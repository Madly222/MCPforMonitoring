"""
User Store Module.

Runtime-writable user store backed by a JSON file. Seeded once from
secrets.yaml (web_users) on first run, after which it becomes the source of
truth for authentication and user management.

Roles: superadmin > admin > operator.
"""

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import bcrypt
from loguru import logger

from src.core.config import get_config, PROJECT_ROOT

VALID_ROLES = ("operator", "admin", "superadmin")

USERS_FILE = PROJECT_ROOT / "sessions" / "users.json"


def _hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _looks_hashed(value: str) -> bool:
    """Return True if the value is already a bcrypt hash."""
    return value.startswith("$2b$") or value.startswith("$2a$") or value.startswith("$2y$")


class UserStore:
    """JSON-backed user store with runtime management."""

    def __init__(self):
        self._lock = threading.Lock()
        self._users: dict[str, dict] = {}
        self._load_or_seed()

    def _load_or_seed(self) -> None:
        """Load users from disk, or seed from secrets.yaml on first run."""
        USERS_FILE.parent.mkdir(parents=True, exist_ok=True)

        if USERS_FILE.exists():
            try:
                with open(USERS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for entry in data.get("users", []):
                    self._users[entry["username"]] = entry
                logger.info(f"User store loaded: {len(self._users)} users")
                return
            except Exception as e:
                logger.error(f"Failed to load user store: {e}")

        self._seed_from_secrets()

    def reseed_from_secrets(self) -> int:
        """Discard the user store and re-seed from secrets.yaml web_users.

        Destructive: web-created users are removed and passwords reset to whatever
        secrets.yaml holds. Used by the 'Reload from secrets.yaml' action.
        """
        with self._lock:
            try:
                if USERS_FILE.exists():
                    USERS_FILE.unlink()
            except Exception as e:
                logger.error(f"Could not remove user store: {e}")
            self._users = {}
            self._seed_from_secrets()
            return len(self._users)

    def _seed_from_secrets(self) -> None:
        """Populate the store from secrets.yaml web_users (first run only)."""
        try:
            secrets = get_config().load_secrets()
        except Exception as e:
            logger.error(f"Cannot seed user store from secrets: {e}")
            return

        now = datetime.now().isoformat()
        for user in secrets.web_users:
            role = user.role if user.role in VALID_ROLES else "operator"
            password = user.password if _looks_hashed(user.password) else _hash_password(user.password)
            self._users[user.username] = {
                "username": user.username,
                "password": password,
                "role": role,
                "created_at": now,
                "updated_at": now,
            }

        self._save()
        logger.info(f"User store seeded from secrets.yaml: {len(self._users)} users")

    def _save(self) -> None:
        """Persist the store to disk atomically."""
        USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = USERS_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"users": list(self._users.values())}, f, indent=2, ensure_ascii=False)
        tmp.replace(USERS_FILE)

    def verify(self, username: str, password: str) -> Optional[dict]:
        """Return {username, role} if credentials are valid, else None."""
        user = self._users.get(username)
        if not user:
            return None
        try:
            if bcrypt.checkpw(password.encode("utf-8"), user["password"].encode("utf-8")):
                return {"username": user["username"], "role": user["role"]}
        except Exception as e:
            logger.error(f"Password verification error: {e}")
        return None

    def list_users(self) -> list[dict]:
        """Return all users without password hashes."""
        return [
            {
                "username": u["username"],
                "role": u["role"],
                "created_at": u.get("created_at"),
                "updated_at": u.get("updated_at"),
            }
            for u in self._users.values()
        ]

    def exists(self, username: str) -> bool:
        return username in self._users

    def get_role(self, username: str) -> Optional[str]:
        user = self._users.get(username)
        return user["role"] if user else None

    def add_user(self, username: str, password: str, role: str) -> dict:
        """Add a new user. Raises ValueError on conflict or invalid input."""
        username = username.strip()
        if not username:
            raise ValueError("Username is required")
        if role not in VALID_ROLES:
            raise ValueError(f"Invalid role: {role}")
        if not password:
            raise ValueError("Password is required")
        with self._lock:
            if username in self._users:
                raise ValueError(f"User already exists: {username}")
            now = datetime.now().isoformat()
            self._users[username] = {
                "username": username,
                "password": _hash_password(password),
                "role": role,
                "created_at": now,
                "updated_at": now,
            }
            self._save()
        return {"username": username, "role": role}

    def delete_user(self, username: str) -> None:
        """Delete a user. Raises ValueError if not found."""
        with self._lock:
            if username not in self._users:
                raise ValueError(f"User not found: {username}")
            del self._users[username]
            self._save()

    def set_password(self, username: str, password: str) -> None:
        """Change a user's password. Raises ValueError on invalid input."""
        if not password:
            raise ValueError("Password is required")
        with self._lock:
            if username not in self._users:
                raise ValueError(f"User not found: {username}")
            self._users[username]["password"] = _hash_password(password)
            self._users[username]["updated_at"] = datetime.now().isoformat()
            self._save()

    def set_role(self, username: str, role: str) -> None:
        """Change a user's role. Raises ValueError on invalid input."""
        if role not in VALID_ROLES:
            raise ValueError(f"Invalid role: {role}")
        with self._lock:
            if username not in self._users:
                raise ValueError(f"User not found: {username}")
            self._users[username]["role"] = role
            self._users[username]["updated_at"] = datetime.now().isoformat()
            self._save()

    def count_superadmins(self) -> int:
        return sum(1 for u in self._users.values() if u["role"] == "superadmin")


_user_store: Optional[UserStore] = None


def get_user_store() -> UserStore:
    """Get the singleton user store instance."""
    global _user_store
    if _user_store is None:
        _user_store = UserStore()
    return _user_store
