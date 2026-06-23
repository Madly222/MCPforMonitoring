"""
Invoice Generator - SSH to billing server, run script, copy XLS, send email.
"""

import os
import re
import ssl
import glob
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from pathlib import Path
from typing import Optional
import paramiko
from scp import SCPClient
from loguru import logger

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except ImportError:
    pass


INVOICE_CONFIG = {
    "ssh_host": os.getenv("INVOICE_SSH_HOST", "172.22.22.60"),
    "ssh_user": os.getenv("INVOICE_SSH_USER", "root"),
    "ssh_password": os.getenv("INVOICE_SSH_PASSWORD", ""),
    "ssh_port": int(os.getenv("INVOICE_SSH_PORT", 22)),
    "script_dir": os.getenv("INVOICE_SSH_SCRIPT_DIR", "/home/polearnik"),
    "script_cmd": os.getenv("INVOICE_SSH_SCRIPT_CMD", "sudo php index.php"),
    "local_dir": Path(__file__).parent.parent.parent / "invoices_logs",
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
    "from": os.getenv("INVOICE_EMAIL_FROM", "control@rapidlink.md"),
    "to": os.getenv("INVOICE_EMAIL_TO", "").split(","),
    "test_mode": os.getenv("INVOICE_TEST_MODE", "false").lower() == "true",
    "test_email": os.getenv("INVOICE_TEST_EMAIL", "admin@rapidlink.md"),
    "cc": os.getenv("INVOICE_EMAIL_CC", "").split(","),
}


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


def generate_invoice() -> dict:
    """
    Main function: SSH to server, run script, copy XLS, send email.
    Returns dict with status and details.
    """
    result = {
        "success": False,
        "message": "",
        "file": None,
        "timestamp": datetime.now().isoformat(),
    }
    
    ssh = None
    
    try:
        # 1. Connect via SSH
        logger.info(f"Invoice: connecting to {INVOICE_CONFIG['ssh_host']}...")
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=INVOICE_CONFIG['ssh_host'],
            port=INVOICE_CONFIG['ssh_port'],
            username=INVOICE_CONFIG['ssh_user'],
            password=INVOICE_CONFIG['ssh_password'],
            timeout=30,
        )
        logger.info("Invoice: SSH connected")
        
        # 2. Run the script
        script_dir = INVOICE_CONFIG['script_dir']
        script_cmd = INVOICE_CONFIG['script_cmd']
        full_cmd = f"cd {script_dir} && {script_cmd}"
        
        logger.info(f"Invoice: running '{full_cmd}'...")
        stdin, stdout, stderr = ssh.exec_command(full_cmd, timeout=120)
        exit_code = stdout.channel.recv_exit_status()
        
        stdout_text = stdout.read().decode('utf-8', errors='ignore')
        stderr_text = stderr.read().decode('utf-8', errors='ignore')
        
        if exit_code != 0:
            logger.error(f"Invoice: script failed with code {exit_code}: {stderr_text}")
            result["message"] = f"Script failed: {stderr_text[:200]}"
            return result
        
        logger.info(f"Invoice: script completed. Output: {stdout_text[:200]}")
        
        # 3. Find XLS file on remote server
        logger.info("Invoice: looking for XLS files...")
        stdin, stdout, stderr = ssh.exec_command(f"ls -t {script_dir}/*.xls 2>/dev/null | head -1")
        remote_xls = stdout.read().decode('utf-8').strip()
        
        if not remote_xls:
            # Try xlsx
            stdin, stdout, stderr = ssh.exec_command(f"ls -t {script_dir}/*.xlsx 2>/dev/null | head -1")
            remote_xls = stdout.read().decode('utf-8').strip()
        
        if not remote_xls:
            logger.error("Invoice: no XLS file found")
            result["message"] = "No XLS file generated"
            return result
        
        logger.info(f"Invoice: found file {remote_xls}")
        
        # 4. Copy file to local
        INVOICE_CONFIG['local_dir'].mkdir(parents=True, exist_ok=True)
        local_filename = f"invoice_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xls"
        if remote_xls.endswith('.xlsx'):
            local_filename = local_filename.replace('.xls', '.xlsx')
        local_path = INVOICE_CONFIG['local_dir'] / local_filename
        
        with SCPClient(ssh.get_transport()) as scp:
            scp.get(remote_xls, str(local_path))
        
        logger.info(f"Invoice: file copied to {local_path}")
        result["file"] = str(local_path)
        # 5. Send email with attachment
        email_ok = send_invoice_email(local_path)
        result["success"] = True
        if email_ok:
            result["message"] = f"Invoice generated and sent: {local_filename}"
        else:
            result["message"] = f"Invoice generated but email failed: {local_filename}"
        return result
    except paramiko.AuthenticationException:
        logger.error("Invoice: SSH authentication failed")
        result["message"] = "SSH authentication failed"
        return result
    except paramiko.SSHException as e:
        logger.error(f"Invoice: SSH error: {e}")
        result["message"] = f"SSH error: {str(e)}"
        return result
    except Exception as e:
        logger.error(f"Invoice: error: {e}")
        result["message"] = f"Error: {str(e)}"
        return result
    finally:
        if ssh:
            ssh.close()


def send_invoice_email(file_path: Path) -> bool:
    """Send email with XLS attachment."""
    
    # Test mode - send to test email only
    if EMAIL_CONFIG.get("test_mode"):
        test_email = EMAIL_CONFIG.get("test_email", "admin@rapidlink.md")
        logger.info(f"Invoice: TEST MODE - sending to {test_email} instead of real recipients")
        recipients_to = [e.strip() for e in test_email.split(",") if e.strip()]
        recipients_cc = []
    else:
        if not EMAIL_CONFIG["to"] or not EMAIL_CONFIG["to"][0]:
            logger.warning("Invoice: no email recipients configured")
            return False
        recipients_to = [e.strip() for e in EMAIL_CONFIG["to"] if e.strip()]
        recipients_cc = [e.strip() for e in EMAIL_CONFIG["cc"] if e.strip()]
    
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_CONFIG["from"]
        msg['To'] = ', '.join(recipients_to)
        if recipients_cc:
            msg['Cc'] = ', '.join(recipients_cc)
        msg['Subject'] = "RAPIDLINK"
        body = ""
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        # Attach file
        with open(file_path, 'rb') as f:
            part = MIMEBase('application', 'vnd.ms-excel')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{file_path.name}"')
            msg.attach(part)
        
        # All recipients
        all_recipients = recipients_to + recipients_cc
        
        refused = smtp_send(msg, all_recipients)
        
        if refused:
            logger.error(f"Invoice: recipients refused: {refused}")
        
        logger.info(f"Invoice: email sent to {all_recipients}")
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"Invoice: SMTP auth failed (проверь ACC_SMTP_USER/PASSWORD): {e}")
        return False
    except smtplib.SMTPRecipientsRefused as e:
        logger.error(f"Invoice: all recipients refused: {e.recipients}")
        return False
    except Exception as e:
        logger.error(f"Invoice: email error: {e}")
        return False


FTP_CONFIG = {
    "host": os.getenv("INVOICE_FTP_HOST", "ftp2.posta.md"),
    "user": os.getenv("INVOICE_FTP_USER", ""),
    "password": os.getenv("INVOICE_FTP_PASSWORD", ""),
    "path": os.getenv("INVOICE_FTP_PATH", "/In/"),
}


def upload_to_ftp(file_path: Path) -> bool:
    """Upload file to Posta Moldovei FTP."""
    
    if not FTP_CONFIG["user"] or not FTP_CONFIG["password"]:
        logger.warning("Invoice: FTP credentials not configured")
        return False
    
    try:
        from ftplib import FTP
        
        logger.info(f"Invoice: connecting to FTP {FTP_CONFIG['host']}...")
        ftp = FTP(FTP_CONFIG['host'], timeout=60)
        ftp.login(FTP_CONFIG['user'], FTP_CONFIG['password'])
        
        # Change to target directory
        if FTP_CONFIG['path']:
            ftp.cwd(FTP_CONFIG['path'])
        
        # Upload file
        with open(file_path, 'rb') as f:
            ftp.storbinary(f'STOR {file_path.name}', f)
        
        ftp.quit()
        logger.info(f"Invoice: file uploaded to FTP: {FTP_CONFIG['path']}{file_path.name}")
        return True
        
    except Exception as e:
        logger.error(f"Invoice: FTP upload error: {e}")
        return False