"""/api/execute holds risky commands back until /api/execute/confirm."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.actions.pending as pending_mod
import src.core.command_resolver as resolver_mod
import src.web.api as api
import src.web.auth as auth
from src.core.command_resolver import ResolvedCommand


class FakeSSH:
    def __init__(self):
        self.calls = []

    async def execute(self, server_id, command, timeout=30.0):
        self.calls.append(("plain", server_id, command))
        return SimpleNamespace(success=True, output="out", stderr="")

    async def execute_sudo(self, server_id, command, timeout=30.0):
        self.calls.append(("sudo", server_id, command))
        return SimpleNamespace(success=True, output="out", stderr="")


@pytest.fixture
def env(web_env, monkeypatch):
    ssh = FakeSSH()
    state = {"resolved": None}

    class FakeResolver:
        async def resolve(self, text, servers, ssh, claude_fallback=None):
            return state["resolved"]

    server_cfg = SimpleNamespace(get_enabled_servers=lambda: [SimpleNamespace(id="dns1")])
    monkeypatch.setattr(api, "get_ssh_manager", lambda: ssh)
    monkeypatch.setattr(api, "get_config", lambda: server_cfg)
    monkeypatch.setattr(resolver_mod, "get_command_resolver", lambda: FakeResolver())
    monkeypatch.setattr(pending_mod, "_pending", None)

    app = FastAPI()
    app.include_router(auth.router, prefix="/api/auth")
    app.include_router(api.router, prefix="/api")

    def client_for(username):
        c = TestClient(app)
        assert c.post("/api/auth/login", json={"username": username, "password": "correct horse"}).status_code == 200
        return c

    def resolve_to(command, sudo=True, source="claude"):
        state["resolved"] = ResolvedCommand(command=command, sudo=sudo, source=source,
                                            intent=None, server_id="dns1", description="test")

    return SimpleNamespace(ssh=ssh, client_for=client_for, resolve_to=resolve_to)


def test_read_only_command_runs_at_once(env):
    env.resolve_to("journalctl -u named -n 20 --no-pager")
    resp = env.client_for("alice").post("/api/execute", json={"command": "named logs"}).json()

    assert resp["confirmation"] is None
    assert resp["success"] is True
    assert env.ssh.calls == [("sudo", "dns1", "journalctl -u named -n 20 --no-pager")]


def test_risky_command_waits_for_confirmation(env):
    env.resolve_to("systemctl stop named")
    alice = env.client_for("alice")

    resp = alice.post("/api/execute", json={"command": "stop dns"}).json()
    assert env.ssh.calls == []
    conf = resp["confirmation"]
    assert (conf["command"], conf["risk"], conf["action"]) == ("systemctl stop named", 2, "stop_service")

    done = alice.post("/api/execute/confirm", json={"confirmation_id": conf["id"]})
    assert done.status_code == 200
    assert env.ssh.calls == [("sudo", "dns1", "systemctl stop named")]

    again = alice.post("/api/execute/confirm", json={"confirmation_id": conf["id"]})
    assert again.status_code == 404


def test_only_the_requesting_user_can_confirm(env, web_env):
    from src.web.users import get_user_store

    get_user_store().set_role("bob", "admin")
    env.resolve_to("rm -rf /var/cache/bind")
    conf = env.client_for("alice").post("/api/execute", json={"command": "clean"}).json()["confirmation"]

    resp = env.client_for("bob").post("/api/execute/confirm", json={"confirmation_id": conf["id"]})
    assert resp.status_code == 404
    assert env.ssh.calls == []


def test_operators_cannot_execute(env):
    env.resolve_to("uptime")
    assert env.client_for("bob").post("/api/execute", json={"command": "uptime"}).status_code == 403
