"""Every API route has a deliberate access level.

ROLES lists each route with the least privileged role that may call it. A new
route that is missing here fails the test, so its access level gets decided
instead of defaulting to whatever the handler happened to declare.
"""

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from src.web.admin import router as admin_router
from src.web.api import router as api_router
from src.web.api_netbox import router as netbox_router
from src.web.auth import router as auth_router

PUBLIC, USER, ADMIN, SUPERADMIN = "public", "user", "admin", "superadmin"
DEPENDENCY_ROLE = {"get_current_user": USER, "require_admin": ADMIN, "require_superadmin": SUPERADMIN}

ROLES = {
    # liveness and the login flow itself
    ("GET", "/api/health"): PUBLIC,
    ("POST", "/api/auth/login"): PUBLIC,
    ("POST", "/api/auth/logout"): PUBLIC,
    ("GET", "/api/auth/check"): PUBLIC,
    ("GET", "/api/auth/me"): USER,
    ("POST", "/api/auth/change-password"): USER,
    # reading state: any logged-in user, operators included
    ("GET", "/api/branding"): USER,
    ("GET", "/api/status"): USER,
    ("GET", "/api/servers"): USER,
    ("GET", "/api/servers/{server_id}"): USER,
    ("GET", "/api/servers/{server_id}/info"): USER,
    ("GET", "/api/servers/{server_id}/services/{service_type}/diagnostics/{diagnostic_name}"): USER,
    ("POST", "/api/servers/{server_id}/reconnect"): USER,
    ("GET", "/api/settings/auto-check"): USER,
    ("GET", "/api/acc/status"): USER,
    ("POST", "/api/acc/check"): USER,
    ("GET", "/api/electric/status"): USER,
    ("POST", "/api/electric/check"): USER,
    ("GET", "/api/onu/status"): USER,
    ("GET", "/api/onu/olts"): USER,
    ("GET", "/api/onu/olt/{olt_id}"): USER,
    ("GET", "/api/monitoring/status"): USER,
    ("GET", "/api/monitoring/errors"): USER,
    ("GET", "/api/monitoring/health"): USER,
    ("GET", "/api/claude/health"): USER,
    ("GET", "/api/netbox/health"): USER,
    ("POST", "/api/netbox/scan"): USER,
    ("POST", "/api/netbox/scan-router"): USER,
    # changing something on a server, an OLT or NetBox
    ("POST", "/api/servers/{server_id}/action"): ADMIN,
    ("POST", "/api/onu/olt/{olt_id}/poll"): ADMIN,
    ("POST", "/api/execute"): ADMIN,
    ("POST", "/api/execute/confirm"): ADMIN,
    ("POST", "/api/console/exec"): ADMIN,
    ("POST", "/api/monitoring/errors/{error_hash}/fix"): ADMIN,
    ("POST", "/api/netbox/apply"): ADMIN,
    ("POST", "/api/netbox/auto"): ADMIN,
    ("POST", "/api/netbox/apply-router"): ADMIN,
    ("POST", "/api/netbox/sync-mac"): ADMIN,
    ("POST", "/api/netbox/sync-interfaces"): ADMIN,
    # the app itself
    ("POST", "/api/service/restart"): SUPERADMIN,
}
ADMIN_CONSOLE_PREFIX = "/api/admin/"  # every route there is superadmin-only


def build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/auth")
    app.include_router(api_router, prefix="/api")
    app.include_router(netbox_router, prefix="/api/netbox")
    app.include_router(admin_router, prefix="/api/admin")
    return app


def route_table():
    for route in build_app().routes:
        if not isinstance(route, APIRoute):
            continue
        names = {d.call.__name__ for d in route.dependant.dependencies}
        roles = [DEPENDENCY_ROLE[n] for n in names if n in DEPENDENCY_ROLE]
        actual = max(roles, key=[PUBLIC, USER, ADMIN, SUPERADMIN].index) if roles else PUBLIC
        for method in route.methods:
            yield method, route.path, actual


def test_every_route_has_the_expected_role():
    seen = set()
    for method, path, actual in route_table():
        key = (method, path)
        if path.startswith(ADMIN_CONSOLE_PREFIX):
            assert actual == SUPERADMIN, f"{method} {path} must be superadmin-only, is {actual}"
            continue
        assert key in ROLES, f"{method} {path} is not in ROLES: decide who may call it"
        assert actual == ROLES[key], f"{method} {path} requires {actual}, expected {ROLES[key]}"
        seen.add(key)
    assert set(ROLES) - seen == set(), "ROLES lists routes that no longer exist"


# A few real requests, so the table above is backed by the actual dependencies

@pytest.fixture
def client(web_env):
    return TestClient(build_app())


def login(client, username):
    assert client.post("/api/auth/login", json={"username": username, "password": "correct horse"}).status_code == 200


@pytest.mark.parametrize("method, path", [
    ("GET", "/api/status"),
    ("GET", "/api/electric/status"),
    ("GET", "/api/acc/status"),
    ("POST", "/api/execute"),
    ("GET", "/api/admin/users"),
])
def test_anonymous_requests_are_rejected(client, method, path):
    assert client.request(method, path, json={}).status_code == 401


@pytest.mark.parametrize("method, path", [
    ("POST", "/api/execute"),
    ("POST", "/api/console/exec"),
    ("POST", "/api/netbox/sync-mac"),
    ("POST", "/api/netbox/apply"),
    ("POST", "/api/service/restart"),
    ("GET", "/api/admin/users"),
])
def test_operators_cannot_change_anything(client, method, path):
    login(client, "bob")
    assert client.request(method, path, json={}).status_code == 403
