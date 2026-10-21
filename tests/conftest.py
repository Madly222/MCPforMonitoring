import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config import ClaudeConfig, MCPServerConfig, SecretsConfig, WebUserConfig  # noqa: E402


class FakeConfig:
    """Stands in for ConfigLoader so tests never read secrets.yaml."""

    def __init__(self, secrets: SecretsConfig):
        self._secrets = secrets

    def load_secrets(self):
        return self._secrets


@pytest.fixture
def web_env(tmp_path, monkeypatch):
    """Point the user store, session store and audit log at tmp_path.

    Seeds two users: alice (superadmin) and bob (operator), both with
    password "correct horse".
    """
    import src.web.audit as audit
    import src.web.auth as auth
    import src.web.users as users

    secrets = SecretsConfig(
        mcp_server=MCPServerConfig(login_max_attempts=3, login_lockout_minutes=15),
        claude=ClaudeConfig(api_key="test"),
        web_users=[
            WebUserConfig(username="alice", password="correct horse", role="superadmin"),
            WebUserConfig(username="bob", password="correct horse", role="operator"),
        ],
    )
    fake = FakeConfig(secrets)

    monkeypatch.setattr(users, "get_config", lambda: fake)
    monkeypatch.setattr(auth, "get_config", lambda: fake)
    monkeypatch.setattr(users, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(auth, "SESSIONS_FILE", tmp_path / "web_sessions.json")
    monkeypatch.setattr(audit, "AUDIT_FILE", tmp_path / "audit.jsonl")
    monkeypatch.setattr(users, "_user_store", None)
    monkeypatch.setattr(auth, "_session_store", None)
    monkeypatch.setattr(auth, "_login_throttle", None)
    monkeypatch.setattr(audit, "_audit_logger", None, raising=False)
    return secrets
