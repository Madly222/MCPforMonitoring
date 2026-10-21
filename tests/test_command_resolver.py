"""Command resolver: templates per init system, server inference, profile and Claude caching."""

import asyncio
from dataclasses import dataclass, field

import pytest

import src.core.command_resolver as cr
import src.core.server_profile as sp
from src.actions.policy import ActionPolicy


@dataclass
class Server:
    id: str
    services: list = field(default_factory=list)
    distro: str = "debian"


@dataclass
class FakeResult:
    stdout: str
    stderr: str = ""
    exit_code: int = 0

    @property
    def success(self):
        return self.exit_code == 0

    @property
    def output(self):
        return self.stdout.strip()


class FakeSSH:
    """Answers the profile probe like a systemd or sysvinit host; counts probes."""

    def __init__(self, init="systemd", distro="debian"):
        self.init = init
        self.distro = distro
        self.probe_count = 0

    async def execute(self, server_id, command, timeout=30.0):
        if "echo init=" in command:
            self.probe_count += 1
            systemd = "1" if self.init == "systemd" else "0"
            return FakeResult(
                f"init={self.init}\nsystemctl={systemd}\njournalctl={systemd}\nservice=1\ndistro={self.distro}"
            )
        return FakeResult(f"<output: {command[:40]}>")

    async def execute_sudo(self, server_id, command, timeout=30.0):
        return FakeResult("<sudo output>")

    async def detect_init_system(self, server_id):
        class _Init:
            value = self.init
        return _Init()


SYSTEMD_FLEET = [Server("dns-138", ["dns"]), Server("dhcp-93", ["dhcp"])]
SYSV_FLEET = [Server("radius-7", ["radius"], "centos")]


@pytest.fixture(autouse=True)
def isolated_stores(tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "PROFILE_STORE", tmp_path / "server_profiles.json")
    monkeypatch.setattr(cr, "RESOLVER_CACHE_STORE", tmp_path / "resolver_cache.json")


def resolve(text, fleet, ssh, **kwargs):
    return asyncio.run(cr.CommandResolver().resolve(text, fleet, ssh, **kwargs))


def test_server_is_inferred_from_the_service():
    r = resolve("error logs for today for dns", SYSTEMD_FLEET, FakeSSH())

    assert r.server_id == "dns-138"
    assert r.intent == cr.ERRORS
    assert "journalctl -u bind9 -p err" in r.command
    assert "--since today" in r.command
    assert r.sudo is True


def test_single_server_fleet_needs_no_server_name():
    r = resolve("recent system logs", SYSV_FLEET, FakeSSH("sysvinit", "centos"))

    assert r.server_id == "radius-7"
    assert r.sudo is True
    assert r.command.startswith("bash -c")


def test_sysvinit_reads_the_service_log_file():
    ssh = FakeSSH("sysvinit", "centos")

    logs = resolve("logs radius", SYSV_FLEET, ssh)
    assert "tail -n 50 /var/log/freeradius/radius.log" in logs.command and logs.sudo

    errors = resolve("errors radius", SYSV_FLEET, ssh)
    assert 'grep -iE "error|fail|crit|fatal" /var/log/freeradius/radius.log' in errors.command and errors.sudo


def test_systemd_templates():
    ssh = FakeSSH()

    status = resolve("status dhcp on dhcp-93", SYSTEMD_FLEET, ssh)
    assert "systemctl status isc-dhcp-server" in status.command and not status.sudo

    restart = resolve("restart dhcp on dhcp-93", SYSTEMD_FLEET, ssh)
    assert restart.command == "systemctl restart isc-dhcp-server" and restart.sudo

    logs = resolve("logs dhcp on dhcp-93 last 100", SYSTEMD_FLEET, ssh)
    assert "-n 100" in logs.command and "-n 93" not in logs.command


def test_profile_is_not_probed_again():
    ssh = FakeSSH()
    resolver = cr.CommandResolver()

    asyncio.run(resolver.resolve("status dns on dns-138", SYSTEMD_FLEET, ssh))
    probes = ssh.probe_count
    asyncio.run(resolver.resolve("logs dns on dns-138", SYSTEMD_FLEET, ssh))

    assert probes <= 1
    assert ssh.probe_count == probes


def test_ambiguous_host_request_is_left_to_the_interpreter():
    assert resolve("recent system logs", SYSTEMD_FLEET, FakeSSH()) is None


def test_claude_fallback_result_is_cached():
    calls = []

    async def fallback(request, profile):
        calls.append(request)
        return ("ss -tlnp", False)

    ssh = FakeSSH()
    resolver = cr.CommandResolver()
    first = asyncio.run(resolver.resolve("show open ports for dns", SYSTEMD_FLEET, ssh, claude_fallback=fallback))
    second = asyncio.run(resolver.resolve("show open ports for dns", SYSTEMD_FLEET, ssh, claude_fallback=fallback))

    assert (first.source, first.command) == ("claude", "ss -tlnp")
    assert second.source == "cache"
    assert len(calls) == 1


@pytest.mark.parametrize("text, fleet, init, runs_alone", [
    ("status dhcp on dhcp-93", SYSTEMD_FLEET, "systemd", True),
    ("logs dhcp on dhcp-93", SYSTEMD_FLEET, "systemd", True),
    ("error logs for today for dns", SYSTEMD_FLEET, "systemd", True),
    ("restart dhcp on dhcp-93", SYSTEMD_FLEET, "systemd", True),
    ("stop dhcp on dhcp-93", SYSTEMD_FLEET, "systemd", False),
    ("status radius", SYSV_FLEET, "sysvinit", True),
    ("logs radius", SYSV_FLEET, "sysvinit", True),
    ("errors radius", SYSV_FLEET, "sysvinit", True),
    ("recent system logs", SYSV_FLEET, "sysvinit", True),
])
def test_template_commands_get_the_expected_policy_verdict(text, fleet, init, runs_alone):
    """Read-only templates and allowed restarts must not trigger a confirmation prompt."""
    r = resolve(text, fleet, FakeSSH(init))
    policy = ActionPolicy.from_file()

    allowed, why = policy.auto_allowed(policy.classify(r.command))
    assert allowed is runs_alone, f"{r.command!r}: {why}"
