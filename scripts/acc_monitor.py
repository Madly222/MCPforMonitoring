"""
ACC.md Water Disconnection Monitor Module

Checks for water disconnections at specified address.
Used by API and standalone script.
"""

import re
import os
import json
import asyncio
import aiohttp
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from loguru import logger


@dataclass
class ACCStatus:
    """ACC check result."""
    ok: bool = True  # True = no disconnections, False = found
    last_check: Optional[datetime] = None
    matches: list = field(default_factory=list)
    error: Optional[str] = None


# Configuration
ACC_CONFIG = {
    "base_url": "https://www.acc.md/disconnections",
    "address_pattern": r"Asachi\s*,?\s*71\b",
    "check_interval": 3600,  # 1 hour between checks
    "timeout": 30,
}

# Cache file for storing last check result
CACHE_FILE = Path(__file__).parent.parent / "logs" / "acc_status.json"

# In-memory cache
_cached_status: Optional[ACCStatus] = None
_last_check_time: Optional[datetime] = None


async def fetch_acc_page(date_str: str, tab: int = 2) -> str:
    """Fetch ACC disconnections page content."""
    url = f"{ACC_CONFIG['base_url']}?date={date_str}&tab={tab}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ro-MD,ro;q=0.9,en;q=0.8",
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=ACC_CONFIG['timeout'])) as response:
                if response.status == 200:
                    return await response.text()
                else:
                    logger.warning(f"ACC fetch failed: HTTP {response.status}")
                    return ""
    except asyncio.TimeoutError:
        logger.warning(f"ACC fetch timeout: {url}")
        return ""
    except Exception as e:
        logger.warning(f"ACC fetch error: {e}")
        return ""


def find_address_in_content(content: str, pattern: str) -> list:
    """Search for address pattern in page content."""
    matches = []
    regex = re.compile(pattern, re.IGNORECASE)
    
    for line in content.split('\n'):
        if regex.search(line):
            # Clean HTML tags
            clean_line = re.sub(r'<[^>]+>', ' ', line)
            clean_line = re.sub(r'\s+', ' ', clean_line).strip()
            if clean_line and len(clean_line) > 5:
                matches.append(clean_line[:200])  # Limit length
    
    return matches


async def check_acc_status(force: bool = False) -> ACCStatus:
    """
    Check ACC.md for disconnections.
    Uses cache to avoid frequent requests.
    """
    global _cached_status, _last_check_time
    
    # Return cached result if recent enough
    if not force and _cached_status and _last_check_time:
        elapsed = (datetime.now() - _last_check_time).total_seconds()
        if elapsed < ACC_CONFIG['check_interval']:
            logger.debug(f"ACC: returning cached status (age: {int(elapsed)}s)")
            return _cached_status
    
    logger.info("ACC: checking for disconnections...")
    
    today = datetime.now().strftime("%Y-%m-%d")
    pattern = ACC_CONFIG['address_pattern']
    all_matches = []
    
    # Check both tabs
    for tab in [1, 2]:
        content = await fetch_acc_page(today, tab)
        if content:
            matches = find_address_in_content(content, pattern)
            if matches:
                tab_name = "Уведомления" if tab == 1 else "Текущие работы"
                for m in matches:
                    all_matches.append(f"[{tab_name}] {m}")
    
    # Create status
    status = ACCStatus(
        ok=len(all_matches) == 0,
        last_check=datetime.now(),
        matches=all_matches,
        error=None
    )
    
    # Update cache
    _cached_status = status
    _last_check_time = datetime.now()
    
    # Save to file for persistence
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, 'w') as f:
            json.dump({
                "ok": status.ok,
                "last_check": status.last_check.isoformat() if status.last_check else None,
                "matches": status.matches,
            }, f)
    except Exception as e:
        logger.debug(f"ACC: failed to save cache: {e}")
    
    if all_matches:
        logger.warning(f"ACC: FOUND {len(all_matches)} matches!")
    else:
        logger.info("ACC: no disconnections found")
    
    return status


def load_cached_status() -> Optional[ACCStatus]:
    """Load status from cache file."""
    global _cached_status, _last_check_time
    
    if _cached_status:
        return _cached_status
    
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, 'r') as f:
                data = json.load(f)
                _cached_status = ACCStatus(
                    ok=data.get('ok', True),
                    last_check=datetime.fromisoformat(data['last_check']) if data.get('last_check') else None,
                    matches=data.get('matches', []),
                )
                if _cached_status.last_check:
                    _last_check_time = _cached_status.last_check
                return _cached_status
    except Exception as e:
        logger.debug(f"ACC: failed to load cache: {e}")
    
    return None


def get_status_dict() -> dict:
    """Get status as dictionary for API response."""
    status = load_cached_status()
    
    if status:
        return {
            "ok": status.ok,
            "last_check": status.last_check.isoformat() if status.last_check else None,
            "matches_count": len(status.matches),
            "matches": status.matches[:5],  # Limit to 5 for API
        }
    
    return {
        "ok": True,
        "last_check": None,
        "matches_count": 0,
        "matches": [],
    }