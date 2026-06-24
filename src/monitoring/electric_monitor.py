"""
Premier Energy Distribution - Electricity Disconnection Monitor
"""

import re
import os
import json
import asyncio
import aiohttp
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple
from dataclasses import dataclass, field

from loguru import logger

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except ImportError:
    pass


@dataclass
class ElectricStatus:
    ok: bool = True
    last_check: Optional[datetime] = None
    matches: list = field(default_factory=list)
    error: Optional[str] = None


ELECTRIC_CONFIG = {
    "base_url": "https://premierenergydistribution.md",
    "check_interval": int(os.getenv("ELECTRIC_CHECK_INTERVAL", 3600)),
    "timeout": 15,
    "days_ahead": 3,
}

def _email_config() -> dict:
    """Read notification config live from the runtime store (with env fallback)."""
    from src.web.runtime_config import get_notification_config, get_notification_recipients
    cfg = dict(get_notification_config("electric"))
    cfg["to"] = get_notification_recipients("electric")
    return cfg

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
ADDRESSES_FILE = CONFIG_DIR / "electric_addresses.txt"
CACHE_FILE = Path(__file__).parent.parent.parent / "logs" / "electric_status.json"
NOTIFIED_FILE = Path(__file__).parent.parent.parent / "logs" / "electric_notified.json"

_cached_status: Optional[ElectricStatus] = None
_last_check_time: Optional[datetime] = None


def parse_house_number(num_str: str) -> Tuple[int, str]:
    """Parse house number like '12', '12/2', '12A' into (base_number, suffix)."""
    num_str = num_str.strip()
    # Match: digits, then optional suffix (/2, A, B, etc.)
    match = re.match(r'^(\d+)(.*)$', num_str)
    if match:
        return int(match.group(1)), match.group(2).strip()
    return 0, num_str


def house_in_range(target: str, range_str: str) -> bool:
    """Check if target house number is in a range like '15-23' or matches exactly."""
    target_base, target_suffix = parse_house_number(target)
    
    # Check for range: 15-23
    range_match = re.match(r'^(\d+)\s*[-–]\s*(\d+)$', range_str.strip())
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        # For ranges, only check base number (ignore suffix)
        return start <= target_base <= end
    
    # Exact match (including suffix)
    range_base, range_suffix = parse_house_number(range_str)
    if target_base == range_base:
        # If target has suffix, it must match
        if target_suffix:
            return target_suffix == range_suffix
        # If target has no suffix, match any
        return True
    
    return False


def find_house_in_list(target: str, houses_text: str) -> bool:
    """Check if target house is in a list like '12/1, 12/2, 15-23, 25A'."""
    # Split by comma and space, but be careful with ranges
    # Pattern to extract house numbers/ranges
    pattern = r'(\d+(?:/\d+)?(?:[A-Za-z])?(?:\s*[-–]\s*\d+)?)'
    houses = re.findall(pattern, houses_text)
    
    for house in houses:
        if house_in_range(target, house):
            return True
    return False


def send_email_notification(matches: list) -> bool:
    """Send email notification about electricity disconnection."""
    
    EMAIL_CONFIG = _email_config()
    if not EMAIL_CONFIG["enabled"]:
        logger.debug("Electric email notifications disabled")
        return False
    
    if not matches:
        return False
    
    logger.info(f"Electric: Sending email notification to {EMAIL_CONFIG['to']}")
    
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_CONFIG["from"]
        msg['To'] = ', '.join(EMAIL_CONFIG["to"])
        msg['Subject'] = f"⚡ Premier Energy - Запланированное отключение электричества! ({datetime.now().strftime('%d.%m.%Y')})"
        
        body = f"""⚡ ВНИМАНИЕ! Запланированное отключение электричества!

Дата проверки: {datetime.now().strftime('%d.%m.%Y %H:%M')}

{'='*50}
НАЙДЕНО:
{'='*50}

"""
        for match in matches:
            body += f"{match}\n\n"
        
        body += f"""
{'='*50}
Проверьте сайт для подробностей:
https://premierenergydistribution.md/ru/toate-lucrarile-programate

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
        
        logger.info("Electric: Email sent successfully!")
        return True
        
    except Exception as e:
        logger.error(f"Electric: Email error: {e}")
        return False


def get_notified_dates() -> set:
    """Get set of dates for which notifications were already sent."""
    try:
        if NOTIFIED_FILE.exists():
            with open(NOTIFIED_FILE, 'r') as f:
                data = json.load(f)
                return set(data.get('dates', []))
    except:
        pass
    return set()


def mark_notified(dates: list):
    """Mark dates as notified."""
    try:
        existing = get_notified_dates()
        existing.update(dates)
        today = datetime.now().strftime('%Y-%m-%d')
        existing = {d for d in existing if d >= today}
        
        NOTIFIED_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(NOTIFIED_FILE, 'w') as f:
            json.dump({'dates': list(existing), 'updated': datetime.now().isoformat()}, f)
    except Exception as e:
        logger.debug(f"Electric: failed to mark notified: {e}")


def cleanup_old_notifications():
    """Remove old notification records."""
    try:
        if NOTIFIED_FILE.exists():
            today = datetime.now().strftime('%Y-%m-%d')
            with open(NOTIFIED_FILE, 'r') as f:
                data = json.load(f)
            
            old_dates = data.get('dates', [])
            new_dates = [d for d in old_dates if d >= today]
            
            if len(new_dates) != len(old_dates):
                with open(NOTIFIED_FILE, 'w') as f:
                    json.dump({'dates': new_dates, 'updated': datetime.now().isoformat()}, f)
                logger.debug(f"Electric: cleaned {len(old_dates) - len(new_dates)} old notifications")
    except Exception as e:
        logger.debug(f"Electric: cleanup error: {e}")


def load_addresses() -> list:
    """Load addresses to monitor. Format: 'Street' or 'Street HouseNumber'."""
    addresses = []
    try:
        if ADDRESSES_FILE.exists():
            with open(ADDRESSES_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        addresses.append(line)
            logger.debug(f"Electric: loaded {len(addresses)} addresses: {addresses}")
    except Exception as e:
        logger.error(f"Electric: failed to load addresses: {e}")
    return addresses


def parse_address(addr: str) -> Tuple[str, Optional[str]]:
    """Parse address into (street_name, house_number or None)."""
    parts = addr.strip().split()
    if len(parts) >= 2:
        # Last part might be house number
        last = parts[-1]
        if re.match(r'^\d+', last):
            # Has house number
            street = ' '.join(parts[:-1])
            return street, last
    return addr, None


async def fetch_page(session: aiohttp.ClientSession, url: str) -> str:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=ELECTRIC_CONFIG['timeout'])) as response:
            if response.status == 200:
                return await response.text()
            return ""
    except Exception as e:
        logger.debug(f"Electric fetch error: {e}")
        return ""


def clean_html(content: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r'<[^>]+>', ' ', content)
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&ndash;', '–')
    text = text.replace('&mdash;', '—')
    text = re.sub(r'&[^;]+;', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text


def find_in_chisinau(content: str, addresses: list, date_str: str) -> list:
    """Find addresses only in Chisinau sections."""
    matches = []
    
    text = clean_html(content)
    
    # Split by "Chişinău, sectorul" to get Chisinau blocks
    parts = re.split(r'(Chişinău,\s*sectorul\s+\w+)', text, flags=re.IGNORECASE)
    
    i = 1
    while i < len(parts):
        if not re.match(r'Chişinău,\s*sectorul', parts[i], re.IGNORECASE):
            i += 1
            continue
        
        header = parts[i]
        content_block = parts[i + 1] if i + 1 < len(parts) else ""
        
        # Skip sub-localities (com. Băcioi, or. Durleşti, etc.)
        if re.search(r',\s*(com\.|or\.|s\.)\s*\w+', header, re.IGNORECASE):
            i += 2
            continue
        
        sector_match = re.search(r'sectorul\s+(\w+)', header, re.IGNORECASE)
        sector = sector_match.group(1) if sector_match else ""
        
        block = content_block[:1000]
        
        for addr in addresses:
            street, house_num = parse_address(addr)
            
            # Find street in block
            street_pattern = re.compile(
                r'(?:str\.\s*|bd\.\s*|str-la\s*\d*\s*)?' + re.escape(street) + r'(?:\s+(?:bd\.|str\.|str-la))?\s*([\d\s,/\-–A-Za-z]+?)(?=\s+în\s+intervalul|\s+pentru|\s*$|[A-Z][a-z]+\s+\d)',
                re.IGNORECASE
            )
            
            street_match = street_pattern.search(block)
            if street_match:
                houses_text = street_match.group(1) if street_match.lastindex else ""
                
                # If we need specific house number, check it
                if house_num:
                    if not find_house_in_list(house_num, houses_text):
                        continue
                
                time_match = re.search(r'(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})', block)
                time_info = time_match.group(0) if time_match else ""
                
                # Extract context around street
                street_pos = block.lower().find(street.lower())
                if street_pos >= 0:
                    start = max(0, street_pos - 20)
                    end = min(len(block), street_pos + 200)
                    display = block[start:end].strip()
                else:
                    display = block[:200].strip()
                
                match_str = f"[{date_str}] ⚡ {addr} (Chișinău, {sector})"
                if time_info:
                    match_str += f" ⏰ {time_info}"
                match_str += f"\n   📍 ...{display}..."
                
                if match_str not in matches:
                    matches.append(match_str)
        
        i += 2
    
    return matches


def filter_current_matches(matches: list) -> list:
    """Filter out past dates, keep only today and future."""
    today = datetime.now().strftime('%Y-%m-%d')
    filtered = []
    
    for match in matches:
        date_match = re.search(r'\[(\d{4}-\d{2}-\d{2})\]', match)
        if date_match:
            match_date = date_match.group(1)
            if match_date >= today:
                filtered.append(match)
        else:
            filtered.append(match)
    
    return filtered


async def check_electric_status(force: bool = False) -> ElectricStatus:
    global _cached_status, _last_check_time
    
    cleanup_old_notifications()
    
    if not force and _cached_status and _last_check_time:
        elapsed = (datetime.now() - _last_check_time).total_seconds()
        if elapsed < ELECTRIC_CONFIG['check_interval']:
            _cached_status.matches = filter_current_matches(_cached_status.matches)
            _cached_status.ok = len(_cached_status.matches) == 0
            return _cached_status
    
    addresses = load_addresses()
    if not addresses:
        logger.warning("Electric: no addresses in config/electric_addresses.txt")
        return ElectricStatus(ok=True, last_check=datetime.now(), matches=[])
    
    logger.info(f"Electric: checking {len(addresses)} addresses: {addresses}")
    
    all_matches = []
    matched_dates = []
    today = datetime.now().strftime('%Y-%m-%d')
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
    }
    
    async with aiohttp.ClientSession(headers=headers) as session:
        urls = []
        for days in range(0, ELECTRIC_CONFIG['days_ahead'] + 1):
            date = datetime.now() + timedelta(days=days)
            date_str = date.strftime("%Y-%m-%d")
            url = f"{ELECTRIC_CONFIG['base_url']}/ro/lucrari-programate-{date_str}"
            urls.append((date_str, url))
        
        tasks = [fetch_page(session, url) for _, url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, Exception) or not result:
                continue
            
            date_str = urls[i][0]
            matches = find_in_chisinau(result, addresses, date_str)
            
            if matches:
                matched_dates.append(date_str)
            
            all_matches.extend([m for m in matches if m not in all_matches])
    
    all_matches = filter_current_matches(all_matches)
    
    if all_matches:
        notified_dates = get_notified_dates()
        new_dates = [d for d in matched_dates if d not in notified_dates and d >= today]
        
        if new_dates:
            new_matches = [m for m in all_matches if any(d in m for d in new_dates)]
            if new_matches and send_email_notification(new_matches):
                mark_notified(new_dates)
    
    status = ElectricStatus(
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
                "date_checked": datetime.now().strftime("%Y-%m-%d"),
            }, f)
    except Exception as e:
        logger.debug(f"Electric: cache save error: {e}")
    
    if all_matches:
        logger.warning(f"Electric: FOUND {len(all_matches)} matches!")
    else:
        logger.info("Electric: no disconnections found")
    
    return status


def load_cached_status() -> Optional[ElectricStatus]:
    global _cached_status, _last_check_time
    
    if _cached_status:
        _cached_status.matches = filter_current_matches(_cached_status.matches)
        _cached_status.ok = len(_cached_status.matches) == 0
        return _cached_status
    
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, 'r') as f:
                data = json.load(f)
                matches = filter_current_matches(data.get('matches', []))
                _cached_status = ElectricStatus(
                    ok=len(matches) == 0,
                    last_check=datetime.fromisoformat(data['last_check']) if data.get('last_check') else None,
                    matches=matches,
                )
                if _cached_status.last_check:
                    _last_check_time = _cached_status.last_check
                return _cached_status
    except Exception as e:
        logger.debug(f"Electric: cache load error: {e}")
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
    return {"ok": True, "last_check": None, "matches_count": 0, "matches": []}
