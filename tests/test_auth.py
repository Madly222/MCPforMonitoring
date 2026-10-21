"""Session store, login throttling and the auth/admin HTTP flow."""

from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.web.auth as auth
from src.web.users import MIN_PASSWORD_LENGTH, get_user_store


@pytest.fixture
def client(web_env):
    from src.web.admin import router as admin_router

    app = FastAPI()
    app.include_router(auth.router, prefix="/api/auth")
    app.include_router(admin_router, prefix="/api/admin")
    return TestClient(app)


def login(client, username="alice", password="correct horse"):
    return client.post("/api/auth/login", json={"username": username, "password": password})


# ------------------------------------------------------------------------------
# SessionStore
# ------------------------------------------------------------------------------

def test_sessions_survive_a_restart(web_env, tmp_path):
    sid = auth.SessionStore().create_session("alice", "superadmin")

    reloaded = auth.SessionStore()
    assert reloaded.get_session(sid)["username"] == "alice"


def test_session_file_holds_no_usable_token(web_env, tmp_path):
    sid = auth.SessionStore().create_session("alice", "superadmin")

    assert sid not in (tmp_path / "web_sessions.json").read_text(encoding="utf-8")


def test_expired_sessions_are_dropped(web_env):
    store = auth.SessionStore()
    sid = store.create_session("alice", "superadmin")
    store._sessions[auth._token_key(sid)]["expires_at"] = datetime.now() - timedelta(seconds=1)

    assert store.get_session(sid) is None
    assert auth.SessionStore().get_session(sid) is None


def test_delete_user_sessions_can_keep_the_callers_session(web_env):
    store = auth.SessionStore()
    keep = store.create_session("alice", "superadmin")
    other = store.create_session("alice", "superadmin")
    bob = store.create_session("bob", "operator")

    assert store.delete_user_sessions("alice", keep_session_id=keep) == 1
    assert store.get_session(keep) is not None
    assert store.get_session(other) is None
    assert store.get_session(bob) is not None


# ------------------------------------------------------------------------------
# LoginThrottle
# ------------------------------------------------------------------------------

def test_throttle_locks_after_max_attempts_and_resets():
    throttle = auth.LoginThrottle(max_attempts=2, lockout=timedelta(minutes=5))
    keys = ("user:bob", "ip:10.0.0.1")

    throttle.record_failure(*keys)
    assert throttle.retry_after(*keys) == 0
    throttle.record_failure(*keys)
    assert 0 < throttle.retry_after(*keys) <= 300

    throttle.reset(*keys)
    assert throttle.retry_after(*keys) == 0


def test_throttle_forgets_failures_older_than_the_window():
    throttle = auth.LoginThrottle(max_attempts=1, lockout=timedelta(minutes=5))
    throttle._failures["user:bob"] = [datetime.now() - timedelta(minutes=6)]

    assert throttle.retry_after("user:bob") == 0


# ------------------------------------------------------------------------------
# HTTP flow
# ------------------------------------------------------------------------------

def test_login_sets_httponly_cookie(client):
    resp = login(client)

    assert resp.status_code == 200
    cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "secure" not in cookie


def test_cookie_is_secure_when_configured(client, web_env):
    web_env.mcp_server.cookie_secure = True

    assert "secure" in login(client).headers["set-cookie"].lower()


def test_repeated_failures_lock_the_login(client):
    for _ in range(3):
        assert login(client, password="wrong password").status_code == 401

    resp = login(client)  # right password, but locked out
    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) > 0


def test_demotion_applies_to_an_existing_session(client):
    bob = TestClient(client.app)
    assert login(bob, "bob").status_code == 200
    get_user_store().set_role("bob", "admin")

    assert bob.get("/api/auth/me").json()["role"] == "admin"


def test_deleted_user_loses_access_at_once(client):
    bob = TestClient(client.app)
    login(bob, "bob")
    login(client)

    assert client.delete("/api/admin/users/bob").status_code == 200
    assert bob.get("/api/auth/me").status_code == 401


def test_admin_password_reset_ends_the_users_sessions(client):
    bob = TestClient(client.app)
    login(bob, "bob")
    login(client)

    resp = client.put("/api/admin/users/bob/password", json={"password": "a brand new pass"})
    assert resp.status_code == 200
    assert bob.get("/api/auth/me").status_code == 401


def test_own_password_change_keeps_only_the_current_session(client):
    other_device = TestClient(client.app)
    login(other_device)
    login(client)

    resp = client.post(
        "/api/auth/change-password",
        json={"current_password": "correct horse", "new_password": "a brand new pass"},
    )
    assert resp.status_code == 200
    assert client.get("/api/auth/me").status_code == 200
    assert other_device.get("/api/auth/me").status_code == 401


def test_short_passwords_are_rejected(client):
    login(client)
    short = "x" * (MIN_PASSWORD_LENGTH - 1)

    resp = client.post("/api/admin/users", json={"username": "carol", "password": short, "role": "operator"})
    assert resp.status_code == 400
    assert str(MIN_PASSWORD_LENGTH) in resp.json()["detail"]
