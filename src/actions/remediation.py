"""
Remediation of errors found in the logs.

Known errors (knowledge_base/known_errors.yaml) can carry fix commands. Each
command is checked against the risk policy (config/safe_actions.yaml) and,
depending on settings.yaml > auto_remediation.mode:

    off      nothing happens
    suggest  the plan is attached to the error for the dashboard; a human applies it
    auto     commands the policy allows run at once, within its cooldowns and
             limits; the rest stay as suggestions

Errors that match no pattern can be sent to Claude for a diagnosis. Claude's
commands are only ever shown, never run on their own.
"""

import asyncio
import re
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

from loguru import logger

from src.actions.policy import (
    ActionLimiter,
    ActionPolicy,
    Classification,
    get_action_policy,
)
from src.core.config import get_config

AUTO_USER = "auto-remediation"

_PLACEHOLDER = re.compile(r"\{(\w+)\}")

# Resolves a placeholder such as {service_name} for (server_id, service_type)
PlaceholderResolver = Callable[[str, str, str], Awaitable[Optional[str]]]


async def resolve_service_name(server_id: str, service_type: str, name: str) -> Optional[str]:
    """Fill {service_name} from the service handler's detection (dhcp, dns, radius)."""
    if name != "service_name":
        return None
    from src.core.ssh_manager import get_ssh_manager
    from src.services.dhcp import DHCPService
    from src.services.dns import DNSService
    from src.services.radius import RADIUSService

    handler_class = {"dhcp": DHCPService, "dns": DNSService, "radius": RADIUSService}.get(service_type)
    if handler_class is None:
        return None
    return await handler_class(get_ssh_manager(), server_id).get_service_name()


class Remediator:
    def __init__(
        self,
        policy: Optional[ActionPolicy] = None,
        ssh=None,
        audit=None,
        resolve_placeholder: PlaceholderResolver = resolve_service_name,
        mode: Optional[Callable[[], str]] = None,
    ):
        self.policy = policy or get_action_policy()
        self.limiter = ActionLimiter(self.policy)
        self._ssh = ssh
        self._audit = audit
        self._resolve_placeholder = resolve_placeholder
        self._mode = mode or (lambda: get_config().load_settings().auto_remediation.mode)

    @property
    def ssh(self):
        if self._ssh is None:
            from src.core.ssh_manager import get_ssh_manager
            self._ssh = get_ssh_manager()
        return self._ssh

    @property
    def audit(self):
        if self._audit is None:
            from src.web.audit import get_audit_logger
            self._audit = get_audit_logger()
        return self._audit

    # ------------------------------------------------------------------ plan

    async def plan(self, detected) -> list[dict[str, Any]]:
        """Fill placeholders in the pattern's fix commands and classify each one."""
        steps = []
        event = detected.event
        for template in detected.pattern.commands:
            command, missing = await self._fill(template, event.server_id, event.service_type)
            if missing:
                steps.append({
                    "command": template,
                    "risk": None,
                    "auto": False,
                    "reason": f"cannot fill {{{missing}}} on {event.server_id}",
                })
                continue
            c = self.policy.classify(command)
            allowed, why = self.policy.auto_allowed(c)
            steps.append({"command": command, **c.to_dict(), "auto": allowed, "reason": why})
        return steps

    async def _fill(self, template: str, server_id: str, service_type: str) -> tuple[str, Optional[str]]:
        command = template
        for name in set(_PLACEHOLDER.findall(template)):
            try:
                value = await self._resolve_placeholder(server_id, service_type, name)
            except Exception as e:
                logger.warning(f"Could not resolve {{{name}}} on {server_id}: {e}")
                value = None
            if not value:
                return template, name
            command = command.replace("{" + name + "}", value)
        return command, None

    # ------------------------------------------------------------------ handle

    async def handle(self, detected, detector) -> Optional[dict[str, Any]]:
        """Decide what to do about a known error; store and return the record."""
        pattern = detected.pattern
        if pattern is None or not pattern.commands:
            return None
        mode = self._mode()
        if mode == "off":
            return None

        steps = await self.plan(detected)
        record: dict[str, Any] = {"mode": mode, "steps": steps, "at": datetime.now().isoformat()}

        if mode == "suggest" or not pattern.auto_fix:
            record["status"] = "suggested"
            if mode == "auto":
                record["note"] = "auto_fix is false for this pattern"
            detected.remediation = record
            return record

        if not detector.can_auto_fix(detected):
            record["status"] = "suggested"
            record["note"] = "pattern cooldown is active"
            detected.remediation = record
            return record

        server_id = detected.event.server_id
        ran_any = False
        all_ok = True
        for step in steps:
            if not step["auto"]:
                step["result"] = "needs a human"
                all_ok = False
                continue
            c = self.policy.classify(step["command"])
            ok, why = self.limiter.check(server_id, c)
            if not ok:
                step["result"] = f"held back: {why}"
                all_ok = False
                continue
            success, output = await self._execute(server_id, c)
            self.limiter.record(server_id, c, success)
            ran_any = True
            step["result"] = "ok" if success else "failed"
            step["output"] = output[-2000:]
            all_ok = all_ok and success
            self.audit.log(
                action="auto_remediation",
                username=AUTO_USER,
                target=server_id,
                detail=f"{step['command']} (for: {pattern.diagnosis})",
                success=success,
            )
            if not success:
                break

        if ran_any:
            detector.mark_fix_attempted(detected)
        if ran_any and all_ok:
            record["status"] = "fixed"
            detector.mark_resolved(detected, f"auto-remediation: {', '.join(s['command'] for s in steps)}")
        elif ran_any:
            record["status"] = "failed"
        else:
            record["status"] = "suggested"
        detected.remediation = record
        logger.info(f"Remediation on {server_id} for '{pattern.diagnosis[:40]}': {record['status']}")
        return record

    async def apply(self, detected, detector, username: str, role: Optional[str], ip: Optional[str]) -> dict[str, Any]:
        """Run every fix command of a known error because a human asked to."""
        steps = await self.plan(detected)
        server_id = detected.event.server_id
        all_ok = True
        for step in steps:
            if step["risk"] is None:
                step["result"] = "skipped"
                all_ok = False
                continue
            c = self.policy.classify(step["command"])
            success, output = await self._execute(server_id, c)
            step["result"] = "ok" if success else "failed"
            step["output"] = output[-2000:]
            all_ok = all_ok and success
            self.audit.log(
                action="remediation_applied",
                username=username,
                role=role,
                target=server_id,
                detail=step["command"],
                success=success,
                ip=ip,
            )
            if not success:
                break
        record = {
            "mode": "manual",
            "status": "fixed" if all_ok else "failed",
            "steps": steps,
            "by": username,
            "at": datetime.now().isoformat(),
        }
        detector.mark_fix_attempted(detected)
        if all_ok:
            detector.mark_resolved(detected, f"applied by {username}")
        detected.remediation = record
        return record

    async def _execute(self, server_id: str, c: Classification) -> tuple[bool, str]:
        """Restarts and reloads go through the init-aware helpers; other commands run under sudo."""
        try:
            if c.action == "restart_service" and c.service:
                result = await self.ssh.restart_service(server_id, c.service)
            elif c.action == "reload_config" and c.service and not c.command.startswith("rndc"):
                result = await self.ssh.reload_service(server_id, c.service)
            else:
                result = await self.ssh.execute_sudo(server_id, c.command, timeout=60.0)
            return result.success, result.output
        except Exception as e:
            logger.error(f"Remediation command failed on {server_id}: {e}")
            return False, str(e)

    # ------------------------------------------------------------------ unknown errors

    async def analyze_unknown(self, detected) -> None:
        """Ask Claude about an error no pattern matched; store the diagnosis on it."""
        settings = get_config().load_settings().auto_remediation
        if not settings.analyze_unknown_errors:
            return
        try:
            secrets = get_config().load_secrets()
            if not secrets.claude.api_key:
                return
            server = next((s for s in secrets.servers if s.id == detected.event.server_id), None)
            from src.core.claude_client import get_claude_client

            result = await get_claude_client().analyze_error(
                [detected.event.line],
                {
                    "server_id": detected.event.server_id,
                    "distro": server.distro if server else None,
                    "services": server.services if server else [],
                },
            )
        except Exception as e:
            logger.warning(f"Claude analysis failed for {detected.error_hash}: {e}")
            return

        commands = []
        for command in result.fix_commands:
            c = self.policy.classify(command)
            commands.append({"command": command, **c.to_dict()})
        detected.analysis = {
            "source": "claude",
            "diagnosis": result.diagnosis,
            "severity": result.severity,
            "needs_human": result.needs_human,
            "reason": result.reason,
            "suggestions": result.suggestions,
            "fix_commands": commands,
            "at": datetime.now().isoformat(),
        }


_remediator: Optional[Remediator] = None
_background: set[asyncio.Task] = set()


def get_remediator() -> Remediator:
    global _remediator
    if _remediator is None:
        _remediator = Remediator()
    return _remediator


def spawn(coro) -> None:
    """Run a coroutine in the background without letting the task be garbage-collected."""
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_finished)


def _finished(task: asyncio.Task) -> None:
    _background.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.opt(exception=task.exception()).error("Background remediation task failed")
