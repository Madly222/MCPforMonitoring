"""
Email Invoice Sender
Queries billing DB for clients, generates PDF invoices, sends emails.
"""

import os
import ssl
import smtplib
from datetime import datetime
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional
import paramiko
from loguru import logger

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except ImportError:
    pass


BILLING_CONFIG = {
    "ssh_host": os.getenv("INVOICE_SSH_HOST", "172.22.22.60"),
    "ssh_user": os.getenv("INVOICE_SSH_USER", "root"),
    "ssh_password": os.getenv("INVOICE_SSH_PASSWORD", ""),
    "ssh_port": int(os.getenv("INVOICE_SSH_PORT", 22)),
    "db_name": os.getenv("BILLING_DB_NAME", "billing"),
    "db_user": os.getenv("BILLING_DB_USER", "billing"),
    "db_password": os.getenv("BILLING_DB_PASSWORD", ""),
}

# --- Настройки SMTP (порт 587 + STARTTLS + логин = отправка на внешние почты) ---
SMTP_CONFIG = {
    "server": os.getenv("ACC_SMTP_SERVER", "mail.rapidlink.md"),
    "port": int(os.getenv("ACC_SMTP_PORT", 587)),
    "user": os.getenv("ACC_SMTP_USER", ""),            # напр. control@rapidlink.md
    "password": os.getenv("ACC_SMTP_PASSWORD", ""),
    "use_tls": os.getenv("ACC_SMTP_TLS", "true").lower() == "true",
    "from": os.getenv("INVOICE_EMAIL_FROM", "control@rapidlink.md"),
}

EMAIL_CONFIG = {
    "cc": [e.strip() for e in os.getenv("EMAIL_INVOICE_CC", "").split(",") if e.strip()],
    "test_mode": os.getenv("EMAIL_INVOICE_TEST_MODE", "true").lower() == "true",
    "test_email": os.getenv("EMAIL_INVOICE_TEST_EMAIL", os.getenv("INVOICE_TEST_EMAIL", "admin@rapidlink.md")),
}

# Мердж инвойсов в биллинге. По умолчанию ВЫКЛЮЧЕН (ломает текущую систему).
# Чтобы вернуть - поставить в .env: EMAIL_INVOICE_MERGE=true
MERGE_ENABLED = os.getenv("EMAIL_INVOICE_MERGE", "false").lower() == "true"

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
CLIENTS_FILE = CONFIG_DIR / "invoice_clienti_email.txt"
OUTPUT_DIR = Path(__file__).parent.parent.parent / "invoices_logs"

EMAIL_BODY = """Stimate client,
Vă transmitem factura lunară pentru serviciile de internet pentru perioada curenta. 
Vă rugăm să efectuați achitarea în termenul indicat în factură, pentru a evita eventuale întreruperi ale serviciului."""


def smtp_send(msg: MIMEMultipart, to_addrs: list) -> dict:
    """
    Отправляет готовый MIME-объект через SMTP.
    Возвращает dict отклонённых получателей (пустой = все приняты).
    Бросает исключение при ошибке соединения/аутентификации/полном отказе.
    """
    cfg = SMTP_CONFIG
    with smtplib.SMTP(cfg["server"], cfg["port"], timeout=30) as server:
        server.ehlo()
        if cfg["use_tls"]:
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        if cfg["user"] and cfg["password"]:
            server.login(cfg["user"], cfg["password"])
        refused = server.sendmail(cfg["from"], to_addrs, msg.as_string())
    return refused


def load_client_names() -> list:
    """Load client names from config file."""
    names = []
    try:
        if CLIENTS_FILE.exists():
            with open(CLIENTS_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        names.append(line)
            logger.debug(f"EmailInvoice: loaded {len(names)} client names")
    except Exception as e:
        logger.error(f"EmailInvoice: failed to load client names: {e}")
    return names


def query_client_invoices(ssh, client_names: list) -> tuple:
    """Query billing database for unpaid invoices. Returns (invoices, all_paid_names, not_found_names)."""
    results = []
    all_paid = []
    not_found = []
    
    db_user = BILLING_CONFIG['db_user']
    db_pass = BILLING_CONFIG['db_password']
    db_name = BILLING_CONFIG['db_name']
    
    for name in client_names:
        parts = name.strip().split()
        
        # Build flexible search - check each word against both firstname and lastname
        safe_parts = [p.replace("'", "''").replace("\\", "\\\\") for p in parts]
        
        if len(parts) >= 2:
            # Try all combinations: each part can be in firstname or lastname
            conditions = []
            # All parts combined search (CONCAT firstname lastname)
            all_parts = '%'.join(safe_parts)
            conditions.append(f"CONCAT(c.firstname, ' ', c.lastname) LIKE '%{all_parts}%'")
            # Reverse order
            all_parts_rev = '%'.join(reversed(safe_parts))
            conditions.append(f"CONCAT(c.firstname, ' ', c.lastname) LIKE '%{all_parts_rev}%'")
            # Last word in lastname, rest in firstname
            conditions.append(f"(c.firstname LIKE '%{' '.join(safe_parts[:-1])}%' AND c.lastname LIKE '%{safe_parts[-1]}%')")
            # First word in firstname, rest in lastname
            conditions.append(f"(c.firstname LIKE '%{safe_parts[0]}%' AND c.lastname LIKE '%{' '.join(safe_parts[1:])}%')")
            where_clause = f"({' OR '.join(conditions)})"
        else:
            safe_name = safe_parts[0]
            where_clause = f"(c.firstname LIKE '%{safe_name}%' OR c.lastname LIKE '%{safe_name}%')"
        
        query = f"""
        SELECT 
            i.id AS invoice_id,
            i.date AS invoice_date,
            i.total AS amount,
            c.id AS client_id,
            CONCAT(c.firstname, ' ', c.lastname) AS client_name,
            c.email AS client_email,
            c.address1 AS client_address,
            (SELECT GROUP_CONCAT(description SEPARATOR '; ') FROM tblinvoiceitems WHERE invoiceid = i.id) AS description
        FROM tblinvoices i
        JOIN tblclients c ON c.id = i.userid
        WHERE i.status = 'Unpaid' AND {where_clause}
        ORDER BY i.id;
        """
        
        cmd = f'mysql -u {db_user} -p"{db_pass}" {db_name} -N -e "{query}"'
        
        stdin, stdout, stderr = ssh.exec_command(cmd)
        output = stdout.read().decode('utf-8', errors='ignore').strip()
        
        if output:
            for line in output.split('\n'):
                parts = line.split('\t')
                if len(parts) >= 7:
                    results.append({
                        'invoice_id': parts[0],
                        'invoice_date': parts[1],
                        'amount': parts[2],
                        'client_id': parts[3],
                        'client_name': parts[4],
                        'client_email': parts[5] if parts[5] and parts[5] != 'NULL' else '',
                        'client_address': parts[6] if len(parts) > 6 else '',
                        'description': parts[7] if len(parts) > 7 else '',
                        'search_name': name,
                    })
        else:
            # No unpaid invoices - check if client exists at all
            check_query = f"""SELECT COUNT(*) FROM tblclients c WHERE {where_clause}"""
            check_cmd = f'mysql -u {db_user} -p"{db_pass}" {db_name} -N -e "{check_query}"'
            stdin, stdout, stderr = ssh.exec_command(check_cmd)
            count = stdout.read().decode('utf-8', errors='ignore').strip()
            if count and int(count) > 0:
                all_paid.append(name)
            else:
                not_found.append(name)
    
    return results, all_paid, not_found


def generate_pdf_via_ssh(ssh, invoice_id: int) -> Optional[bytes]:
    """Generate PDF invoice via WHMCS on billing server."""
    try:
        cmd = f'cd /var/www/billing && sudo -u www-data php /var/www/billing/gen_invoice_pdf.php {invoice_id}'
        stdin, stdout, stderr = ssh.exec_command(cmd)
        pdf_path = stdout.read().decode('utf-8', errors='ignore').strip()
        err_output = stderr.read().decode('utf-8', errors='ignore').strip()
        
        if err_output:
            logger.debug(f"EmailInvoice: PHP stderr: {err_output[:200]}")
        
        if not pdf_path or not pdf_path.startswith('/tmp/invoice_'):
            logger.error(f"EmailInvoice: PDF generation failed for invoice {invoice_id}, output: {pdf_path[:100] if pdf_path else 'empty'}")
            return None
        
        sftp = ssh.open_sftp()
        with sftp.file(pdf_path, 'rb') as f:
            pdf_data = f.read()
        sftp.close()
        
        ssh.exec_command(f'rm -f {pdf_path}')
        
        logger.info(f"EmailInvoice: PDF generated for invoice {invoice_id}, size {len(pdf_data)} bytes")
        return pdf_data
        
    except Exception as e:
        logger.error(f"EmailInvoice: PDF generation error: {e}")
        return None


def merge_invoices_via_ssh(ssh, invoice_ids: list) -> Optional[str]:
    """Merge multiple invoices into one via WHMCS."""
    try:
        ids_str = ','.join(str(i) for i in invoice_ids)
        logger.info(f"EmailInvoice: merging invoices {ids_str}")
        
        cmd = f'cd /var/www/billing && sudo -u www-data php /var/www/billing/merge_invoices.php {ids_str}'
        stdin, stdout, stderr = ssh.exec_command(cmd)
        merged_id = stdout.read().decode('utf-8', errors='ignore').strip()
        err = stderr.read().decode('utf-8', errors='ignore').strip()
        
        if merged_id and merged_id.isdigit():
            logger.info(f"EmailInvoice: merged into invoice {merged_id}")
            return merged_id
        else:
            logger.error(f"EmailInvoice: merge failed: {merged_id} {err}")
            return None
    except Exception as e:
        logger.error(f"EmailInvoice: merge error: {e}")
        return None


def send_invoice_email(invoice: dict, pdf_data: bytes) -> bool:
    """Send email with PDF attachment."""
    
    original_email = invoice['client_email']
    
    if EMAIL_CONFIG['test_mode']:
        to_list = [e.strip() for e in EMAIL_CONFIG['test_email'].split(',') if e.strip()]
        cc_list = []
        subject = f"Factura #{invoice['invoice_id']} ({original_email})"
        logger.info(f"EmailInvoice: TEST MODE -> {to_list} (real: {original_email})")
    else:
        to_list = [original_email]
        cc_list = list(EMAIL_CONFIG['cc'])
        subject = f"Factura #{invoice['invoice_id']}"
    
    all_recipients = to_list + cc_list
    
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_CONFIG['from']
        msg['To'] = ', '.join(to_list)
        if cc_list:
            msg['Cc'] = ', '.join(cc_list)
        msg['Subject'] = subject
        
        msg.attach(MIMEText(EMAIL_BODY, 'plain', 'utf-8'))
        
        part = MIMEBase('application', 'pdf')
        part.set_payload(pdf_data)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="factura_{invoice["invoice_id"]}.pdf"')
        msg.attach(part)
        
        refused = smtp_send(msg, all_recipients)
        
        if refused:
            logger.error(f"EmailInvoice: invoice {invoice['invoice_id']} - recipients refused: {refused}")
            # если в боевом режиме отклонён именно адрес клиента - считаем отправку неудачной
            if not EMAIL_CONFIG['test_mode'] and original_email in refused:
                return False
        
        logger.info(f"EmailInvoice: sent invoice {invoice['invoice_id']} to {to_list} cc {cc_list}")
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"EmailInvoice: SMTP auth failed (проверь ACC_SMTP_USER/PASSWORD): {e}")
        return False
    except smtplib.SMTPRecipientsRefused as e:
        logger.error(f"EmailInvoice: all recipients refused, invoice {invoice['invoice_id']}: {e.recipients}")
        return False
    except Exception as e:
        logger.error(f"EmailInvoice: send error: {e}")
        return False


def send_email_invoices() -> dict:
    """Main function: query billing, merge invoices per client, generate PDFs, send emails."""
    result = {
        "success": False,
        "message": "",
        "total_unpaid": 0,
        "sent": 0,
        "failed": 0,
        "no_email": [],
        "not_found": [],
        "all_paid": [],
        "details": [],
        "timestamp": datetime.now().isoformat(),
    }
    
    ssh = None
    
    try:
        client_names = load_client_names()
        if not client_names:
            result["message"] = "No clients in invoice_clienti_email.txt"
            return result
        
        logger.info(f"EmailInvoice: searching for {len(client_names)} clients...")
        
        logger.info(f"EmailInvoice: connecting to {BILLING_CONFIG['ssh_host']}...")
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=BILLING_CONFIG['ssh_host'],
            port=BILLING_CONFIG['ssh_port'],
            username=BILLING_CONFIG['ssh_user'],
            password=BILLING_CONFIG['ssh_password'],
            timeout=30,
        )
        
        invoices, all_paid, not_found = query_client_invoices(ssh, client_names)
        
        result["not_found"] = not_found
        result["all_paid"] = all_paid
        result["total_unpaid"] = len(invoices)
        
        if not invoices:
            result["success"] = True
            result["message"] = "No unpaid invoices found"
            return result
        
        logger.info(f"EmailInvoice: found {len(invoices)} unpaid invoices")
        
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        
        # Group invoices by client email
        clients = {}
        for inv in invoices:
            email = inv['client_email']
            if not email:
                result["no_email"].append(inv['client_name'])
                result["details"].append({
                    "invoice_id": inv['invoice_id'],
                    "client": inv['client_name'],
                    "email": "",
                    "amount": inv['amount'],
                    "status": "no email"
                })
                continue
            if email not in clients:
                clients[email] = {"name": inv['client_name'], "invoices": []}
            clients[email]["invoices"].append(inv)
        
        # Process each client
        for email, client_data in clients.items():
            inv_list = client_data["invoices"]
            inv_ids = [inv['invoice_id'] for inv in inv_list]

            # Решаем, что отправлять: один объединённый инвойс (если мердж включён)
            # или каждый инвойс по отдельности (мердж выключен - по умолчанию).
            if MERGE_ENABLED and len(inv_ids) > 1:
                merged_id = merge_invoices_via_ssh(ssh, inv_ids)
                if not merged_id:
                    result["failed"] += len(inv_ids)
                    for inv in inv_list:
                        result["details"].append({
                            "invoice_id": inv['invoice_id'],
                            "client": inv['client_name'],
                            "email": email,
                            "amount": inv['amount'],
                            "status": "merge failed"
                        })
                    continue
                targets = [{
                    'invoice_id': merged_id,
                    'amount': sum(float(inv['amount']) for inv in inv_list),
                    'merged_count': len(inv_ids),
                }]
            else:
                # Без мерджа: каждый инвойс - отдельное письмо со своим PDF
                targets = [{
                    'invoice_id': inv['invoice_id'],
                    'amount': float(inv['amount']),
                    'merged_count': 1,
                } for inv in inv_list]

            for tgt in targets:
                invoice_id = tgt['invoice_id']

                # Generate PDF
                pdf_data = generate_pdf_via_ssh(ssh, int(invoice_id))
                if not pdf_data:
                    result["failed"] += 1
                    result["details"].append({
                        "invoice_id": invoice_id,
                        "client": client_data["name"],
                        "email": email,
                        "amount": tgt['amount'],
                        "status": "PDF failed"
                    })
                    continue

                # Save PDF locally
                pdf_path = OUTPUT_DIR / f"factura_{invoice_id}.pdf"
                with open(pdf_path, 'wb') as f:
                    f.write(pdf_data)

                # Create invoice dict for email
                inv_for_email = {
                    'invoice_id': invoice_id,
                    'client_name': client_data["name"],
                    'client_email': email,
                    'amount': tgt['amount'],
                }

                # Send email
                if send_invoice_email(inv_for_email, pdf_data):
                    result["sent"] += 1
                    status = f"sent (merged {tgt['merged_count']})" if tgt['merged_count'] > 1 else "sent"
                    result["details"].append({
                        "invoice_id": invoice_id,
                        "client": client_data["name"],
                        "email": email,
                        "amount": tgt['amount'],
                        "status": status
                    })
                else:
                    result["failed"] += 1
                    result["details"].append({
                        "invoice_id": invoice_id,
                        "client": client_data["name"],
                        "email": email,
                        "amount": tgt['amount'],
                        "status": "send failed"
                    })
        
        result["success"] = True
        messages = [f"Found {result['total_unpaid']} unpaid"]
        messages.append(f"Sent {result['sent']}")
        if result["failed"]:
            messages.append(f"Failed {result['failed']}")
        if result["no_email"]:
            messages.append(f"No email: {len(result['no_email'])}")
        if result["all_paid"]:
            messages.append(f"All paid: {len(result['all_paid'])}")
        if result["not_found"]:
            messages.append(f"Not found: {len(result['not_found'])}")
        result["message"] = " | ".join(messages)
        
        return result
        
    except Exception as e:
        logger.error(f"EmailInvoice: error: {e}")
        result["message"] = f"Error: {str(e)}"
        return result
    finally:
        if ssh:
            ssh.close()