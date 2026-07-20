"""
ACC.md Water Disconnection Monitor Module
"""

import re
import os
import json
import asyncio
import aiohttp
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from loguru import logger

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except ImportError:
    pass


@dataclass
class ACCStatus:
    ok: bool = True
    last_check: Optional[datetime] = None
    matches: list = field(default_factory=list)
    error: Optional[str] = None


# Configuration
ACC_CONFIG = {
    "base_url": "https://www.acc.md/disconnections",
    "address_pattern": os.getenv("ACC_ADDRESS_PATTERN", r"Asachi\s*,?\s*71"),
    "check_interval": int(os.getenv("ACC_CHECK_INTERVAL", 3600)),
    "timeout": 30,
}

# Email configuration
def _email_config() -> dict:
    """Read notification config live from the runtime store (with env fallback)."""
    from src.web.runtime_config import get_notification_config, get_notification_recipients
    cfg = dict(get_notification_config("acc"))
    cfg["to"] = get_notification_recipients("acc")
    return cfg


def _acc_pattern() -> str:
    """Read the ACC address pattern live from the runtime store."""
    from src.web.runtime_config import get_acc_pattern
    return get_acc_pattern()

CACHE_FILE = Path(__file__).parent.parent.parent / "logs" / "acc_status.json"
NOTIFIED_FILE = Path(__file__).parent.parent.parent / "logs" / "acc_notified.json"

_cached_status: Optional[ACCStatus] = None
_last_check_time: Optional[datetime] = None


def send_email_notification(matches: list) -> bool:
    """Send email notification about water disconnection."""
    
    EMAIL_CONFIG = _email_config()
    if not EMAIL_CONFIG["enabled"]:
        logger.debug("ACC email notifications disabled")
        return False
    
    if not matches:
        return False
    
    logger.info(f"ACC: Sending email notification to {EMAIL_CONFIG['to']}")
    
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_CONFIG["from"]
        msg['To'] = ', '.join(EMAIL_CONFIG["to"])
        _domain = EMAIL_CONFIG["from"].split("@")[-1] if "@" in EMAIL_CONFIG["from"] else None
        msg['Date'] = formatdate(localtime=True)
        msg['Message-ID'] = make_msgid(domain=_domain)
        msg['Subject'] = f"⚠️ ACC.md - Возможно отключение воды! ({datetime.now().strftime('%d.%m.%Y')})"
        
        body = f"""⚠️ ВНИМАНИЕ! Обнаружено отключение воды!

Дата проверки: {datetime.now().strftime('%d.%m.%Y %H:%M')}
Адрес мониторинга: {_acc_pattern()}

{'='*50}
НАЙДЕНО:
{'='*50}

"""
        for match in matches:
            body += f"{match}\n\n"
        
        body += f"""
{'='*50}
Проверьте сайт для подробностей:
https://www.acc.md/disconnections

--
MCP Server Monitor
"""
        
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        server = smtplib.SMTP(EMAIL_CONFIG["smtp_server"], EMAIL_CONFIG["smtp_port"], timeout=30)
        if EMAIL_CONFIG.get("smtp_tls"):
            server.starttls()
        if EMAIL_CONFIG.get("smtp_user"):
            server.login(EMAIL_CONFIG["smtp_user"], EMAIL_CONFIG.get("smtp_password", ""))
        server.sendmail(EMAIL_CONFIG["from"], EMAIL_CONFIG["to"], msg.as_string())
        server.quit()
        
        logger.info("ACC: Email sent successfully!")
        return True
        
    except Exception as e:
        logger.error(f"ACC: Email error: {e}")
        return False


def _match_signature(match: str) -> str:
    """Stable id for one disconnection: its first line."""
    return match.split('\n', 1)[0].strip()


def _match_end(match: str) -> Optional[datetime]:
    """Parse the restoration time ('Восст: dd.mm.yyyy hh:mm') if present."""
    m = re.search(r'Восст[^0-9]*(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2}))?', match)
    if not m:
        return None
    try:
        return datetime(
            int(m.group(3)), int(m.group(2)), int(m.group(1)),
            int(m.group(4) or 23), int(m.group(5) or 59),
        )
    except ValueError:
        return None


def filter_current_matches(matches: list) -> list:
    """Drop disconnections whose restoration time has already passed. Entries
    without a parseable end time (plain notifications) are kept for the day and
    expire via the day-level cache reset."""
    now = datetime.now()
    out = []
    for m in matches:
        end = _match_end(m)
        if end and now > end:
            continue
        out.append(m)
    return out


def get_notified_signatures() -> dict:
    """Return {signature: date} of disconnections already emailed about."""
    try:
        if NOTIFIED_FILE.exists():
            with open(NOTIFIED_FILE, 'r') as f:
                data = json.load(f)
            sigs = data.get('sigs')
            if isinstance(sigs, dict):
                return sigs
    except Exception:
        pass
    return {}


def mark_notified(matches: list):
    """Record disconnections as emailed; prune entries older than today."""
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        sigs = get_notified_signatures()
        for m in matches:
            sigs[_match_signature(m)] = today
        sigs = {s: d for s, d in sigs.items() if d >= today}

        NOTIFIED_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(NOTIFIED_FILE, 'w') as f:
            json.dump({'sigs': sigs, 'updated': datetime.now().isoformat()}, f)
    except Exception as e:
        logger.debug(f"ACC: failed to mark notified: {e}")


def invalidate():
    """Drop the in-memory cache so the next check re-fetches immediately.
    Called when the monitored address pattern changes."""
    global _cached_status, _last_check_time
    _cached_status = None
    _last_check_time = None
    logger.info("ACC: cache invalidated (pattern changed)")


async def fetch_acc_page(date_str: str, tab: int = 2) -> str:
    url = f"{ACC_CONFIG['base_url']}?date={date_str}&tab={tab}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=ACC_CONFIG['timeout'])) as response:
                if response.status == 200:
                    return await response.text()
                return ""
    except Exception as e:
        logger.warning(f"ACC fetch error: {e}")
        return ""


def decode_html_entities(text: str) -> str:
    """Decode HTML entities."""
    replacements = {
        '&nbsp;': ' ',
        '&ndash;': '–',
        '&mdash;': '—',
        '&Icirc;': 'Î',
        '&icirc;': 'î',
        '&bdquo;': '„',
        '&rdquo;': '"',
        '&ldquo;': '"',
        '&laquo;': '«',
        '&raquo;': '»',
        '&amp;': '&',
        '&lt;': '<',
        '&gt;': '>',
        '&quot;': '"',
        '&apos;': "'",
        '&#39;': "'",
    }
    for entity, char in replacements.items():
        text = text.replace(entity, char)
    return text


def parse_notifications(html: str, regex) -> list:
    """Parse tab=1 notifications (text format with planned works)."""
    matches = []
    
    time_match = re.search(
        r'intervalul[^<]*<em><strong>([^<]+)</strong></em>.*?următoarele străzi.*?</p>\s*<p[^>]*><span[^>]*><strong><em>([^<]+)</em></strong>',
        html, 
        re.DOTALL | re.IGNORECASE
    )
    
    if time_match:
        time_date = decode_html_entities(time_match.group(1).strip())
        streets = decode_html_entities(time_match.group(2).strip())
        
        if regex.search(streets):
            match_str = f"[Уведомление] ⚠️ Плановое отключение!\n   📅 {time_date}\n   📍 Улицы: {streets}"
            matches.append(match_str)
    
    return matches


def parse_table_rows(html: str, regex) -> list:
    """Parse tab=2 HTML table and find matching addresses."""
    matches = []
    
    current_sector = ""
    
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE)
    
    for row in rows:
        sector_match = re.search(r"<td colspan=['\"]?\d+['\"]?>([^<]+)</td>", row, re.IGNORECASE)
        if 'sector_title' in row and sector_match:
            current_sector = decode_html_entities(sector_match.group(1).strip())
            continue
        
        tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL | re.IGNORECASE)
        if len(tds) < 4:
            continue
        
        def clean_td(td):
            text = re.sub(r'<[^>]+>', '', td)
            text = decode_html_entities(text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text
        
        tds_clean = [clean_td(td) for td in tds]
        full_row_text = ' '.join(tds_clean)
        
        if regex.search(full_row_text):
            status = tds_clean[0] if tds_clean[0] else ""
            street = tds_clean[2] if len(tds_clean) > 2 else ""
            number = tds_clean[3] if len(tds_clean) > 3 else ""
            problem = tds_clean[4] if len(tds_clean) > 4 else ""
            
            dates = re.findall(r'\d{2}\.\d{2}\.\d{4}(?:\s+\d{2}:\d{2})?', full_row_text)
            date_info = ""
            if dates:
                if len(dates) >= 2:
                    date_info = f"Откл: {dates[0]}, Восст: {dates[1]}"
                else:
                    date_info = f"Дата: {dates[0]}"
            
            match_str = f"[Работы] 📍 {current_sector}: {street} {number}"
            if status:
                match_str += f" [{status}]"
            if problem:
                match_str += f"\n   Причина: {problem}"
            if date_info:
                match_str += f"\n   {date_info}"
            
            matches.append(match_str)
    
    return matches


async def check_acc_status(force: bool = False) -> ACCStatus:
    global _cached_status, _last_check_time
    
    if not force and _cached_status and _last_check_time:
        elapsed = (datetime.now() - _last_check_time).total_seconds()
        if elapsed < ACC_CONFIG['check_interval']:
            _cached_status.matches = filter_current_matches(_cached_status.matches)
            _cached_status.ok = len(_cached_status.matches) == 0
            return _cached_status
    
    logger.info(f"ACC: checking for '{_acc_pattern()}'...")
    
    today = datetime.now().strftime("%Y-%m-%d")
    pattern = _acc_pattern()

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        logger.error(
            f"ACC: invalid address pattern {pattern!r}: {e}. "
            "Fix it in the admin panel (Water outage pattern), e.g. 'Asachi\\s*,?\\s*71'."
        )
        status = ACCStatus(ok=True, last_check=datetime.now(), matches=[], error=f"invalid pattern: {e}")
        _cached_status = status
        _last_check_time = datetime.now()
        return status

    all_matches = []
    
    # Tab 1 = Planned notifications (Уведомления)
    content1 = await fetch_acc_page(today, tab=1)
    if content1:
        matches1 = parse_notifications(content1, regex)
        all_matches.extend(matches1)
    
    # Tab 2 = Current works (Текущие работы)
    content2 = await fetch_acc_page(today, tab=2)
    if content2:
        matches2 = parse_table_rows(content2, regex)
        all_matches.extend(matches2)
    
    all_matches = filter_current_matches(all_matches)

    # Send email for disconnections we haven't emailed about yet (by content,
    # so a newly added address still triggers even if today was already notified)
    if all_matches:
        notified = get_notified_signatures()
        new_matches = [m for m in all_matches if _match_signature(m) not in notified]
        if new_matches and send_email_notification(new_matches):
            mark_notified(new_matches)
    
    status = ACCStatus(
        ok=len(all_matches) == 0,
        last_check=datetime.now(),
        matches=all_matches,
    )
    
    _cached_status = status
    _last_check_time = datetime.now()
    
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, 'w') as f:
            json.dump({
                "ok": status.ok,
                "last_check": status.last_check.isoformat() if status.last_check else None,
                "matches": status.matches,
                "date_checked": today,
            }, f)
    except Exception as e:
        logger.debug(f"ACC: failed to save cache: {e}")
    
    if all_matches:
        logger.warning(f"ACC: FOUND {len(all_matches)} matches!")
    else:
        logger.info("ACC: no disconnections found")
    
    return status


def load_cached_status() -> Optional[ACCStatus]:
    global _cached_status, _last_check_time
    
    if _cached_status:
        _cached_status.matches = filter_current_matches(_cached_status.matches)
        _cached_status.ok = len(_cached_status.matches) == 0
        return _cached_status
    
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, 'r') as f:
                data = json.load(f)
                
                cached_date = data.get('date_checked')
                today = datetime.now().strftime("%Y-%m-%d")
                if cached_date != today:
                    return None
                
                matches = filter_current_matches(data.get('matches', []))
                _cached_status = ACCStatus(
                    ok=len(matches) == 0,
                    last_check=datetime.fromisoformat(data['last_check']) if data.get('last_check') else None,
                    matches=matches,
                )
                if _cached_status.last_check:
                    _last_check_time = _cached_status.last_check
                return _cached_status
    except Exception as e:
        logger.debug(f"ACC: failed to load cache: {e}")
    return None


def get_status_dict() -> dict:
    status = load_cached_status()
    if status:
        return {
            "ok": status.ok,
            "last_check": status.last_check.isoformat() if status.last_check else None,
            "matches_count": len(status.matches),
            "matches": status.matches,
        }
    return {
        "ok": True,
        "last_check": None,
        "matches_count": 0,
        "matches": [],
    }
