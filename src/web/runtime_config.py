"""
Runtime Configuration Store.

Writable settings that the superadmin can edit at runtime via the web UI,
backed by a JSON file. The outage monitors read these values live (each run)
with fallback to environment variables / defaults, so edits take effect without
a restart.

Covers:
- Notification email settings (electric + acc channels)
- ACC (water) address pattern
- Electric address list (stored in config/electric_addresses.txt)
"""

import json
import os
import re
import threading
from pathlib import Path
from typing import Optional

from loguru import logger

from src.core.config import PROJECT_ROOT, CONFIG_DIR

RUNTIME_FILE = PROJECT_ROOT / "sessions" / "runtime_settings.json"
ELECTRIC_ADDRESSES_FILE = CONFIG_DIR / "electric_addresses.txt"

_lock = threading.Lock()
_cache: Optional[dict] = None


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    if RUNTIME_FILE.exists():
        try:
            with open(RUNTIME_FILE, "r", encoding="utf-8") as f:
                _cache = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load runtime settings: {e}")
            _cache = {}
    else:
        _cache = {}
    return _cache


def _save(data: dict) -> None:
    global _cache
    RUNTIME_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = RUNTIME_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(RUNTIME_FILE)
    _cache = data


# ==============================================================================
# NOTIFICATION EMAIL SETTINGS
# ==============================================================================
# Defaults mirror the original behaviour in electric_monitor / acc_monitor.

def _env(*keys: str, default: str = "") -> str:
    for k in keys:
        v = os.getenv(k)
        if v is not None and v != "":
            return v
    return default


def _default_notification(channel: str) -> dict:
    if channel == "electric":
        return {
            "enabled": _env("ELECTRIC_EMAIL_ENABLED", default="true").lower() == "true",
            "smtp_server": _env("ELECTRIC_SMTP_SERVER", "ACC_SMTP_SERVER", default="mail.rapidlink.md"),
            "smtp_port": int(_env("ELECTRIC_SMTP_PORT", "ACC_SMTP_PORT", default="25")),
            "smtp_user": _env("ELECTRIC_SMTP_USER", "ACC_SMTP_USER", default=""),
            "smtp_password": _env("ELECTRIC_SMTP_PASSWORD", "ACC_SMTP_PASSWORD", default=""),
            "smtp_tls": _env("ELECTRIC_SMTP_TLS", "ACC_SMTP_TLS", default="false").lower() == "true",
            "from": _env("ELECTRIC_EMAIL_FROM", "ACC_EMAIL_FROM", default="control@rapidlink.md"),
            "to": _env("ELECTRIC_EMAIL_TO", "ACC_EMAIL_TO", default="admin@rapidlink.md"),
        }
    return {
        "enabled": _env("ACC_EMAIL_ENABLED", default="true").lower() == "true",
        "smtp_server": _env("ACC_SMTP_SERVER", default="mail.rapidlink.md"),
        "smtp_port": int(_env("ACC_SMTP_PORT", default="25")),
        "smtp_user": _env("ACC_SMTP_USER", default=""),
        "smtp_password": _env("ACC_SMTP_PASSWORD", default=""),
        "smtp_tls": _env("ACC_SMTP_TLS", default="false").lower() == "true",
        "from": _env("ACC_EMAIL_FROM", default="control@rapidlink.md"),
        "to": _env("ACC_EMAIL_TO", default="admin@rapidlink.md"),
    }


def get_notification_config(channel: str) -> dict:
    """Return effective notification config for 'electric' or 'acc' (live)."""
    cfg = _default_notification(channel)
    stored = _load().get("notifications", {}).get(channel, {})
    cfg.update({k: v for k, v in stored.items() if v is not None})
    return cfg


def set_notification_config(channel: str, values: dict) -> dict:
    """Persist notification config for a channel. Returns the effective config."""
    if channel not in ("electric", "acc"):
        raise ValueError(f"Invalid channel: {channel}")
    allowed = {"enabled", "smtp_server", "smtp_port", "smtp_user", "smtp_password", "smtp_tls", "from", "to"}
    clean = {}
    for k, v in values.items():
        if k not in allowed:
            continue
        if k == "smtp_port":
            clean[k] = int(v)
        elif k in ("enabled", "smtp_tls"):
            clean[k] = bool(v)
        elif k == "smtp_password":
            if v != "":
                clean[k] = str(v)
        else:
            clean[k] = str(v).strip()
    with _lock:
        data = _load()
        data.setdefault("notifications", {}).setdefault(channel, {}).update(clean)
        _save(data)
    return get_notification_config(channel)


def get_notification_recipients(channel: str) -> list[str]:
    """Return the 'to' list for a channel, split and trimmed."""
    raw = get_notification_config(channel).get("to", "")
    return [a.strip() for a in str(raw).split(",") if a.strip()]


# ==============================================================================
# ACC (WATER) ADDRESS PATTERN
# ==============================================================================

def get_acc_pattern() -> str:
    """Return the effective ACC address pattern (live)."""
    stored = _load().get("acc_pattern")
    if stored:
        return stored
    return _env("ACC_ADDRESS_PATTERN", default=r"Asachi\s*,?\s*71")


def set_acc_pattern(pattern: str) -> str:
    """Persist the ACC address pattern."""
    pattern = (pattern or "").strip()
    if not pattern:
        raise ValueError("Pattern is required")
    try:
        re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Invalid regex pattern: {e}")
    with _lock:
        data = _load()
        data["acc_pattern"] = pattern
        _save(data)
    return pattern


# ==============================================================================
# ELECTRIC ADDRESS LIST  (config/electric_addresses.txt)
# ==============================================================================

def get_electric_addresses() -> list[str]:
    """Return the list of monitored electric addresses (without comments)."""
    addresses: list[str] = []
    if not ELECTRIC_ADDRESSES_FILE.exists():
        return addresses
    try:
        with open(ELECTRIC_ADDRESSES_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    addresses.append(line)
    except Exception as e:
        logger.error(f"Failed to read electric addresses: {e}")
    return addresses


def set_electric_addresses(addresses: list[str]) -> list[str]:
    """Overwrite the electric address list, preserving a header comment."""
    clean = []
    seen = set()
    for a in addresses:
        a = (a or "").strip()
        if a and not a.startswith("#") and a not in seen:
            clean.append(a)
            seen.add(a)
    header = (
        "# Addresses monitored for electricity outages (Chisinau)\n"
        "# Format: Street HouseNumber  |  one per line\n"
        "# Managed via the web admin panel.\n\n"
    )
    with _lock:
        ELECTRIC_ADDRESSES_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = ELECTRIC_ADDRESSES_FILE.with_suffix(".txt.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(header)
            f.write("\n".join(clean) + "\n")
        tmp.replace(ELECTRIC_ADDRESSES_FILE)
    return clean


def reload_cache() -> None:
    """Invalidate the in-memory cache (forces re-read from disk)."""
    global _cache
    _cache = None


# ==============================================================================
# DASHBOARD AUTO CONNECTION-CHECK
# ==============================================================================
# Controls the dashboard's automatic re-probing of server connections.

_DEFAULT_AUTOCHECK_INTERVAL = 30
_MIN_AUTOCHECK_INTERVAL = 5


def get_auto_check() -> dict:
    """Return the dashboard auto-check setting: {enabled, interval_seconds}."""
    stored = _load().get("auto_check", {}) or {}
    enabled = stored.get("enabled", True)
    interval = stored.get("interval_seconds", _DEFAULT_AUTOCHECK_INTERVAL)
    try:
        interval = int(interval)
    except (TypeError, ValueError):
        interval = _DEFAULT_AUTOCHECK_INTERVAL
    if interval < _MIN_AUTOCHECK_INTERVAL:
        interval = _MIN_AUTOCHECK_INTERVAL
    return {"enabled": bool(enabled), "interval_seconds": interval}


def set_auto_check(enabled: bool, interval_seconds) -> dict:
    """Persist the auto-check setting. Returns the normalized value."""
    try:
        interval = int(interval_seconds)
    except (TypeError, ValueError):
        raise ValueError("interval_seconds must be an integer")
    if interval < _MIN_AUTOCHECK_INTERVAL:
        raise ValueError(f"interval_seconds must be >= {_MIN_AUTOCHECK_INTERVAL}")
    with _lock:
        data = _load()
        data["auto_check"] = {"enabled": bool(enabled), "interval_seconds": interval}
        _save(data)
    return get_auto_check()


# ==============================================================================
# SSH CONNECT TIMEOUT
# ==============================================================================
# How long to wait for an SSH connection (TCP + handshake + auth) before giving
# up on a server. Read live on every connection attempt, so changes apply
# without a restart. Raise it for hosts with a slow sshd handshake (e.g. one
# doing reverse-DNS/GSSAPI lookups); the real fix is on the server, but this
# keeps such hosts monitorable meanwhile.

_DEFAULT_SSH_TIMEOUT = 8
_MIN_SSH_TIMEOUT = 3
_MAX_SSH_TIMEOUT = 120


def get_ssh_timeout() -> int:
    """Return the SSH connect timeout in seconds."""
    stored = _load().get("ssh_connect_timeout", _DEFAULT_SSH_TIMEOUT)
    try:
        value = int(stored)
    except (TypeError, ValueError):
        return _DEFAULT_SSH_TIMEOUT
    if value < _MIN_SSH_TIMEOUT or value > _MAX_SSH_TIMEOUT:
        return _DEFAULT_SSH_TIMEOUT
    return value


def set_ssh_timeout(seconds) -> int:
    """Persist the SSH connect timeout. Returns the normalized value."""
    try:
        value = int(seconds)
    except (TypeError, ValueError):
        raise ValueError("Timeout must be an integer number of seconds")
    if value < _MIN_SSH_TIMEOUT or value > _MAX_SSH_TIMEOUT:
        raise ValueError(
            f"Timeout must be between {_MIN_SSH_TIMEOUT} and {_MAX_SSH_TIMEOUT} seconds"
        )
    with _lock:
        data = _load()
        data["ssh_connect_timeout"] = value
        _save(data)
    return value


# ==============================================================================
# SERVERS STORE  (seed-and-own, like the user store)
# ==============================================================================
# Seeded once from secrets.yaml on first config load, then this store is the
# source of truth for the monitored-server list. Edits apply after an app
# restart (the SSH pool and monitors initialise at startup).

def servers_seeded() -> bool:
    return "servers" in _load()


def seed_servers(defaults: list[dict]) -> None:
    if servers_seeded():
        return
    with _lock:
        data = _load()
        data["servers"] = defaults
        _save(data)
    logger.info(f"Server store seeded: {len(defaults)} servers")


def get_servers() -> list[dict]:
    return list(_load().get("servers", []))


def _save_servers(servers: list[dict]) -> None:
    with _lock:
        data = _load()
        data["servers"] = servers
        _save(data)


def add_server(server: dict) -> None:
    servers = get_servers()
    if any(s.get("id") == server.get("id") for s in servers):
        raise ValueError(f"Server already exists: {server.get('id')}")
    servers.append(server)
    _save_servers(servers)


def update_server(server_id: str, server: dict) -> None:
    servers = get_servers()
    for i, s in enumerate(servers):
        if s.get("id") == server_id:
            servers[i] = server
            _save_servers(servers)
            return
    raise ValueError(f"Server not found: {server_id}")


def delete_server(server_id: str) -> None:
    servers = get_servers()
    new = [s for s in servers if s.get("id") != server_id]
    if len(new) == len(servers):
        raise ValueError(f"Server not found: {server_id}")
    _save_servers(new)


# ==============================================================================
# OLT (ONU) STORE
# ==============================================================================

def olts_seeded() -> bool:
    return "olts" in _load()


def seed_olts(defaults: list[dict]) -> None:
    if olts_seeded():
        return
    with _lock:
        data = _load()
        data["olts"] = defaults
        _save(data)
    logger.info(f"OLT store seeded: {len(defaults)} OLTs")


def get_olts() -> list[dict]:
    return list(_load().get("olts", []))


def _save_olts(olts: list[dict]) -> None:
    with _lock:
        data = _load()
        data["olts"] = olts
        _save(data)


def add_olt(olt: dict) -> None:
    olts = get_olts()
    if any(o.get("id") == olt.get("id") for o in olts):
        raise ValueError(f"OLT already exists: {olt.get('id')}")
    olts.append(olt)
    _save_olts(olts)


def update_olt(olt_id: str, olt: dict) -> None:
    olts = get_olts()
    for i, o in enumerate(olts):
        if o.get("id") == olt_id:
            olts[i] = olt
            _save_olts(olts)
            return
    raise ValueError(f"OLT not found: {olt_id}")


def delete_olt(olt_id: str) -> None:
    olts = get_olts()
    new = [o for o in olts if o.get("id") != olt_id]
    if len(new) == len(olts):
        raise ValueError(f"OLT not found: {olt_id}")
    _save_olts(new)


# ==============================================================================
# OUTAGE CHECK SCHEDULE  (daily time the electric/water checks run, HH:MM)
# ==============================================================================

_DEFAULT_SCHEDULE = "08:00"
_TIME_RE = re.compile(r'^([01]?\d|2[0-3]):([0-5]\d)$')


def get_schedule_time(channel: str) -> str:
    """Return the daily check time 'HH:MM' for a channel ('electric' | 'acc')."""
    stored = _load().get("schedules", {}).get(channel)
    if stored and _TIME_RE.match(stored):
        return stored
    env_key = {"electric": "ELECTRIC_CHECK_TIME", "acc": "ACC_CHECK_TIME"}.get(channel, "")
    if env_key:
        ev = _env(env_key, default="")
        if _TIME_RE.match(ev):
            return ev
    return _DEFAULT_SCHEDULE


def set_schedule_time(channel: str, value: str) -> str:
    """Persist the daily check time for a channel. Returns the normalized value."""
    value = (value or "").strip()
    m = _TIME_RE.match(value)
    if not m:
        raise ValueError("Time must be HH:MM (00:00–23:59)")
    value = f"{int(m.group(1)):02d}:{m.group(2)}"
    with _lock:
        data = _load()
        data.setdefault("schedules", {})[channel] = value
        _save(data)
    return value
