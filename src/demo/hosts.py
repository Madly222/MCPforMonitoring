"""
Simulated Linux hosts for demo mode.

DemoHost.run() answers the shell commands the app sends (status checks,
service detection, system info, logs, restarts) from an in-memory model of the
host, so the real code above the SSH layer runs unchanged. It recognises the
shapes of commands this codebase emits; anything else succeeds with no output.
"""

import random
import re
import shlex
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from src.core.ssh_manager import SUDO_PATH


@dataclass
class DemoHost:
    server_id: str
    hostname: str
    distro: str                       # debian | centos
    init: str                         # systemd | sysvinit
    pretty_name: str
    packages: set[str]                # what service detection should find
    services: dict[str, bool]         # unit/init script -> running
    processes: dict[str, str]         # process name -> unit it belongs to
    ports_tcp: list[int]
    ports_udp: list[int]
    ip: str
    log_file: str
    files: dict[str, str] = field(default_factory=dict)
    cpu: str = "Intel(R) Xeon(R) Silver 4210R CPU @ 2.40GHz"
    cores: int = 4
    mem_total_mb: int = 3936
    mem_used_mb: int = 1180
    disk_total_gb: int = 40
    disk_used_gb: int = 17
    kernel: str = "6.1.0-26-amd64"
    booted: datetime = field(default_factory=lambda: datetime.now() - timedelta(days=37, hours=5))
    log: list[str] = field(default_factory=list)
    reachable: bool = True

    # ------------------------------------------------------------------ helpers

    def pid(self, process: str) -> int:
        return 700 + sum(map(ord, process)) % 900

    def _process_running(self, process: str) -> bool:
        unit = self.processes.get(process)
        return unit is not None and self.services.get(unit, False)

    def _log_line(self, process: str, text: str, when: Optional[datetime] = None) -> str:
        when = when or datetime.now()
        return f"{when:%b %d %H:%M:%S} {self.hostname} {process}[{self.pid(process)}]: {text}"

    def append_log(self, process: str, text: str) -> str:
        line = self._log_line(process, text)
        self.log.append(line)
        del self.log[:-500]
        return line

    def uptime_text(self) -> str:
        delta = datetime.now() - self.booted
        return f"up {delta.days} days, {delta.seconds // 3600} hours"

    # ------------------------------------------------------------------ commands

    def run(self, command: str, sudo: bool = False) -> tuple[str, str, int]:
        """Return (stdout, stderr, exit_code) for a shell command."""
        command = _unwrap(command)
        for matcher in _RULES:
            result = matcher(self, command, sudo)
            if result is not None:
                return result
        return "", "", 0


def _unwrap(command: str) -> str:
    """Strip the PATH export and sudo wrappers the SSH layer adds."""
    command = re.sub(r"^export PATH=[^;]*;\s*", "", command.strip())
    m = re.search(r"sudo (?:-n|-S -p '') env PATH=" + re.escape(SUDO_PATH) + r" sh -c (.+?)(?: 2>&1)?$", command)
    if m:
        try:
            return shlex.split(m.group(1))[0]
        except ValueError:
            return m.group(1)
    return command


# ------------------------------------------------------------------ rules
# Each rule returns None when it does not apply.

def _ok(out: str = "", code: int = 0, err: str = "") -> tuple[str, str, int]:
    return out, err, code


def _echo_ok(h, c, sudo):
    if c == "echo ok":
        return _ok("ok\n")
    if c == "whoami":
        return _ok("root\n" if sudo else "monitor\n")


def _probe(h, c, sudo):
    if "echo init=" in c:
        systemd = h.init == "systemd"
        return _ok(f"init={h.init}\nsystemctl={int(systemd)}\njournalctl={int(systemd)}\nservice=1\ndistro={h.distro}\n")
    if "systemctl --version" in c or "systemctl is-system-running" in c:
        return _ok(f"{h.init}\n")


def _detection(h, c, sudo):
    if "echo 'found'" not in c:
        return None
    words = set(re.findall(r"[A-Za-z0-9_.-]+", c))
    found = any(p in words for p in h.packages)
    return _ok("found\n" if found else "not found\n")


_LIFECYCLE = re.compile(
    r"(?:systemctl (restart|start|stop|reload|try-restart) ([\w@.:+-]+)"
    r"|service (\S+) (restart|start|stop|reload)\b"
    r"|/etc/init\.d/(\S+) (restart|start|stop|reload)\b)"
)


def _lifecycle(h, c, sudo):
    m = _LIFECYCLE.search(c)
    if not m:
        return None
    verb = m.group(1) or m.group(4) or m.group(6)
    unit = (m.group(2) or m.group(3) or m.group(5)).removesuffix(".service")
    if unit not in h.services:
        return _ok(code=5, err=f"Failed to {verb} {unit}.service: Unit {unit}.service not found.\n")
    if not sudo:
        return _ok(code=1, err="Interactive authentication required.\n")
    process = next((p for p, u in h.processes.items() if u == unit), unit)
    if verb == "stop":
        h.services[unit] = False
        h.append_log("systemd", f"Stopped {unit}.service.")
    else:
        h.services[unit] = True
        h.append_log("systemd", f"{'Reloaded' if verb == 'reload' else 'Started'} {unit}.service.")
        h.append_log(process, "Server starting service.")
    return _ok()


def _systemctl_query(h, c, sudo):
    m = re.search(r"systemctl (is-active|is-enabled|status) (?:--quiet )?(\S+?)(?:\.service)?(?:\s|$)", c)
    if not m:
        return None
    verb, unit = m.groups()
    known = unit in h.services
    running = h.services.get(unit, False)
    if verb == "is-active":
        return _ok("active\n" if running else ("inactive\n" if known else "unknown\n"), 0 if running else 3)
    if verb == "is-enabled":
        return _ok("enabled\n" if known else "not-found\n", 0 if known else 1)
    if not known:
        return _ok(code=4, err=f"Unit {unit}.service could not be found.\n")
    since = h.booted.strftime("%a %Y-%m-%d %H:%M:%S UTC")
    state = f"active (running) since {since}" if running else "inactive (dead)"
    process = next((p for p, u in h.processes.items() if u == unit), unit)
    recent = [line for line in h.log if f" {process}[" in line][-5:]
    text = (
        f"● {unit}.service - {unit}\n"
        f"     Loaded: loaded (/lib/systemd/system/{unit}.service; enabled; preset: enabled)\n"
        f"     Active: {state}\n"
        + (f"   Main PID: {h.pid(process)} ({process})\n      Tasks: 4 (limit: 4598)\n     Memory: 18.4M\n" if running else "")
        + "\n" + "\n".join(recent) + "\n"
    )
    return _ok(text, 0 if running else 3)


def _sysv_status(h, c, sudo):
    m = re.search(r"(?:service (\S+) status|/etc/init\.d/(\S+) status)", c)
    if not m or h.init != "sysvinit":
        return None
    unit = m.group(1) or m.group(2)
    if h.services.get(unit):
        process = next((p for p, u in h.processes.items() if u == unit), unit)
        return _ok(f"{process} (pid {h.pid(process)}) is running...\n")
    return _ok(f"{unit} is stopped\n", 3)


def _pgrep(h, c, sudo):
    m = re.search(r"pgrep -x '?([\w.-]+)'?", c)
    if not m:
        return None
    process = m.group(1)
    running = h._process_running(process)
    if "echo 'running'" in c or "echo running" in c:
        return _ok("running\n" if running else "stopped\n")
    return _ok(f"{h.pid(process)}\n" if running else "", 0 if running else 1)


def _rc_enabled(h, c, sudo):
    if "/etc/rc2.d/S*" in c:
        return _ok("enabled\n")


def _exists(h, c, sudo):
    m = re.search(r"\[ -([fd]) '?([^ ']+)'? \]", c)
    if not m or ("echo 'exists'" not in c and "echo exists" not in c and "&& echo" not in c):
        return None
    path = m.group(2)
    present = path in h.files or path == h.log_file or any(f.startswith(path.rstrip("/") + "/") for f in h.files)
    if "echo yes" in c:
        return _ok("yes\n" if present else "no\n")
    return _ok("exists\n" if present else "not found\n")


def _ok_checks(h, c, sudo):
    """Checks shaped like `... && echo 'ok' || echo 'fail'`: listening ports and resolution."""
    if "echo 'ok'" not in c:
        return None
    if (m := re.search(r"grep -q ':(\d+) '", c)):
        port = int(m.group(1))
        listening = port in (h.ports_udp if " -uln" in c else h.ports_tcp)
        return _ok("ok\n" if listening else "fail\n")
    if "dig " in c or "nslookup" in c or "host " in c:
        return _ok("ok\n" if h._process_running("named") else "fail\n")
    return _ok("ok\n")


def _journal(h, c, sudo):
    if "journalctl" not in c:
        return None
    n = int(m.group(1)) if (m := re.search(r"-n (\d+)", c)) else 50
    lines = h.log
    if (u := re.search(r"-u (\S+)", c)):
        process = next((p for p, unit in h.processes.items() if unit == u.group(1)), u.group(1))
        lines = [line for line in lines if f" {process}[" in line or u.group(1) in line]
    if "-p err" in c:
        lines = [line for line in lines if re.search(r"error|fail|fatal|crit|refused|denied", line, re.I)]
    return _ok("\n".join(lines[-n:]) + "\n" if lines else "-- No entries --\n")


def _log_read(h, c, sudo):
    m = re.search(r"(?:tail -n (\d+)|cat) '?(/var/log/[^ ']+)'?", c)
    if not m:
        return None
    if m.group(2) != h.log_file:
        return _ok(code=1, err=f"tail: cannot open '{m.group(2)}' for reading: No such file or directory\n")
    if not sudo and h.log_file.startswith("/var/log/freeradius"):
        return _ok(code=1, err=f"tail: cannot open '{h.log_file}' for reading: Permission denied\n")
    lines = h.log
    if (g := re.search(r"grep (?:-\w+ )*(?:-- )?['\"]?([^'\"|]+?)['\"]? ", c)):
        pattern = g.group(1)
        lines = [line for line in lines if re.search(pattern, line, re.I)]
    n = int(m.group(1) or 0) or len(lines)
    if (t := re.search(r"\| tail -n (\d+)", c)):
        n = int(t.group(1))
    return _ok("\n".join(lines[-n:]) + "\n" if lines else "")


def _file_read(h, c, sudo):
    m = re.search(r"^cat '?([^ ']+)'?(?: 2>/dev/null)?$", c)
    if m and m.group(1) in h.files:
        return _ok(h.files[m.group(1)])
    m = re.search(r"grep -c '\^lease' '?([^ ']+)'?", c)
    if m:
        return _ok(f"{h.files.get(m.group(1), '').count('lease ')}\n")


def _system_info(h, c, sudo):
    used_pct = round(100 * h.disk_used_gb / h.disk_total_gb)
    table = [
        ("/etc/os-release", lambda: f'PRETTY_NAME="{h.pretty_name}"\nNAME="{h.pretty_name.split()[0]}"\nID={h.distro}\n'),
        ("uname -r", lambda: h.kernel + "\n"),
        ("uname -m", lambda: "x86_64\n"),
        ("model name", lambda: f" {h.cpu}\n"),
        ("nproc", lambda: f"{h.cores}\n"),
        ("print $2,$3}'", lambda: f"{h.mem_total_mb} {h.mem_used_mb}\n"),
        ("free -m", lambda: f"{h.mem_used_mb}/{h.mem_total_mb}MB\n"),
        ("df -BG", lambda: f"{h.disk_total_gb} {h.disk_used_gb} {used_pct}%\n"),
        ("df -h /", lambda: f"{used_pct}%\n"),
        ("hostname", lambda: h.hostname + "\n"),
        ("uptime", lambda: h.uptime_text() + "\n"),
        ("/proc/loadavg", lambda: f"{random.uniform(0.02, 0.4):.2f} {random.uniform(0.05, 0.3):.2f} {random.uniform(0.05, 0.25):.2f}\n"),
        ("ip -4 addr", lambda: f"lo 127.0.0.1/8\neth0 {h.ip}/24\n"),
        ("ss -tlnp", lambda: "\n".join(map(str, sorted(h.ports_tcp))) + "\n"),
        ("ss -uln", lambda: "\n".join(f"UNCONN 0 0 0.0.0.0:{p} 0.0.0.0:*" for p in h.ports_udp) + "\n"),
        ("ss -tln", lambda: "\n".join(f"LISTEN 0 128 0.0.0.0:{p} 0.0.0.0:*" for p in h.ports_tcp) + "\n"),
        ("ufw status", lambda: "Status: active\n"),
        ("--state=running", lambda: f"{sum(h.services.values()) + 21}\n"),
        ("--state=failed", lambda: f"{sum(not v for v in h.services.values())}\n"),
        ("list-units --type=service", lambda: f"{len(h.services) + 24}\n"),
        ("ls /etc/init.d/", lambda: f"{len(h.services) + 18}\n"),
        ("ps aux | grep -v grep | wc -l", lambda: "112\n"),
        ("reboot-required", lambda: "no\n"),
    ]
    for needle, fn in table:
        if needle in c:
            return _ok(fn())


def _ps(h, c, sudo):
    m = re.search(r"ps aux \| grep (?:-E )?(?:-- )?'?([\w.|-]+)'?", c)
    if not m:
        return None
    names = m.group(1).split("|")
    rows = [
        f"root      {h.pid(p):>5}  0.3  1.2 112340 48212 ?  Ssl  Sep14  42:10 /usr/sbin/{p} -f"
        for p in names if h._process_running(p)
    ]
    return _ok("\n".join(rows) + ("\n" if rows else ""), 0 if rows else 1)


def _config_test(h, c, sudo):
    if re.search(r"\b(dhcpd -t|named-checkconf|radiusd -C|freeradius -C|kea-dhcp4 -t)", c):
        return _ok("Configuration OK\n")


_RULES = [
    _echo_ok, _probe, _detection, _lifecycle, _systemctl_query, _sysv_status, _pgrep,
    _rc_enabled, _exists, _ok_checks, _journal, _log_read, _file_read, _system_info, _ps, _config_test,
]


# ==============================================================================
# THE DEMO FLEET (addresses from the documentation ranges, RFC 5737)
# ==============================================================================

DHCPD_CONF = """# dhcpd.conf (demo)
authoritative;
default-lease-time 3600;
max-lease-time 7200;

subnet 192.0.2.0 netmask 255.255.255.0 {
  range 192.0.2.100 192.0.2.199;
  option routers 192.0.2.1;
  option domain-name-servers 192.0.2.11;
}
"""

LEASES = "".join(
    f"lease 192.0.2.{100 + i} {{\n  starts 3 2026/10/21 08:{i:02d}:00;\n  ends 3 2026/10/21 09:{i:02d}:00;\n"
    f"  hardware ethernet 02:00:5e:00:53:{i:02x};\n}}\n"
    for i in range(1, 38)
)

NAMED_CONF = """// named.conf.local (demo)
zone "example.test" {
    type secondary;
    primaries { 192.0.2.53; };
    file "/var/cache/bind/db.example.test";
};
"""

RADIUS_CLIENTS = """# clients.conf (demo)
client nas-01 {
    ipaddr = 192.0.2.30
    secret = demo
}
"""


def build_fleet() -> dict[str, DemoHost]:
    hosts = [
        DemoHost(
            server_id="dhcp-01", hostname="dhcp-01", distro="debian", init="systemd",
            pretty_name="Debian GNU/Linux 12 (bookworm)", packages={"isc-dhcp-server"},
            services={"isc-dhcp-server": True, "ssh": True}, processes={"dhcpd": "isc-dhcp-server", "sshd": "ssh"},
            ports_tcp=[22], ports_udp=[67], ip="192.0.2.10", log_file="/var/log/syslog",
            files={"/etc/dhcp/dhcpd.conf": DHCPD_CONF, "/var/lib/dhcp/dhcpd.leases": LEASES},
        ),
        DemoHost(
            server_id="dns-01", hostname="dns-01", distro="debian", init="systemd",
            pretty_name="Debian GNU/Linux 12 (bookworm)", packages={"bind9", "named"},
            services={"bind9": True, "named": True, "ssh": True}, processes={"named": "bind9", "sshd": "ssh"},
            ports_tcp=[22, 53, 953], ports_udp=[53], ip="192.0.2.11", log_file="/var/log/syslog",
            files={"/etc/bind/named.conf": NAMED_CONF, "/etc/bind/named.conf.local": NAMED_CONF,
                   "/var/cache/bind/db.example.test": "; zone file\n"},
            mem_used_mb=1420, disk_used_gb=11,
        ),
        DemoHost(
            server_id="radius-01", hostname="radius-01", distro="centos", init="sysvinit",
            pretty_name="CentOS Linux 7 (Core)", packages={"freeradius", "radiusd"},
            services={"radiusd": True, "freeradius": True, "sshd": True},
            processes={"radiusd": "radiusd", "freeradius": "freeradius", "sshd": "sshd"},
            ports_tcp=[22], ports_udp=[1812, 1813], ip="192.0.2.12", log_file="/var/log/freeradius/radius.log",
            files={"/etc/raddb/radiusd.conf": "# radiusd.conf (demo)\n", "/etc/raddb/clients.conf": RADIUS_CLIENTS},
            kernel="3.10.0-1160.119.1.el7.x86_64", cores=2, mem_total_mb=1838, mem_used_mb=690,
            disk_total_gb=20, disk_used_gb=14,
        ),
        DemoHost(
            server_id="dns-02", hostname="dns-02", distro="debian", init="systemd",
            pretty_name="Debian GNU/Linux 12 (bookworm)", packages={"bind9"},
            services={"bind9": True}, processes={"named": "bind9"},
            ports_tcp=[22, 53], ports_udp=[53], ip="198.51.100.53", log_file="/var/log/syslog",
            reachable=False,
        ),
    ]
    now = datetime.now()
    for h in hosts:
        if h.server_id == "dhcp-01":
            for i in range(12):
                h.log.append(h._log_line("dhcpd", f"DHCPACK on 192.0.2.{120 + i} to 02:00:5e:00:53:{i:02x} via eth0",
                                         now - timedelta(minutes=40 - 3 * i)))
        elif h.server_id == "dns-01":
            for i in range(6):
                h.log.append(h._log_line("named", f"client @0x7f 192.0.2.{40 + i}#5{i}312: query: example.test IN A + (192.0.2.11)",
                                         now - timedelta(minutes=30 - 4 * i)))
        elif h.server_id == "radius-01":
            for i in range(8):
                h.log.append(f"{now - timedelta(minutes=50 - 5 * i):%a %b %d %H:%M:%S %Y} : Auth: (1{i}) Login OK: "
                             f"[user{i}@example.test] (from client nas-01 port 0)")
    return {h.server_id: h for h in hosts}


# Lines the demo writes into the logs over time: (server_id, process, text).
# Known patterns from knowledge_base/known_errors.yaml show fix plans; the rest
# are unknown and go to Claude when an API key is set.
SCRIPTED_EVENTS = [
    (8, "dhcp-01", "dhcpd", "No free leases on subnet 192.0.2.0/24 (shared network LAN): error, pool exhausted"),
    (20, "dns-01", "named", "zone example.test/IN: refresh: failure trying primary 192.0.2.53#53 (source 0.0.0.0#0): timed out; zone expired"),
    (35, "radius-01", "radiusd", "Error: Ignoring request to auth address * port 1812 bound to server default from unknown client 203.0.113.77 port 51544 proto udp"),
    (55, "dhcp-01", "dhcpd", "Configuration file errors encountered -- exiting"),
    (80, "dns-01", "named", "error (network unreachable) resolving 'ns1.example.net/AAAA/IN': 2001:db8::53#53"),
]
RECURRING_EVENTS = [
    ("dhcp-01", "dhcpd", "DHCPDECLINE of 192.0.2.150 from 02:00:5e:00:53:99 via eth0: abandoned, failed address conflict"),
    ("dns-01", "named", "client @0x7f 192.0.2.77#40112 (example.test): query failed (SERVFAIL) for example.test/IN/MX"),
    ("radius-01", "radiusd", "Auth: (412) Login incorrect (mschap: MS-CHAP2-Response is incorrect): [user9@example.test] failed"),
    ("dhcp-01", "dhcpd", "Unable to add forward map from host-150.example.test to 192.0.2.150: timed out, error"),
]
