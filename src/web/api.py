"""
REST API Endpoints.

Provides API for server monitoring and management.
"""

import os
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from loguru import logger

from src.core.config import get_config
from src.core.ssh_manager import get_ssh_manager
from src.web.auth import get_current_user, require_admin, UserInfo
from src.services.dhcp import DHCPService
from src.services.dns import DNSService
from src.services.radius import RADIUSService


class ServerStatus(BaseModel):
    id: str
    host: str
    enabled: bool
    connected: bool
    services: list[dict]
    system_info: Optional[dict] = None


class ServiceStatusModel(BaseModel):
    name: str
    type: str
    running: bool
    enabled: str
    health: str
    pid: Optional[int] = None
    extra: Optional[dict] = None


class CommandRequest(BaseModel):
    command: str


class CommandResponse(BaseModel):
    success: bool
    interpretation: Optional[str] = None
    commands_executed: Optional[list[dict]] = None
    result: Optional[str] = None
    error: Optional[str] = None
    source: str = "local"
    # Set when the command was not run because the risk policy wants a human to confirm it
    confirmation: Optional[dict] = None


class ConfirmRequest(BaseModel):
    confirmation_id: str


class ActionRequest(BaseModel):
    server_id: str
    service_type: str
    action: str


class ActionResponse(BaseModel):
    success: bool
    message: str
    output: Optional[str] = None


class ConsoleRequest(BaseModel):
    server_id: str
    command: str
    sudo: bool = False


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


@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }


# ==============================================================================
# ACC WATER MONITORING ENDPOINTS
# ==============================================================================

@router.get("/acc/status")
async def get_acc_status():
    """Get ACC.md water disconnection status."""
    try:
        from src.monitoring.acc_monitor import get_status_dict, check_acc_status
        import asyncio
        asyncio.create_task(check_acc_status())
        return get_status_dict()
    except ImportError:
        return {"ok": True, "last_check": None, "matches_count": 0, "matches": [], "error": "ACC module not installed"}
    except Exception as e:
        logger.error(f"ACC status error: {e}")
        return {"ok": True, "last_check": None, "matches_count": 0, "matches": [], "error": str(e)}


@router.post("/acc/check")
async def check_acc_now(user: UserInfo = Depends(get_current_user)):
    """Force check ACC.md now."""
    try:
        from src.monitoring.acc_monitor import check_acc_status, get_status_dict
        await check_acc_status(force=True)
        return get_status_dict()
    except Exception as e:
        logger.error(f"ACC check error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ==============================================================================
# ELECTRIC MONITORING ENDPOINTS
# ==============================================================================

@router.get("/electric/status")
async def get_electric_status():
    """Get Premier Energy disconnection status."""
    try:
        from src.monitoring.electric_monitor import get_status_dict, check_electric_status
        import asyncio
        asyncio.create_task(check_electric_status())
        return get_status_dict()
    except ImportError:
        return {"ok": True, "last_check": None, "matches_count": 0, "matches": [], "error": "Electric module not installed"}
    except Exception as e:
        logger.error(f"Electric status error: {e}")
        return {"ok": True, "last_check": None, "matches_count": 0, "matches": [], "error": str(e)}


@router.post("/electric/check")
async def check_electric_now(user: UserInfo = Depends(get_current_user)):
    """Force check Premier Energy now."""
    try:
        from src.monitoring.electric_monitor import check_electric_status, get_status_dict
        await check_electric_status(force=True)
        return get_status_dict()
    except Exception as e:
        logger.error(f"Electric check error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ==============================================================================
# ONU MONITORING ENDPOINTS
# ==============================================================================
@router.get("/onu/status")
async def get_onu_status(user: UserInfo = Depends(get_current_user)):
    """Get all ONU status from all OLTs."""
    from src.monitoring.onu_monitor import get_onu_monitor

    monitor = get_onu_monitor()
    onus = monitor.get_cached_onus()
    stats = monitor.get_stats()

    config = get_config()
    onu_config = config.get_onu_monitoring_config()
    thresholds = onu_config.thresholds if onu_config else None

    return {
        "timestamp": datetime.now().isoformat(),
        "stats": stats,
        "thresholds": {
            "good": thresholds.good if thresholds else -20,
            "warning": thresholds.warning if thresholds else -25
        },
        "onus": [
            {
                "olt_id": o.olt_id,
                "onu_id": o.onu_id,
                "port": o.port,
                "status": o.status.value,
                "registration": o.registration.value,
                "rx_power": o.rx_power,
                "tx_power": o.tx_power,
                "rx_power_avg": getattr(o, 'rx_power_avg', None),
                "tx_power_avg": getattr(o, 'tx_power_avg', None),
                "description": o.description,
                "onu_type": getattr(o, 'onu_type', ''),
                "serial_number": getattr(o, 'serial_number', ''),
                "mac_address": getattr(o, 'mac_address', ''),
                "last_offline": getattr(o, 'last_offline', None),
                "offline_reason": getattr(o, 'offline_reason', None),
                "updated_at": o.updated_at.isoformat()
            }
            for o in onus
        ]
    }


@router.get("/onu/olts")
async def get_olts(user: UserInfo = Depends(get_current_user)):
    """Get configured OLTs."""
    config = get_config()
    olts = config.get_enabled_olts()

    return {
        "olts": [
            {
                "id": olt.id,
                "host": olt.host,
                "vendor": olt.vendor,
                "enabled": olt.enabled
            }
            for olt in olts
        ]
    }


@router.get("/onu/olt/{olt_id}")
async def get_olt_onus(
    olt_id: str,
    user: UserInfo = Depends(get_current_user)
):
    """Get ONU status for specific OLT."""
    from src.monitoring.onu_monitor import get_onu_monitor

    config = get_config()
    olt = config.get_olt_by_id(olt_id)

    if not olt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OLT not found: {olt_id}"
        )

    monitor = get_onu_monitor()
    onus = monitor.get_cached_onus(olt_id)
    last_poll = monitor.get_last_poll_time(olt_id)

    return {
        "olt_id": olt_id,
        "host": olt.host,
        "vendor": olt.vendor,
        "last_poll": last_poll.isoformat() if last_poll else None,
        "onus": [
            {
                "onu_id": o.onu_id,
                "port": o.port,
                "status": o.status.value,
                "registration": o.registration.value,
                "rx_power": o.rx_power,
                "tx_power": o.tx_power,
                "description": o.description,
                "offline_reason": o.offline_reason.value if o.offline_reason else None,
            }
            for o in onus
        ]
    }


@router.post("/onu/olt/{olt_id}/poll")
async def poll_olt(
    olt_id: str,
    user: UserInfo = Depends(require_admin)
):
    """Force poll specific OLT."""
    from src.monitoring.onu_monitor import get_onu_monitor

    config = get_config()
    olt = config.get_olt_by_id(olt_id)

    if not olt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OLT not found: {olt_id}"
        )

    monitor = get_onu_monitor()
    onus = await monitor.poll_olt(olt)

    return {
        "success": True,
        "message": f"Polled {len(onus)} ONUs from {olt_id}",
        "count": len(onus)
    }


# ==============================================================================
# COMMAND EXECUTION
# ==============================================================================

async def _run_resolved_command(ssh, server_id: str, command: str, sudo: bool,
                                interpretation: Optional[str], source: str) -> CommandResponse:
    if sudo:
        exec_result = await ssh.execute_sudo(server_id, command)
    else:
        wrapped = (
            "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:"
            "/usr/bin:/sbin:/bin:$PATH; " + command
        )
        exec_result = await ssh.execute(server_id, wrapped)

    return CommandResponse(
        success=exec_result.success,
        interpretation=interpretation,
        commands_executed=[{"command": command, "output": exec_result.output}],
        result=exec_result.output,
        error=exec_result.stderr if not exec_result.success else None,
        source=source,
    )


@router.post("/execute/confirm", response_model=CommandResponse)
async def confirm_command(
    request: ConfirmRequest,
    http_request: Request,
    user: UserInfo = Depends(require_admin)
):
    """Run a command that /execute held back for confirmation."""
    from src.actions.pending import get_pending_commands
    from src.web.audit import get_audit_logger

    pending = get_pending_commands().take(request.confirmation_id, user.username)
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nothing to confirm: the request expired, was already run, or belongs to another user",
        )

    get_audit_logger().log(
        action="command_confirmed",
        username=user.username,
        role=user.role,
        target=pending.server_id,
        detail=f"{pending.command} (risk {pending.classification.risk})",
        ip=http_request.client.host if http_request.client else None,
    )
    logger.info(f"User {user.username} confirmed on {pending.server_id}: {pending.command}")
    return await _run_resolved_command(
        get_ssh_manager(), pending.server_id, pending.command, pending.sudo,
        pending.description, pending.source,
    )


@router.post("/execute", response_model=CommandResponse)
async def execute_command(
    request: CommandRequest,
    http_request: Request,
    user: UserInfo = Depends(require_admin)
):
    command = request.command.strip()

    logger.info(f"User {user.username} executing command: {command}")

    from src.web.audit import get_audit_logger
    get_audit_logger().log(
        action="command",
        username=user.username,
        role=user.role,
        detail=command,
        ip=http_request.client.host if http_request.client else None,
    )

    config = get_config()
    ssh = get_ssh_manager()

    servers = config.get_enabled_servers()
    server_ids = [s.id for s in servers]

    # Stage 0: capability-aware resolver. Simple intents (status/logs/errors/
    # restart) render to a profile-correct command with zero Claude tokens;
    # unknown requests fall back to Claude and get cached per server.
    try:
        from src.core.command_resolver import get_command_resolver, LIFECYCLE

        resolver = get_command_resolver()

        async def _claude_fallback(req: str, profile):
            from src.core.claude_client import get_claude_client
            return await get_claude_client().resolve_shell_command(req, profile)

        resolved = await resolver.resolve(
            command, servers, ssh, claude_fallback=_claude_fallback,
        )

        # Managed-service lifecycle keeps using the validated handler path below.
        managed_lifecycle = (
            resolved is not None
            and resolved.intent in LIFECYCLE
            and resolved.service in ("dhcp", "dns", "radius")
        )

        if resolved and not managed_lifecycle:
            from src.actions.policy import get_action_policy
            from src.actions.pending import get_pending_commands

            policy = get_action_policy()
            classification = policy.classify(resolved.command)
            allowed, why = policy.auto_allowed(classification)
            if not allowed:
                pending = get_pending_commands().add(
                    username=user.username,
                    server_id=resolved.server_id,
                    command=resolved.command,
                    sudo=resolved.sudo,
                    classification=classification,
                    description=resolved.description or resolved.intent or "",
                    source=resolved.source,
                )
                get_audit_logger().log(
                    action="command_needs_confirmation",
                    username=user.username,
                    role=user.role,
                    target=resolved.server_id,
                    detail=f"{resolved.command} (risk {classification.risk}: {why})",
                    ip=http_request.client.host if http_request.client else None,
                )
                return CommandResponse(
                    success=False,
                    interpretation=resolved.description or resolved.intent,
                    result=f"Not run yet: {why}. Confirm to run it on {resolved.server_id}.",
                    source=resolved.source,
                    confirmation={**pending.to_dict(), "why": why},
                )

            return await _run_resolved_command(
                ssh, resolved.server_id, resolved.command, resolved.sudo,
                resolved.description or resolved.intent, resolved.source,
            )
    except Exception as e:
        logger.warning(f"Command resolver stage failed: {e}, continuing to interpreter")

    try:
        from src.core.claude_client import get_claude_client

        claude = get_claude_client()
        interpretation = await claude.interpret_command(command, server_ids)

        if interpretation.confidence > 0.7:
            result = await execute_interpreted_command(interpretation, ssh, config)
            result.source = "claude"
            return result

    except Exception as e:
        logger.warning(f"Claude interpretation failed: {e}, falling back to basic parsing")

    command_lower = command.lower()

    if "status" in command_lower:
        target_server = None
        for s in servers:
            if s.id.lower() in command_lower:
                target_server = s.id
                break

        if target_server:
            try:
                info = await ssh.get_system_info(target_server)
                return CommandResponse(
                    success=True,
                    interpretation=f"Checking status of {target_server}",
                    result=f"{target_server}: connected, load={info.get('load', 'unknown')}, memory={info.get('memory', 'unknown')}"
                )
            except Exception as e:
                return CommandResponse(
                    success=False,
                    interpretation=f"Checking status of {target_server}",
                    error=str(e)
                )
        else:
            results = []
            for server in servers:
                try:
                    connected = await ssh.test_connection(server.id)
                    if connected:
                        info = await ssh.get_system_info(server.id)
                        results.append(f"{server.id}: connected, load={info.get('load', 'unknown')}")
                    else:
                        results.append(f"{server.id}: disconnected")
                except Exception as e:
                    results.append(f"{server.id}: error - {e}")

            return CommandResponse(
                success=True,
                interpretation="Checking status of all servers",
                result="\n".join(results)
            )

    elif "restart" in command_lower:
        service_type = None
        target_server = None

        service_keywords = {
            "dhcp": "dhcp",
            "dns": "dns",
            "postfix": "postfix",
            "mail": "postfix",
            "dovecot": "dovecot",
            "apache": "apache",
            "web": "apache",
            "spam": "spamfilter"
        }

        for keyword, svc_type in service_keywords.items():
            if keyword in command_lower:
                service_type = svc_type
                break

        for s in servers:
            if s.id.lower() in command_lower:
                target_server = s.id
                break

        if not target_server and service_type:
            for s in servers:
                if service_type in s.services:
                    target_server = s.id
                    break

        if target_server and service_type:
            service_handlers = {
                "dhcp": DHCPService,
                "dns": DNSService,
                "radius": RADIUSService,
            }

            handler_class = service_handlers.get(service_type)

            if handler_class:
                handler = handler_class(ssh, target_server)
                result = await handler.restart()

                return CommandResponse(
                    success=result.success,
                    interpretation=f"Restarting {service_type} on {target_server}",
                    commands_executed=[{"command": f"restart {service_type}", "output": result.output}],
                    result=f"{service_type} restarted successfully" if result.success else f"Failed to restart {service_type}",
                    error=result.stderr if not result.success else None
                )
            else:
                result = await ssh.restart_service(target_server, service_type)
                return CommandResponse(
                    success=result.success,
                    interpretation=f"Restarting {service_type} on {target_server}",
                    commands_executed=[{"command": f"restart {service_type}", "output": result.output}],
                    result="Service restart attempted",
                    error=result.stderr if not result.success else None
                )
        else:
            return CommandResponse(
                success=False,
                interpretation="Restart command",
                error="Could not determine service or server. Try: 'restart dhcp on dhcp-primary'"
            )

    elif "logs" in command_lower or "errors" in command_lower:
        from src.monitoring.error_detector import get_error_detector

        detector = get_error_detector()
        errors = detector.get_recent_errors(60)

        if errors:
            error_lines = []
            for e in errors[:10]:
                error_lines.append(f"[{e.event.server_id}] {e.event.line[:80]}")

            return CommandResponse(
                success=True,
                interpretation="Showing recent errors",
                result=f"Found {len(errors)} errors in last hour:\n" + "\n".join(error_lines)
            )
        else:
            return CommandResponse(
                success=True,
                interpretation="Showing recent errors",
                result="No errors detected in the last hour"
            )

    elif "health" in command_lower or "check" in command_lower:
        from src.monitoring.health_checker import get_health_checker

        checker = get_health_checker()
        reports = checker.get_all_reports()

        if reports:
            lines = []
            for r in reports:
                lines.append(f"{r.server_id}: {r.check_result.value}")
                for s in r.services:
                    lines.append(f"  - {s.get('name', 'unknown')}: {s.get('health', 'unknown')}")

            return CommandResponse(
                success=True,
                interpretation="Health check status",
                result="\n".join(lines)
            )
        else:
            return CommandResponse(
                success=True,
                interpretation="Health check status",
                result="No health reports available yet"
            )

    else:
        return CommandResponse(
            success=False,
            interpretation="Command not recognized",
            error="Unknown command. Try: 'status', 'restart dhcp', 'show errors', 'health check'"
        )


async def execute_interpreted_command(
    interpretation,
    ssh,
    config
) -> CommandResponse:
    intent = interpretation.intent
    server_id = interpretation.server_id
    service_type = interpretation.service_type

    if intent == "check_status":
        if server_id:
            try:
                info = await ssh.get_system_info(server_id)
                return CommandResponse(
                    success=True,
                    interpretation=f"Checking status of {server_id}",
                    result=f"{server_id}: connected\nHostname: {info.get('hostname')}\nLoad: {info.get('load')}\nMemory: {info.get('memory')}\nDisk: {info.get('disk')}"
                )
            except Exception as e:
                return CommandResponse(
                    success=False,
                    interpretation=f"Checking status of {server_id}",
                    error=str(e)
                )
        else:
            servers = config.get_enabled_servers()
            results = []
            for server in servers:
                try:
                    info = await ssh.get_system_info(server.id)
                    results.append(f"{server.id}: load={info.get('load', 'N/A')}")
                except Exception as e:
                    results.append(f"{server.id}: error ({e})")

            return CommandResponse(
                success=True,
                interpretation="Checking status of all servers",
                result="\n".join(results)
            )

    elif intent == "restart_service":
        if not server_id:
            for s in config.get_enabled_servers():
                if service_type in s.services:
                    server_id = s.id
                    break

        if server_id and service_type:
            service_handlers = {"dhcp": DHCPService, "dns": DNSService, "radius": RADIUSService}
            handler_class = service_handlers.get(service_type)

            if handler_class:
                handler = handler_class(ssh, server_id)
                result = await handler.restart()
            else:
                result = await ssh.restart_service(server_id, service_type)

            return CommandResponse(
                success=result.success,
                interpretation=f"Restarting {service_type} on {server_id}",
                commands_executed=[{"command": f"restart {service_type}", "output": result.output}],
                result="Service restarted" if result.success else "Restart failed",
                error=result.stderr if not result.success else None
            )
        else:
            return CommandResponse(
                success=False,
                interpretation="Restart service",
                error="Could not determine server or service"
            )

    elif intent == "get_logs":
        from src.monitoring.error_detector import get_error_detector

        if server_id:
            service_handlers = {"dhcp": DHCPService, "dns": DNSService, "radius": RADIUSService}

            server = config.get_server_by_id(server_id)
            if server and server.services:
                svc_type = service_type or server.services[0]
                handler_class = service_handlers.get(svc_type)

                if handler_class:
                    handler = handler_class(ssh, server_id)
                    logs = await handler.get_recent_logs(30)

                    return CommandResponse(
                        success=True,
                        interpretation=f"Recent logs from {server_id}",
                        result=logs
                    )

        detector = get_error_detector()
        errors = detector.get_recent_errors(60)

        if errors:
            lines = [f"[{e.event.server_id}] {e.event.line[:100]}" for e in errors[:10]]
            return CommandResponse(
                success=True,
                interpretation="Recent errors from all servers",
                result="\n".join(lines)
            )
        else:
            return CommandResponse(
                success=True,
                interpretation="Getting recent logs/errors",
                result="No recent errors detected. All servers healthy."
            )

    elif intent == "run_diagnostic":
        if not server_id:
            for s in config.get_enabled_servers():
                if service_type and service_type in s.services:
                    server_id = s.id
                    break
            if not server_id:
                servers = config.get_enabled_servers()
                if servers:
                    server_id = servers[0].id

        if server_id:
            server = config.get_server_by_id(server_id)
            service_handlers = {"dhcp": DHCPService, "dns": DNSService, "radius": RADIUSService}

            svc_type = service_type
            if not svc_type and server and server.services:
                svc_type = server.services[0]

            results = []

            if svc_type:
                handler_class = service_handlers.get(svc_type)
                if handler_class:
                    handler = handler_class(ssh, server_id)

                    health_checks = await handler.check_health()
                    results.append(f"=== {svc_type.upper()} Health Checks on {server_id} ===")
                    for check in health_checks:
                        status = "PASS" if check.passed else "FAIL"
                        results.append(f"[{status}] {check.name}: {check.message}")

                    try:
                        extra = await handler.get_extra_info()
                        results.append("\n=== Additional Info ===")
                        for key, value in extra.items():
                            results.append(f"{key}: {value}")
                    except Exception as e:
                        logger.debug(f"get_extra_info failed: {e}")
                else:
                    status = await ssh.check_service_status(server_id, svc_type)
                    results.append(f"Service: {svc_type}")
                    results.append(f"Running: {status.running}")
                    results.append(f"PID: {status.pid}")
            else:
                results.append(f"=== Server {server_id} Health ===")
                system_info = await ssh.get_system_info(server_id)
                results.append(f"Hostname: {system_info.get('hostname', 'N/A')}")
                results.append(f"Load: {system_info.get('load', 'N/A')}")
                results.append(f"Memory: {system_info.get('memory', 'N/A')}")
                results.append(f"Disk: {system_info.get('disk', 'N/A')}")

                if server and server.services:
                    results.append("\n=== Services ===")
                    for svc in server.services:
                        handler_class = service_handlers.get(svc)
                        if handler_class:
                            handler = handler_class(ssh, server_id)
                            try:
                                info = await handler.get_info()
                                results.append(f"{svc}: {info.state.value} ({info.health.value})")
                            except Exception as e:
                                results.append(f"{svc}: error - {e}")
                        else:
                            status = await ssh.check_service_status(server_id, svc)
                            results.append(f"{svc}: {'running' if status.running else 'stopped'}")

            return CommandResponse(
                success=True,
                interpretation=f"Running diagnostics on {server_id}" + (f" ({svc_type})" if svc_type else ""),
                result="\n".join(results)
            )
        else:
            return CommandResponse(
                success=False,
                interpretation="Run diagnostic",
                error="No servers available"
            )

    elif intent == "show_config":
        if not server_id:
            for s in config.get_enabled_servers():
                if service_type and service_type in s.services:
                    server_id = s.id
                    break

        if server_id and service_type:
            service_handlers = {"dhcp": DHCPService, "dns": DNSService, "radius": RADIUSService}
            handler_class = service_handlers.get(service_type)

            if handler_class:
                handler = handler_class(ssh, server_id)
                result = await handler.run_diagnostic("get_config")

                return CommandResponse(
                    success=result.success,
                    interpretation=f"Configuration of {service_type} on {server_id}",
                    result=result.output[:2000] if result.output else "No config found",
                    error=result.error
                )

        return CommandResponse(
            success=False,
            interpretation="Show config",
            error="Could not determine server or service"
        )

    else:
        return CommandResponse(
            success=False,
            interpretation=f"Intent: {intent}",
            error="Command not fully implemented yet"
        )


# ==============================================================================
# MONITORING ENDPOINTS
# ==============================================================================

@router.get("/monitoring/status")
async def get_monitoring_status(user: UserInfo = Depends(get_current_user)):
    from src.monitoring.log_watcher import get_log_watcher
    from src.monitoring.health_checker import get_health_checker
    from src.monitoring.error_detector import get_error_detector

    watcher = get_log_watcher()
    checker = get_health_checker()
    detector = get_error_detector()

    result = {
        "log_watcher": {
            "running": watcher.is_running,
            "watched_files": watcher.watched_files
        },
        "health_checker": {
            "running": checker.is_running
        },
        "error_detector": {
            "stats": detector.get_error_stats()
        }
    }

    try:
        from src.monitoring.onu_monitor import get_onu_monitor
        onu_monitor = get_onu_monitor()
        result["onu_monitor"] = {
            "running": onu_monitor.is_running,
            "stats": onu_monitor.get_stats()
        }
    except Exception as e:
        logger.debug(f"ONU monitor status unavailable: {e}")

    return result


@router.get("/monitoring/errors")
async def get_recent_errors(
    minutes: int = 60,
    user: UserInfo = Depends(get_current_user)
):
    from src.monitoring.error_detector import get_error_detector

    detector = get_error_detector()
    errors = detector.get_recent_errors(minutes)

    return {
        "mode": get_config().load_settings().auto_remediation.mode,
        "count": len(errors),
        "errors": [
            {
                "server_id": e.event.server_id,
                "service_type": e.event.service_type,
                "log_file": e.event.log_file,
                "line": e.event.line[:200],
                "event_type": e.event.event_type.value,
                "error_hash": e.error_hash,
                "first_seen": e.first_seen.isoformat(),
                "last_seen": e.last_seen.isoformat(),
                "count": e.count,
                "resolved": e.resolved,
                "resolution": e.resolution,
                "pattern": {
                    "diagnosis": e.pattern.diagnosis,
                    "severity": e.pattern.severity,
                    "auto_fix": e.pattern.auto_fix,
                    "suggestions": e.pattern.suggestions,
                } if e.pattern else None,
                "remediation": e.remediation,
                "analysis": e.analysis,
            }
            for e in errors
        ]
    }


@router.post("/monitoring/errors/{error_hash}/fix")
async def apply_error_fix(
    error_hash: str,
    http_request: Request,
    user: UserInfo = Depends(require_admin)
):
    """Run the fix commands of a known error, after the operator confirmed them in the UI."""
    from src.actions.remediation import get_remediator
    from src.monitoring.error_detector import get_error_detector

    detector = get_error_detector()
    detected = detector.get_error(error_hash)
    if detected is None:
        raise HTTPException(status_code=404, detail="Error not found (it may have aged out)")
    if detected.pattern is None or not detected.pattern.commands:
        raise HTTPException(status_code=400, detail="This error has no fix commands")

    ip = http_request.client.host if http_request.client else None
    return await get_remediator().apply(detected, detector, user.username, user.role, ip)


@router.get("/monitoring/health")
async def get_health_reports(user: UserInfo = Depends(get_current_user)):
    from src.monitoring.health_checker import get_health_checker

    checker = get_health_checker()
    reports = checker.get_all_reports()

    return {
        "count": len(reports),
        "reports": [
            {
                "server_id": r.server_id,
                "host": r.host,
                "reachable": r.reachable,
                "check_result": r.check_result.value,
                "services": r.services,
                "system_info": r.system_info,
                "checked_at": r.checked_at.isoformat(),
                "error": r.error
            }
            for r in reports
        ]
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


# ==============================================================================
# SERVICE RESTART (admin only)
# ==============================================================================
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


# ==============================================================================
# SSH CONSOLE — raw command execution on a target server
# ==============================================================================

@router.post("/console/exec")
async def console_exec(
    request: ConsoleRequest,
    http_request: Request,
    user: UserInfo = Depends(require_admin)
):
    """
    Execute a raw shell command on a target server over SSH and return its
    output, as if connected via SSH. Admin/superadmin only; every command is
    audited.
    """
    ssh = get_ssh_manager()
    command = request.command.strip()
    server_id = request.server_id

    from src.web.audit import get_audit_logger
    client_ip = http_request.client.host if http_request.client else None
    get_audit_logger().log(
        action="console_exec",
        username=user.username,
        role=user.role,
        target=server_id,
        detail=("sudo " if request.sudo else "") + command,
        ip=client_ip,
    )

    from src.web import runtime_config as rc
    cmd_timeout = float(rc.get_command_timeout())

    try:
        if request.sudo:
            result = await ssh.execute_sudo(server_id, command, timeout=cmd_timeout)
        else:
            # Non-login SSH shells often have a minimal PATH, so binaries like
            # systemctl/ss/ip are "not found". Prepend a sane PATH.
            wrapped = (
                "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH; "
                + command
            )
            result = await ssh.execute(server_id, wrapped, timeout=cmd_timeout)
        return {
            "success": result.success,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_ms": result.duration_ms,
        }
    except Exception as e:
        logger.error(f"Console exec error on {server_id}: {e}")
        return {"success": False, "exit_code": -1, "stdout": "", "stderr": str(e)}


# ==============================================================================
# CLAUDE HEALTH — verify the API key/model are working
# ==============================================================================

@router.get("/claude/health")
async def claude_health(user: UserInfo = Depends(get_current_user)):
    """Make a minimal Claude API call to verify the key and model are alive."""
    from src.core.claude_client import get_claude_client
    model = None
    try:
        secrets = get_config().load_secrets()
        model = secrets.claude.model
        if not secrets.claude.api_key:
            return {"ok": False, "model": model, "error": "No API key configured"}
        # Looking the model up checks the key and the model id without generating tokens
        await get_claude_client().client.models.retrieve(model)
        return {"ok": True, "model": model}
    except Exception as e:
        return {"ok": False, "model": model, "error": str(e)}
