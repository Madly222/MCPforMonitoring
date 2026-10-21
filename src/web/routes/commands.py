"""Commands: natural-language /execute with confirmation, and the raw SSH console."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger

from src.core.config import get_config
from src.core.ssh_manager import get_ssh_manager
from src.web.auth import require_admin, UserInfo
from src.web.routes.models import (
    CommandRequest, CommandResponse, ConfirmRequest,
    ConsoleRequest,
)
from src.services.dhcp import DHCPService
from src.services.dns import DNSService
from src.services.radius import RADIUSService

router = APIRouter()


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
