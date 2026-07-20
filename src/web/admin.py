"""
Admin API Module.

Superadmin-only endpoints for user management and audit log access.
All routes require the superadmin role.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from loguru import logger

from src.web.auth import UserInfo, require_superadmin
from src.web.users import get_user_store, VALID_ROLES
from src.web.audit import get_audit_logger
from src.web import runtime_config as rc
from src.core.config import get_config, ServerConfig, OLTConfig


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str


class PasswordRequest(BaseModel):
    password: str


class RoleRequest(BaseModel):
    role: str


class PatternRequest(BaseModel):
    pattern: str


class AddressesRequest(BaseModel):
    addresses: list[str]


class ScheduleRequest(BaseModel):
    time: str


router = APIRouter()


def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


# ==============================================================================
# USER MANAGEMENT
# ==============================================================================

@router.get("/users")
async def list_users(user: UserInfo = Depends(require_superadmin)):
    """List all users (without password hashes)."""
    return {"users": get_user_store().list_users(), "valid_roles": list(VALID_ROLES)}


@router.post("/users")
async def create_user(
    body: CreateUserRequest,
    request: Request,
    user: UserInfo = Depends(require_superadmin),
):
    """Create a new user."""
    store = get_user_store()
    try:
        created = store.add_user(body.username, body.password, body.role)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    get_audit_logger().log(
        action="user_add",
        username=user.username,
        role=user.role,
        target=body.username,
        detail=f"role={body.role}",
        success=True,
        ip=_client_ip(request),
    )
    logger.info(f"User {user.username} created user {body.username} ({body.role})")
    return {"success": True, "user": created}


@router.delete("/users/{username}")
async def delete_user(
    username: str,
    request: Request,
    user: UserInfo = Depends(require_superadmin),
):
    """Delete a user. Cannot delete yourself or the last superadmin."""
    store = get_user_store()

    if username == user.username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete your own account")

    if not store.exists(username):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User not found: {username}")

    if store.get_role(username) == "superadmin" and store.count_superadmins() <= 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete the last superadmin")

    try:
        store.delete_user(username)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    get_audit_logger().log(
        action="user_delete",
        username=user.username,
        role=user.role,
        target=username,
        success=True,
        ip=_client_ip(request),
    )
    logger.info(f"User {user.username} deleted user {username}")
    return {"success": True}


@router.put("/users/{username}/password")
async def change_password(
    username: str,
    body: PasswordRequest,
    request: Request,
    user: UserInfo = Depends(require_superadmin),
):
    """Change a user's password."""
    store = get_user_store()
    try:
        store.set_password(username, body.password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    get_audit_logger().log(
        action="user_password_change",
        username=user.username,
        role=user.role,
        target=username,
        success=True,
        ip=_client_ip(request),
    )
    logger.info(f"User {user.username} changed password for {username}")
    return {"success": True}


@router.put("/users/{username}/role")
async def change_role(
    username: str,
    body: RoleRequest,
    request: Request,
    user: UserInfo = Depends(require_superadmin),
):
    """Change a user's role. Cannot demote the last superadmin."""
    store = get_user_store()

    if not store.exists(username):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User not found: {username}")

    if (
        store.get_role(username) == "superadmin"
        and body.role != "superadmin"
        and store.count_superadmins() <= 1
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot demote the last superadmin")

    try:
        store.set_role(username, body.role)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    get_audit_logger().log(
        action="user_role_change",
        username=user.username,
        role=user.role,
        target=username,
        detail=f"role={body.role}",
        success=True,
        ip=_client_ip(request),
    )
    logger.info(f"User {user.username} changed role for {username} to {body.role}")
    return {"success": True}


# ==============================================================================
# AUDIT LOG
# ==============================================================================

@router.get("/audit")
async def get_audit(
    limit: int = 200,
    username: Optional[str] = None,
    action: Optional[str] = None,
    since: Optional[str] = None,
    user: UserInfo = Depends(require_superadmin),
):
    """Return recent audit entries (newest first), with optional filters."""
    limit = max(1, min(limit, 1000))
    entries = get_audit_logger().query(limit=limit, username=username, action=action, since=since)
    return {"entries": entries, "count": len(entries)}


# ==============================================================================
# SETTINGS: OUTAGE NOTIFICATIONS, WATER PATTERN, ELECTRIC ADDRESSES
# ==============================================================================

@router.get("/config/notifications/{channel}")
async def get_notifications(channel: str, user: UserInfo = Depends(require_superadmin)):
    """Get notification email settings for 'electric' or 'acc' (password masked)."""
    if channel not in ("electric", "acc"):
        raise HTTPException(status_code=400, detail="Invalid channel")
    cfg = dict(rc.get_notification_config(channel))
    cfg["smtp_password_set"] = bool(cfg.get("smtp_password"))
    cfg["smtp_password"] = ""
    return cfg


@router.put("/config/notifications/{channel}")
async def update_notifications(
    channel: str,
    body: dict,
    request: Request,
    user: UserInfo = Depends(require_superadmin),
):
    """Update notification email settings for a channel."""
    try:
        result = rc.set_notification_config(channel, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    get_audit_logger().log(
        action="settings_notifications",
        username=user.username, role=user.role,
        target=channel, detail=f"to={result.get('to')}",
        success=True, ip=_client_ip(request),
    )
    return {"success": True, "config": result}


@router.get("/config/acc-pattern")
async def get_acc_pattern_ep(user: UserInfo = Depends(require_superadmin)):
    """Get the water (ACC) address pattern."""
    return {"pattern": rc.get_acc_pattern()}


@router.put("/config/acc-pattern")
async def set_acc_pattern_ep(
    body: PatternRequest,
    request: Request,
    user: UserInfo = Depends(require_superadmin),
):
    """Set the water (ACC) address pattern."""
    try:
        pattern = rc.set_acc_pattern(body.pattern)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        from src.monitoring.acc_monitor import invalidate as _acc_invalidate
        _acc_invalidate()
    except Exception as e:
        logger.debug(f"ACC invalidate skipped: {e}")
    get_audit_logger().log(
        action="settings_acc_pattern",
        username=user.username, role=user.role,
        detail=pattern, success=True, ip=_client_ip(request),
    )
    return {"success": True, "pattern": pattern}


@router.get("/config/schedule/{channel}")
async def get_schedule_ep(channel: str, user: UserInfo = Depends(require_superadmin)):
    """Get the daily outage-check time for 'electric' or 'acc'."""
    if channel not in ("electric", "acc"):
        raise HTTPException(status_code=400, detail="Unknown channel")
    return {"time": rc.get_schedule_time(channel)}


@router.put("/config/schedule/{channel}")
async def set_schedule_ep(
    channel: str,
    body: ScheduleRequest,
    request: Request,
    user: UserInfo = Depends(require_superadmin),
):
    """Set the daily outage-check time (HH:MM) for 'electric' or 'acc'."""
    if channel not in ("electric", "acc"):
        raise HTTPException(status_code=400, detail="Unknown channel")
    try:
        new_time = rc.set_schedule_time(channel, body.time)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    get_audit_logger().log(
        action="settings_schedule",
        username=user.username, role=user.role,
        detail=f"{channel}={new_time}", success=True, ip=_client_ip(request),
    )
    return {"success": True, "time": new_time}


@router.get("/config/electric-addresses")
async def get_electric_addresses_ep(user: UserInfo = Depends(require_superadmin)):
    """Get the list of monitored electric addresses."""
    return {"addresses": rc.get_electric_addresses()}


@router.put("/config/electric-addresses")
async def set_electric_addresses_ep(
    body: AddressesRequest,
    request: Request,
    user: UserInfo = Depends(require_superadmin),
):
    """Replace the list of monitored electric addresses."""
    addresses = rc.set_electric_addresses(body.addresses)
    try:
        from src.monitoring.electric_monitor import invalidate as _electric_invalidate
        _electric_invalidate()
    except Exception as e:
        logger.debug(f"Electric invalidate skipped: {e}")
    get_audit_logger().log(
        action="settings_electric_addresses",
        username=user.username, role=user.role,
        detail=f"count={len(addresses)}", success=True, ip=_client_ip(request),
    )
    return {"success": True, "addresses": addresses}


# ==============================================================================
# SERVERS (monitored hosts) — add / edit / delete
# ==============================================================================
# Secret fields are masked on read and preserved on update if left blank.

_SERVER_SECRETS = ("auth_value", "sudo_password")
_OLT_SECRETS = ("ssh_password", "auth_pass", "priv_pass")


def _mask(d: dict, secret_fields) -> dict:
    out = dict(d)
    for f in secret_fields:
        val = out.get(f)
        out[f] = ""
        out[f + "_set"] = bool(val)
    return out


def _merge_secrets(incoming: dict, existing: dict, secret_fields) -> dict:
    merged = dict(incoming)
    for f in secret_fields:
        merged.pop(f + "_set", None)
        if not merged.get(f):
            merged[f] = existing.get(f) if existing else None
    return merged


@router.get("/config/servers")
async def list_servers(user: UserInfo = Depends(require_superadmin)):
    """List monitored servers (secret fields masked)."""
    servers = get_config().load_secrets().servers
    return {"servers": [_mask(s.model_dump(), _SERVER_SECRETS) for s in servers]}


@router.post("/config/servers")
async def create_server(body: dict, request: Request, user: UserInfo = Depends(require_superadmin)):
    """Add a monitored server. Takes effect after restart."""
    body.pop("auth_value_set", None)
    body.pop("sudo_password_set", None)
    try:
        validated = ServerConfig(**body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid server: {e}")
    try:
        rc.add_server(validated.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    get_config().reload()
    get_audit_logger().log(action="server_add", username=user.username, role=user.role,
                           target=validated.id, success=True, ip=_client_ip(request))
    return {"success": True, "restart_required": True}


@router.put("/config/servers/{server_id}")
async def edit_server(server_id: str, body: dict, request: Request, user: UserInfo = Depends(require_superadmin)):
    """Edit a monitored server. Blank secret fields keep their current value."""
    existing = next((s for s in rc.get_servers() if s.get("id") == server_id), None)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Server not found: {server_id}")
    merged = _merge_secrets(body, existing, _SERVER_SECRETS)
    merged["id"] = server_id
    try:
        validated = ServerConfig(**merged)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid server: {e}")
    rc.update_server(server_id, validated.model_dump())
    get_config().reload()
    get_audit_logger().log(action="server_edit", username=user.username, role=user.role,
                           target=server_id, success=True, ip=_client_ip(request))
    return {"success": True, "restart_required": True}


@router.delete("/config/servers/{server_id}")
async def remove_server(server_id: str, request: Request, user: UserInfo = Depends(require_superadmin)):
    """Delete a monitored server. Takes effect after restart."""
    try:
        rc.delete_server(server_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    get_config().reload()
    get_audit_logger().log(action="server_delete", username=user.username, role=user.role,
                           target=server_id, success=True, ip=_client_ip(request))
    return {"success": True, "restart_required": True}


# ==============================================================================
# OLTs (ONU monitoring) — add / edit / delete
# ==============================================================================

@router.get("/config/olts")
async def list_olts(user: UserInfo = Depends(require_superadmin)):
    """List OLTs (secret fields masked)."""
    onu = get_config().load_secrets().onu_monitoring
    olts = onu.olts if onu else []
    return {"olts": [_mask(o.model_dump(), _OLT_SECRETS) for o in olts]}


@router.post("/config/olts")
async def create_olt(body: dict, request: Request, user: UserInfo = Depends(require_superadmin)):
    """Add an OLT. Takes effect after restart."""
    for f in _OLT_SECRETS:
        body.pop(f + "_set", None)
    try:
        validated = OLTConfig(**body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid OLT: {e}")
    try:
        rc.add_olt(validated.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    get_config().reload()
    get_audit_logger().log(action="olt_add", username=user.username, role=user.role,
                           target=validated.id, success=True, ip=_client_ip(request))
    return {"success": True, "restart_required": True}


@router.put("/config/olts/{olt_id}")
async def edit_olt(olt_id: str, body: dict, request: Request, user: UserInfo = Depends(require_superadmin)):
    """Edit an OLT. Blank secret fields keep their current value."""
    existing = next((o for o in rc.get_olts() if o.get("id") == olt_id), None)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"OLT not found: {olt_id}")
    merged = _merge_secrets(body, existing, _OLT_SECRETS)
    merged["id"] = olt_id
    try:
        validated = OLTConfig(**merged)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid OLT: {e}")
    rc.update_olt(olt_id, validated.model_dump())
    get_config().reload()
    get_audit_logger().log(action="olt_edit", username=user.username, role=user.role,
                           target=olt_id, success=True, ip=_client_ip(request))
    return {"success": True, "restart_required": True}


@router.delete("/config/olts/{olt_id}")
async def remove_olt(olt_id: str, request: Request, user: UserInfo = Depends(require_superadmin)):
    """Delete an OLT. Takes effect after restart."""
    try:
        rc.delete_olt(olt_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    get_config().reload()
    get_audit_logger().log(action="olt_delete", username=user.username, role=user.role,
                           target=olt_id, success=True, ip=_client_ip(request))
    return {"success": True, "restart_required": True}


@router.post("/config/reload")
async def reload_config(request: Request, user: UserInfo = Depends(require_superadmin)):
    """Reload configuration from disk (does not restart background monitors)."""
    get_config().reload()
    get_audit_logger().log(action="config_reload", username=user.username, role=user.role,
                           success=True, ip=_client_ip(request))
    return {"success": True}
