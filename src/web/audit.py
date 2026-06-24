"""
Audit Logging Module.

Records security-relevant actions (logins, commands, service actions, user
management) to an append-only JSONL file. Readable only by superadmins via the
admin API.
"""

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from src.core.config import PROJECT_ROOT

AUDIT_FILE = PROJECT_ROOT / "logs" / "audit.jsonl"


class AuditLogger:
    """Append-only audit log backed by a JSONL file."""

    def __init__(self):
        self._lock = threading.Lock()
        AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        action: str,
        username: str,
        role: Optional[str] = None,
        target: Optional[str] = None,
        detail: Optional[str] = None,
        success: Optional[bool] = None,
        ip: Optional[str] = None,
    ) -> None:
        """Append a single audit entry."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "username": username,
            "role": role,
            "action": action,
            "target": target,
            "detail": detail,
            "success": success,
            "ip": ip,
        }
        try:
            with self._lock:
                with open(AUDIT_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to write audit entry: {e}")

    def query(
        self,
        limit: int = 200,
        username: Optional[str] = None,
        action: Optional[str] = None,
        since: Optional[str] = None,
    ) -> list[dict]:
        """
        Return the most recent audit entries, newest first.

        Optional filters: username (exact), action (substring), since (ISO date).
        """
        if not AUDIT_FILE.exists():
            return []

        entries: list[dict] = []
        try:
            with open(AUDIT_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if username and entry.get("username") != username:
                        continue
                    if action and action not in (entry.get("action") or ""):
                        continue
                    if since and (entry.get("timestamp") or "") < since:
                        continue
                    entries.append(entry)
        except Exception as e:
            logger.error(f"Failed to read audit log: {e}")
            return []

        entries.reverse()
        return entries[:limit]


_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get the singleton audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
