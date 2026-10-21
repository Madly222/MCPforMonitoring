"""
Commands waiting for an operator to confirm them.

/api/execute parks a command here when the risk policy does not let it run on
its own; /api/execute/confirm runs it once the same user confirms within the TTL.
"""

import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from src.actions.policy import Classification

CONFIRMATION_TTL = timedelta(minutes=5)


@dataclass
class PendingCommand:
    id: str
    username: str
    server_id: str
    command: str
    sudo: bool
    classification: Classification
    description: str = ""
    source: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "server_id": self.server_id,
            "command": self.command,
            "sudo": self.sudo,
            "description": self.description,
            "expires_in_seconds": int(CONFIRMATION_TTL.total_seconds()),
            **self.classification.to_dict(),
        }


class PendingCommands:
    def __init__(self, ttl: timedelta = CONFIRMATION_TTL):
        self.ttl = ttl
        self._lock = threading.Lock()
        self._items: dict[str, PendingCommand] = {}

    def add(self, username: str, server_id: str, command: str, sudo: bool,
            classification: Classification, description: str = "", source: str = "") -> PendingCommand:
        item = PendingCommand(
            id=secrets.token_urlsafe(16),
            username=username,
            server_id=server_id,
            command=command,
            sudo=sudo,
            classification=classification,
            description=description,
            source=source,
        )
        with self._lock:
            self._prune()
            self._items[item.id] = item
        return item

    def take(self, confirmation_id: str, username: str) -> Optional[PendingCommand]:
        """Remove and return the command if it exists, is fresh and belongs to the user."""
        with self._lock:
            self._prune()
            item = self._items.get(confirmation_id)
            if item is None or item.username != username:
                return None
            del self._items[confirmation_id]
            return item

    def _prune(self) -> None:
        cutoff = datetime.now() - self.ttl
        for key in [k for k, v in self._items.items() if v.created_at < cutoff]:
            del self._items[key]


_pending: Optional[PendingCommands] = None


def get_pending_commands() -> PendingCommands:
    global _pending
    if _pending is None:
        _pending = PendingCommands()
    return _pending
