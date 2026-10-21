"""Servers: status, details, service actions and diagnostics, app restart."""

import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger

from src.core.config import get_config
from src.core.ssh_manager import get_ssh_manager
from src.web.auth import get_current_user, require_admin, UserInfo
from src.web.routes.models import (
    ActionRequest, ActionResponse,
)
from src.services.dhcp import DHCPService
from src.services.dns import DNSService
from src.services.radius import RADIUSService

router = APIRouter()


_BRAND_DEFAULTS = {"name": "Network Operations", "sub": "AI Network Ops · MCP", "avatar": "NO"}


@router.get("/branding")
async def get_branding(user: UserInfo = Depends(get_current_user)):
    """Sidebar branding from .env (BRAND_NAME / BRAND_SUB / BRAND_AVATAR), read live."""
    from dotenv import dotenv_values
    from src.web.env_config import ENV_PATH

    env = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    return {
        key: env.get(f"BRAND_{key.upper()}") or os.getenv(f"BRAND_{key.upper()}") or default
        for key, default in _BRAND_DEFAULTS.items()
    }


async def build_server_status(server) -> dict:
    """Collect one server's status in full isolation.

    Any failure — unreachable host, connect timeout, bad service probe — is
    caught here and returned as ``connected=False`` plus an ``error`` string, so
    a single misconfigured or dead server can never raise out of here and take
    down the rest of the fleet's status. The SSH layer time-bounds the connect,
    so this can't hang either.
    """
    import asyncio
    ssh = get_ssh_manager()
    server_status = {
        "id": server.id,
        "host": server.host,
        "enabled": server.enabled,
        "connected": False,
        "services": [],
        "system_info": None,
    }

    try:
        connected, reason = await ssh.probe_connection(server.id)
        server_status["connected"] = connected
        if not connected and reason:
            server_status["error"] = reason

        if connected:
            system_info_task = ssh.get_system_info(server.id)
            service_tasks = [
                get_service_status(server.id, svc_type)
                for svc_type in server.services
            ]

            results = await asyncio.gather(
                system_info_task,
                *service_tasks,
                return_exceptions=True
            )

            if not isinstance(results[0], Exception):
                server_status["system_info"] = results[0]

            for i, svc_result in enumerate(results[1:]):
                if isinstance(svc_result, Exception):
                    server_status["services"].append({
                        "type": server.services[i],
                        "name": server.services[i],
                        "running": False,
                        "health": "error",
                        "error": str(svc_result)
                    })
                else:
                    server_status["services"].append(svc_result)

    except Exception as e:
        logger.error(f"Error getting status for {server.id}: {e}")
        server_status["error"] = str(e)

    return server_status


@router.get("/status")
async def get_overall_status(user: UserInfo = Depends(get_current_user)):
    import asyncio

    config = get_config()
    servers = config.get_enabled_servers()

    server_statuses = await asyncio.gather(
        *[build_server_status(server) for server in servers],
        return_exceptions=True
    )

    result_servers = []
    for i, server_status in enumerate(server_statuses):
        if isinstance(server_status, Exception):
            result_servers.append({
                "id": servers[i].id,
                "host": servers[i].host,
                "enabled": servers[i].enabled,
                "connected": False,
                "services": [],
                "error": str(server_status)
            })
        else:
            result_servers.append(server_status)

    return {
        "servers": result_servers,
        "timestamp": datetime.now().isoformat()
    }


@router.post("/servers/{server_id}/reconnect")
async def reconnect_server(
    server_id: str,
    user: UserInfo = Depends(get_current_user)
):
    """Drop the cached SSH connection for one server and re-probe it.

    Backs the dashboard's per-server retry button. It only touches this server,
    so the rest of the fleet is untouched, and it cannot hang the UI because the
    connect attempt is time-bounded in the SSH layer. Returns the same shape as
    one entry of ``/status`` so the client can refresh just that card.
    """
    config = get_config()
    server = config.get_server_by_id(server_id)
    if not server:
        raise HTTPException(status_code=404, detail=f"Server not found: {server_id}")

    ssh = get_ssh_manager()
    await ssh.disconnect(server_id)
    return await build_server_status(server)


@router.get("/settings/auto-check")
async def get_auto_check_setting(user: UserInfo = Depends(get_current_user)):
    """Dashboard auto connection-check setting (readable by any logged-in user)."""
    import src.web.runtime_config as rc
    return rc.get_auto_check()


@router.get("/servers")
async def list_servers(user: UserInfo = Depends(get_current_user)):
    config = get_config()
    secrets = config.load_secrets()

    servers = []
    for server in secrets.servers:
        servers.append({
            "id": server.id,
            "host": server.host,
            "port": server.port,
            "distro": server.distro,
            "services": server.services,
            "enabled": server.enabled
        })

    return {"servers": servers}


@router.get("/servers/{server_id}")
async def get_server_details(
    server_id: str,
    user: UserInfo = Depends(get_current_user)
):
    import asyncio

    config = get_config()
    server = config.get_server_by_id(server_id)

    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server not found: {server_id}"
        )

    ssh = get_ssh_manager()

    result = {
        "id": server.id,
        "host": server.host,
        "port": server.port,
        "distro": server.distro,
        "enabled": server.enabled,
        "connected": False,
        "services": [],
        "system_info": None
    }

    if not server.enabled:
        return result

    try:
        connected = await ssh.test_connection(server_id)
        result["connected"] = connected

        if connected:
            system_info_task = ssh.get_system_info(server_id)
            service_tasks = [
                get_service_status(server_id, svc_type)
                for svc_type in server.services
            ]

            results = await asyncio.gather(
                system_info_task,
                *service_tasks,
                return_exceptions=True
            )

            if not isinstance(results[0], Exception):
                result["system_info"] = results[0]

            for i, svc_result in enumerate(results[1:]):
                if isinstance(svc_result, Exception):
                    result["services"].append({
                        "type": server.services[i],
                        "name": server.services[i],
                        "running": False,
                        "health": "error",
                        "error": str(svc_result)
                    })
                else:
                    result["services"].append(svc_result)

    except Exception as e:
        logger.error(f"Error getting status for {server_id}: {e}")
        result["error"] = str(e)

    return result


async def get_service_status(server_id: str, service_type: str) -> dict:
    ssh = get_ssh_manager()

    service_handlers = {
        "dhcp": DHCPService,
        "dns": DNSService,
        "radius": RADIUSService,
    }

    handler_class = service_handlers.get(service_type)

    if handler_class:
        handler = handler_class(ssh, server_id)

        try:
            info = await handler.get_info()
            return {
                "name": info.service_name,
                "type": service_type,
                "running": info.state.value == "running",
                "health": info.health.value,
                "pid": info.pid,
                "config_file": info.config_file,
                "extra": info.extra_info
            }
        except Exception as e:
            logger.error(f"Error getting {service_type} status: {e}")
            return {
                "name": service_type,
                "type": service_type,
                "running": False,
                "health": "unknown",
                "error": str(e)
            }
    else:
        status = await ssh.check_service_status(server_id, service_type)
        return {
            "name": service_type,
            "type": service_type,
            "running": status.running,
            "enabled": status.enabled,
            "health": "unknown",
            "pid": status.pid
        }


@router.post("/servers/{server_id}/action", response_model=ActionResponse)
async def perform_action(
    server_id: str,
    request: ActionRequest,
    http_request: Request,
    user: UserInfo = Depends(require_admin)
):
    config = get_config()
    server = config.get_server_by_id(server_id)

    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server not found: {server_id}"
        )

    if not server.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Server is disabled: {server_id}"
        )

    ssh = get_ssh_manager()

    service_handlers = {
        "dhcp": DHCPService,
        "dns": DNSService,
        "radius": RADIUSService,
    }

    handler_class = service_handlers.get(request.service_type)

    if not handler_class:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown service type: {request.service_type}"
        )

    handler = handler_class(ssh, server_id)

    action_map = {
        "start": handler.start,
        "stop": handler.stop,
        "restart": handler.restart,
        "reload": handler.reload
    }

    action_fn = action_map.get(request.action)

    if not action_fn:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown action: {request.action}"
        )

    from src.web.audit import get_audit_logger
    client_ip = http_request.client.host if http_request.client else None
    target = f"{request.service_type}@{server_id}"

    try:
        logger.info(f"User {user.username} performing {request.action} on {target}")
        result = await action_fn()

        get_audit_logger().log(
            action="service_action",
            username=user.username,
            role=user.role,
            target=target,
            detail=request.action,
            success=result.success,
            ip=client_ip,
        )

        return ActionResponse(
            success=result.success,
            message=f"Action {request.action} completed",
            output=result.output if result.success else result.stderr
        )

    except Exception as e:
        logger.error(f"Action failed: {e}")
        get_audit_logger().log(
            action="service_action",
            username=user.username,
            role=user.role,
            target=target,
            detail=request.action,
            success=False,
            ip=client_ip,
        )
        return ActionResponse(
            success=False,
            message=f"Action failed: {str(e)}"
        )


@router.get("/servers/{server_id}/services/{service_type}/diagnostics/{diagnostic_name}")
async def run_diagnostic(
    server_id: str,
    service_type: str,
    diagnostic_name: str,
    user: UserInfo = Depends(get_current_user)
):
    config = get_config()
    server = config.get_server_by_id(server_id)

    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server not found: {server_id}"
        )

    ssh = get_ssh_manager()

    service_handlers = {
        "dhcp": DHCPService,
        "dns": DNSService,
        "radius": RADIUSService,
    }

    handler_class = service_handlers.get(service_type)

    if not handler_class:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown service type: {service_type}"
        )

    handler = handler_class(ssh, server_id)
    result = await handler.run_diagnostic(diagnostic_name)

    return {
        "name": result.name,
        "success": result.success,
        "output": result.output,
        "error": result.error
    }

@router.get("/servers/{server_id}/info")
async def get_server_full_info(
    server_id: str,
    user: UserInfo = Depends(get_current_user)
):
    config = get_config()
    server = config.get_server_by_id(server_id)

    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server not found: {server_id}"
        )

    ssh = get_ssh_manager()

    connected = await ssh.test_connection(server_id)
    if not connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Cannot connect to server: {server_id}"
        )

    from src.core.system_info import SystemInfoCollector, report_to_dict

    collector = SystemInfoCollector(ssh)
    report = await collector.collect(server_id)

    return report_to_dict(report)

@router.post("/service/restart")
async def restart_service(http_request: Request, user: UserInfo = Depends(get_current_user)):
    """Restart mcp-monitor service. Superadmin only."""
    if user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Superadmin access required")

    from src.web.audit import get_audit_logger
    client_ip = http_request.client.host if http_request.client else None
    try:
        import subprocess
        result = subprocess.run(
            ["sudo", "systemctl", "restart", "mcp-monitor"],
            capture_output=True,
            text=True,
            timeout=30
        )
        ok = result.returncode == 0
        get_audit_logger().log(
            action="app_restart",
            username=user.username,
            role=user.role,
            target="mcp-monitor",
            success=ok,
            ip=client_ip,
        )
        if ok:
            return {"success": True, "message": "Service restart initiated"}
        else:
            return {"success": False, "message": f"Error: {result.stderr}"}
    except Exception as e:
        logger.error(f"Service restart error: {e}")
        get_audit_logger().log(
            action="app_restart", username=user.username, role=user.role,
            target="mcp-monitor", success=False, ip=client_ip,
        )
        raise HTTPException(status_code=500, detail=str(e)) from e
