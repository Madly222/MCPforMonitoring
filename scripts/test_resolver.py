"""
Offline test for the capability-aware command resolver.

Runs without a live server or Claude key: it injects a fake SSH manager whose
profile probe returns a systemd or a sysvinit host, and a fake Claude fallback.
Verifies template rendering per init system, server inference by service,
sudo on log/error reads, profile persistence, and fallback caching.

Run:  python scripts/test_resolver.py
"""

import asyncio
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.core.config as config  # noqa: E402

_TMP = Path(tempfile.mkdtemp())
config.SESSIONS_DIR = _TMP

import src.core.server_profile as sp  # noqa: E402
import src.core.command_resolver as cr  # noqa: E402

sp.PROFILE_STORE = _TMP / "server_profiles.json"
cr.RESOLVER_CACHE_STORE = _TMP / "resolver_cache.json"


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
    def __init__(self, init="systemd", distro="debian"):
        self.init = init
        self.distro = distro
        self.probe_count = 0

    async def execute(self, server_id, command, timeout=30.0):
        if "echo init=" in command:
            self.probe_count += 1
            out = (
                f"init={self.init}\nsystemctl={'1' if self.init=='systemd' else '0'}\n"
                f"journalctl={'1' if self.init=='systemd' else '0'}\n"
                f"service=1\ndistro={self.distro}"
            )
            return FakeResult(out)
        return FakeResult(f"<output: {command[:40]}>")

    async def execute_sudo(self, server_id, command, timeout=30.0):
        return FakeResult("<sudo output>")

    async def detect_init_system(self, server_id):
        class _E:
            value = self.init
        return _E()


PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_failures = 0


def check(name, condition, detail=""):
    global _failures
    print(f"  [{PASS if condition else FAIL}] {name}" + (f"  -> {detail}" if detail and not condition else ""))
    if not condition:
        _failures += 1


async def main():
    # Mirror Victor's fleet: each server runs one service; ids differ from text.
    fleet_systemd = [
        Server("dns-138", ["dns"], "debian"),
        Server("dhcp-93", ["dhcp"], "debian"),
    ]

    print("\n== server inference (no id in text) ==")
    ssh = FakeSSH(init="systemd", distro="debian")
    resolver = cr.CommandResolver()

    # Exactly the failing case: "error logs for today" + "dns", no id typed.
    r = await resolver.resolve("error logs for today for dns", fleet_systemd, ssh)
    check("infers dns-138 from service", r and r.server_id == "dns-138", r.server_id if r else "None")
    check("intent is ERRORS not LOGS", r and r.intent == cr.ERRORS, r.intent if r else "None")
    check("uses journalctl -p err", r and "journalctl -u bind9 -p err" in r.command, r.command if r else "None")
    check("adds --since today", r and "--since today" in r.command, r.command if r else "None")
    check("runs with sudo", r and r.sudo is True)

    print("\n== sysvinit radius: the permission-denied case ==")
    fleet_sysv = [Server("radius-7", ["radius"], "centos")]
    ssh2 = FakeSSH(init="sysvinit", distro="centos")
    resolver2 = cr.CommandResolver()

    # "logs" with single server -> infers it; reads radius.log via sudo, not messages.
    r = await resolver2.resolve("recent system logs", fleet_sysv, ssh2)
    check("single-server inference", r and r.server_id == "radius-7", r.server_id if r else "None")
    # No service token in "recent system logs" -> host-level, but sudo + bash -c.
    check("host logs use sudo", r and r.sudo is True)
    check("host logs wrapped in bash -c", r and r.command.startswith("bash -c"), r.command if r else "None")

    r = await resolver2.resolve("logs radius", fleet_sysv, ssh2)
    check("radius logs -> radius.log via sudo", r and "tail -n 50 /var/log/freeradius/radius.log" in r.command and r.sudo, r.command if r else "None")

    r = await resolver2.resolve("errors radius", fleet_sysv, ssh2)
    check("radius errors -> grep radius.log via sudo", r and 'grep -iE "error|fail|crit|fatal" /var/log/freeradius/radius.log' in r.command and r.sudo, r.command if r else "None")

    print("\n== systemd templates with explicit id ==")
    r = await resolver.resolve("status dhcp on dhcp-93", fleet_systemd, ssh)
    check("status -> systemctl (no sudo)", r and "systemctl status isc-dhcp-server" in r.command and not r.sudo, r.command if r else "None")
    r = await resolver.resolve("restart dhcp on dhcp-93", fleet_systemd, ssh)
    check("restart -> systemctl restart + sudo", r and r.command == "systemctl restart isc-dhcp-server" and r.sudo, r.command if r else "None")
    r = await resolver.resolve("logs dhcp on dhcp-93 last 100", fleet_systemd, ssh)
    check("logs honor last 100 (not '93')", r and "-n 100" in r.command and "-n 93" not in r.command, r.command if r else "None")

    print("\n== profile caching ==")
    check("one probe for dns-138", True)  # informational
    before = ssh.probe_count
    await resolver.resolve("status dns on dns-138", fleet_systemd, ssh)
    check("no extra probe (profile cached)", ssh.probe_count == before, f"probes now={ssh.probe_count}")

    print("\n== ambiguous host-level, multiple servers -> defer ==")
    r = await resolver.resolve("recent system logs", fleet_systemd, ssh)
    check("two servers + no service -> None (legacy)", r is None)

    print("\n== Claude fallback caching ==")
    ssh3 = FakeSSH(init="systemd", distro="debian")
    resolver3 = cr.CommandResolver()
    calls = {"n": 0}

    async def fake_fallback(req, profile):
        calls["n"] += 1
        return ("ss -tlnp", False)

    r = await resolver3.resolve("show open ports for dns", fleet_systemd, ssh3, claude_fallback=fake_fallback)
    check("fallback used", r and r.source == "claude" and r.command == "ss -tlnp", r.command if r else "None")
    r = await resolver3.resolve("show open ports for dns", fleet_systemd, ssh3, claude_fallback=fake_fallback)
    check("second call from cache", r and r.source == "cache")
    check("fallback called once", calls["n"] == 1, f"calls={calls['n']}")

    print()
    if _failures:
        print(f"\033[91m{_failures} check(s) failed\033[0m")
        sys.exit(1)
    print("\033[92mAll checks passed\033[0m")


if __name__ == "__main__":
    asyncio.run(main())
