"""Remediator: what each auto_remediation mode does with a known error."""

import asyncio
from types import SimpleNamespace

import pytest

from src.actions.policy import ActionPolicy
from src.actions.remediation import Remediator
from src.monitoring.error_detector import DetectedError, ErrorPattern
from src.monitoring.log_watcher import LogEvent, LogEventType


class FakeSSH:
    def __init__(self, success=True):
        self.success = success
        self.calls = []

    def _result(self):
        return SimpleNamespace(success=self.success, output="done" if self.success else "boom")

    async def restart_service(self, server_id, service):
        self.calls.append(("restart", server_id, service))
        return self._result()

    async def reload_service(self, server_id, service):
        self.calls.append(("reload", server_id, service))
        return self._result()

    async def execute_sudo(self, server_id, command, timeout=60.0):
        self.calls.append(("sudo", server_id, command))
        return self._result()


class FakeAudit:
    def __init__(self):
        self.entries = []

    def log(self, **kwargs):
        self.entries.append(kwargs)


class FakeDetector:
    def __init__(self, can_fix=True):
        self.can_fix = can_fix
        self.attempted = []
        self.resolved = []

    def can_auto_fix(self, detected):
        return self.can_fix

    def mark_fix_attempted(self, detected):
        self.attempted.append(detected)

    def mark_resolved(self, detected, resolution):
        detected.resolved = True
        self.resolved.append(resolution)


async def fill_service_name(server_id, service_type, name):
    return "isc-dhcp-server" if name == "service_name" else None


def detected_error(commands, auto_fix=True):
    from datetime import datetime

    event = LogEvent("dhcp1", "dhcp", "/var/log/syslog", "dhcpd exiting", LogEventType.ERROR)
    pattern = ErrorPattern("exiting", "dhcp", "critical", auto_fix, "DHCP service crashed", commands=commands)
    now = datetime.now()
    return DetectedError(event, pattern, "abc", now, now)


def make(mode, success=True):
    ssh, audit = FakeSSH(success), FakeAudit()
    r = Remediator(ActionPolicy.from_file(), ssh=ssh, audit=audit,
                   resolve_placeholder=fill_service_name, mode=lambda: mode)
    return r, ssh, audit


def run(coro):
    return asyncio.run(coro)


def test_off_mode_does_nothing():
    r, ssh, _ = make("off")
    assert run(r.handle(detected_error(["systemctl restart {service_name}"]), FakeDetector())) is None
    assert ssh.calls == []


def test_suggest_mode_plans_but_runs_nothing():
    r, ssh, _ = make("suggest")
    d = detected_error(["systemctl restart {service_name}"])

    record = run(r.handle(d, FakeDetector()))

    assert record["status"] == "suggested"
    assert record["steps"][0]["command"] == "systemctl restart isc-dhcp-server"
    assert record["steps"][0]["auto"] is True
    assert ssh.calls == []
    assert d.remediation is record


def test_auto_mode_runs_allowed_restart_and_resolves():
    r, ssh, audit = make("auto")
    detector = FakeDetector()
    d = detected_error(["systemctl restart {service_name}"])

    record = run(r.handle(d, detector))

    assert record["status"] == "fixed"
    assert ssh.calls == [("restart", "dhcp1", "isc-dhcp-server")]
    assert audit.entries[0]["username"] == "auto-remediation"
    assert detector.attempted and detector.resolved and d.resolved


def test_auto_mode_leaves_risky_commands_to_a_human():
    r, ssh, _ = make("auto")
    record = run(r.handle(detected_error(["postsuper -d ALL deferred"]), FakeDetector()))

    assert record["status"] == "suggested"
    assert record["steps"][0]["result"] == "needs a human"
    assert ssh.calls == []


def test_auto_mode_respects_pattern_auto_fix_flag():
    r, ssh, _ = make("auto")
    record = run(r.handle(detected_error(["systemctl restart {service_name}"], auto_fix=False), FakeDetector()))

    assert record["status"] == "suggested"
    assert ssh.calls == []


def test_auto_mode_respects_pattern_cooldown():
    r, ssh, _ = make("auto")
    record = run(r.handle(detected_error(["systemctl restart {service_name}"]), FakeDetector(can_fix=False)))

    assert record["note"] == "pattern cooldown is active"
    assert ssh.calls == []


def test_unfillable_placeholder_is_skipped():
    r, ssh, _ = make("auto")
    record = run(r.handle(detected_error(["rndc retransfer {zone}"]), FakeDetector()))

    step = record["steps"][0]
    assert step["risk"] is None and "{zone}" in step["reason"]
    assert ssh.calls == []


def test_failed_fix_is_reported():
    r, ssh, _ = make("auto", success=False)
    detector = FakeDetector()
    record = run(r.handle(detected_error(["systemctl restart {service_name}"]), detector))

    assert record["status"] == "failed"
    assert detector.attempted and not detector.resolved


def test_manual_apply_runs_commands_the_policy_would_hold_back():
    r, ssh, audit = make("suggest")
    record = run(r.apply(detected_error(["postsuper -d ALL deferred"]), FakeDetector(), "alice", "admin", "10.0.0.5"))

    assert record["status"] == "fixed"
    assert ssh.calls == [("sudo", "dhcp1", "postsuper -d ALL deferred")]
    assert audit.entries[0]["username"] == "alice"


@pytest.mark.parametrize("mode", ["suggest", "auto"])
def test_errors_without_commands_are_ignored(mode):
    r, _, _ = make(mode)
    assert run(r.handle(detected_error([]), FakeDetector())) is None
