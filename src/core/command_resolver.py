"""
Capability-aware command resolver.

Turns a short operator request ("logs dhcp on dhcp-93", "error logs for today
for dns", "status") into a concrete shell command, using the per-server
:class:`ServerProfile` so the command is correct for that host's init system —
*without* spending Claude tokens on the common cases.

Resolution order (cheapest first):

1. **Template registry** — simple intents (status / logs / errors / restart /
   start / stop / host status) render straight to a profile-correct command.
   Cost: 0 tokens.
2. **Per-server cache** — a previously Claude-resolved intent->command for this
   exact request and profile signature. Cost: 0 tokens.
3. **Claude fallback** — only when 1 and 2 miss. The resolved command is then
   written back to the cache (scoped by profile signature) so the next
   identical request is free.

Target selection: the server may be named in the text, OR inferred from the
service (the enabled server that runs it), OR — if only one server exists —
that one. If the target is ambiguous (host-level request, several servers, no
id), the resolver returns ``None`` and the caller's legacy path takes over.

Log/error reads run with ``sudo`` because protected logs (/var/log/messages,
the system journal) are unreadable as the SSH user on many hosts.
"""

import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Callable, Awaitable

from loguru import logger

from src.core.config import SESSIONS_DIR
from src.core.server_profile import get_profile_detector, ServerProfile


RESOLVER_CACHE_STORE = SESSIONS_DIR / "resolver_cache.json"

# Intent identifiers
STATUS = "status"
LOGS = "logs"
ERRORS = "errors"
RESTART = "restart"
START = "start"
STOP = "stop"
HOST_STATUS = "host_status"

LIFECYCLE = {RESTART, START, STOP}

# Intent keyword sets. English first, plus cheap RU/RO synonyms — matching
# costs nothing and operators here work multilingually.
_INTENT_KEYWORDS = [
    (RESTART, ("restart", "перезапуск", "перезапусти", "рестарт", "repornește", "reporneste")),
    (START,   ("start", "запусти", "старт", "pornește", "porneste")),
    (STOP,    ("stop", "останови", "стоп", "oprește", "opreste")),
    (ERRORS,  ("error", "errors", "fail", "ошибк", "сбой", "eroare", "erori")),
    (LOGS,    ("log", "logs", "tail", "лог", "логи", "jurnal", "loguri")),
    (STATUS,  ("status", "state", "статус", "состояние", "stare")),
]

# request token -> canonical service key
_SERVICE_KEYWORDS = {
    "dhcp": "dhcp", "dhcpd": "dhcp", "kea": "dhcp", "dnsmasq": "dhcp",
    "dns": "dns", "bind": "dns", "named": "dns", "bind9": "dns",
    "radius": "radius", "freeradius": "radius",
    "postfix": "postfix", "mail": "postfix", "smtp": "postfix",
    "dovecot": "dovecot", "imap": "dovecot",
    "apache": "apache", "httpd": "apache", "web": "apache",
    "nginx": "nginx",
    "ssh": "ssh", "sshd": "ssh",
}

# canonical service -> systemd unit name (for journalctl -u / systemctl)
_SERVICE_UNIT = {
    "dhcp": "isc-dhcp-server",
    "dns": "bind9",
    "radius": "freeradius",
    "postfix": "postfix",
    "dovecot": "dovecot",
    "apache": "apache2",
    "nginx": "nginx",
    "ssh": "ssh",
}

# canonical service -> (sysvinit init.d name, default log file, syslog filter)
_SERVICE_SYSV = {
    "dhcp": ("isc-dhcp-server", "/var/log/syslog", "dhcpd"),
    "dns": ("bind9", "/var/log/syslog", "named"),
    "radius": ("freeradius", "/var/log/freeradius/radius.log", None),
    "postfix": ("postfix", "/var/log/mail.log", None),
    "dovecot": ("dovecot", "/var/log/mail.log", "dovecot"),
    "apache": ("apache2", "/var/log/apache2/error.log", None),
    "nginx": ("nginx", "/var/log/nginx/error.log", None),
    "ssh": ("ssh", "/var/log/auth.log", "sshd"),
}

_TODAY_WORDS = ("today", "сегодня", "azi", "astăzi", "astazi")
_ERR_GREP = 'grep -iE "error|fail|crit|fatal"'
_DEFAULT_LINES = 50


@dataclass
class ParsedRequest:
    intent: Optional[str]
    server_id: Optional[str]
    service: Optional[str]
    lines: int = _DEFAULT_LINES
    since_today: bool = False
    raw: str = ""


@dataclass
class ResolvedCommand:
    command: str
    sudo: bool
    source: str            # template | cache | claude
    intent: Optional[str]
    server_id: Optional[str]
    service: Optional[str] = None
    description: str = ""


def parse_request(text: str, server_ids: list) -> ParsedRequest:
    """Extract intent, target server, service, line count and a today-filter."""
    raw = text.strip()
    low = raw.lower()

    intent = None
    for name, keywords in _INTENT_KEYWORDS:
        if any(k in low for k in keywords):
            intent = name
            break

    server_id = None
    for sid in sorted(server_ids, key=len, reverse=True):
        if sid.lower() in low:
            server_id = sid
            break

    # Remove the server id from the working text: ids like "dhcp-93" otherwise
    # leak a bogus service ("dhcp") and a bogus line count ("93").
    scan = low.replace(server_id.lower(), " ") if server_id else low

    service = None
    for token in re.findall(r"[a-z0-9]+", scan):
        if token in _SERVICE_KEYWORDS:
            service = _SERVICE_KEYWORDS[token]
            break

    lines = _DEFAULT_LINES
    m = re.search(r"(?:last|tail|n|последн\w*|ultim\w*)\D{0,6}(\d{1,4})", scan)
    if not m:
        m = re.search(r"\b(\d{1,4})\s*(?:lines|line|строк|linii)\b", scan)
    if m:
        lines = max(1, min(2000, int(m.group(1))))

    since_today = any(w in low for w in _TODAY_WORDS)

    # A bare "status" with no service is a host-level status request.
    if intent == STATUS and service is None:
        intent = HOST_STATUS

    return ParsedRequest(
        intent=intent, server_id=server_id, service=service,
        lines=lines, since_today=since_today, raw=raw,
    )


def _journal_suffix(parsed: ParsedRequest) -> str:
    return " --since today" if parsed.since_today else ""


def _build_template(parsed: ParsedRequest, profile: ServerProfile) -> Optional[ResolvedCommand]:
    """Render a profile-correct command for a recognised simple intent."""
    intent = parsed.intent
    svc = parsed.service
    n = parsed.lines
    systemd = profile.is_systemd
    since = _journal_suffix(parsed)

    def rc(command, sudo, desc):
        return ResolvedCommand(
            command=command, sudo=sudo, source="template", intent=intent,
            server_id=parsed.server_id, service=svc, description=desc,
        )

    if intent == HOST_STATUS:
        cmd = (
            "uptime; echo '--- memory ---'; free -m 2>/dev/null | awk 'NR==1||/Mem/'; "
            "echo '--- disk / ---'; df -h / | tail -1"
        )
        return rc(cmd, False, "host status (uptime/memory/disk)")

    if intent == STATUS:
        unit = _SERVICE_UNIT.get(svc, svc)
        sysv, _, _ = _SERVICE_SYSV.get(svc, (svc, "", None))
        if systemd:
            return rc(f"systemctl status {unit} --no-pager -l | head -n 25", False, f"status of {svc}")
        cmd = (
            f"service {sysv} status 2>/dev/null || /etc/init.d/{sysv} status 2>/dev/null "
            f"|| (pgrep -x {sysv} >/dev/null && echo running || echo stopped)"
        )
        return rc(cmd, False, f"status of {svc}")

    if intent == LOGS:
        if svc is None:
            if systemd:
                return rc(f"journalctl -n {n} --no-pager{since}", True, "recent system logs")
            cmd = (
                "bash -c 'for f in /var/log/syslog /var/log/messages; do "
                "[ -f \"$f\" ] && { tail -n %d \"$f\"; break; }; done'" % n
            )
            return rc(cmd, True, "recent system logs")
        unit = _SERVICE_UNIT.get(svc, svc)
        sysv, logfile, filt = _SERVICE_SYSV.get(svc, (svc, "/var/log/syslog", None))
        if systemd:
            return rc(f"journalctl -u {unit} -n {n} --no-pager{since}", True, f"logs of {svc}")
        if filt:
            return rc(f"grep -F {filt} {logfile} 2>/dev/null | tail -n {n}", True, f"logs of {svc}")
        return rc(f"tail -n {n} {logfile}", True, f"logs of {svc}")

    if intent == ERRORS:
        if svc is None:
            if systemd:
                return rc(f"journalctl -p err -n {n} --no-pager{since}", True, "recent errors (system)")
            cmd = (
                "bash -c 'for f in /var/log/syslog /var/log/messages; do "
                "[ -f \"$f\" ] && { %s \"$f\" | tail -n %d; break; }; done'" % (_ERR_GREP, n)
            )
            return rc(cmd, True, "recent errors (system)")
        unit = _SERVICE_UNIT.get(svc, svc)
        sysv, logfile, _ = _SERVICE_SYSV.get(svc, (svc, "/var/log/syslog", None))
        if systemd:
            return rc(f"journalctl -u {unit} -p err -n {n} --no-pager{since}", True, f"errors of {svc}")
        return rc(f"{_ERR_GREP} {logfile} 2>/dev/null | tail -n {n}", True, f"errors of {svc}")

    if intent in LIFECYCLE:
        if not svc:
            return None
        unit = _SERVICE_UNIT.get(svc, svc)
        sysv, _, _ = _SERVICE_SYSV.get(svc, (svc, "", None))
        if systemd:
            return rc(f"systemctl {intent} {unit}", True, f"{intent} {svc}")
        return rc(
            f"service {sysv} {intent} 2>/dev/null || /etc/init.d/{sysv} {intent}",
            True, f"{intent} {svc}",
        )

    return None


class _ResolverCache:
    """Persistent intent->command cache, scoped per server + profile signature."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data = None

    def _load(self):
        if self._data is None:
            if RESOLVER_CACHE_STORE.exists():
                try:
                    with open(RESOLVER_CACHE_STORE, "r", encoding="utf-8") as f:
                        self._data = json.load(f)
                except Exception as e:
                    logger.error(f"Failed to load resolver cache: {e}")
                    self._data = {}
            else:
                self._data = {}
        return self._data

    def _save(self):
        RESOLVER_CACHE_STORE.parent.mkdir(parents=True, exist_ok=True)
        tmp = RESOLVER_CACHE_STORE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data or {}, f, indent=2, ensure_ascii=False)
        tmp.replace(RESOLVER_CACHE_STORE)

    @staticmethod
    def _key(server_id, signature, parsed):
        normalized = re.sub(r"\s+", " ", parsed.raw.lower()).strip()
        if server_id:
            normalized = normalized.replace(server_id.lower(), "{server}")
        return f"{server_id}|{signature}|{normalized}"

    def get(self, server_id, signature, parsed):
        with self._lock:
            return self._load().get(self._key(server_id, signature, parsed))

    def put(self, server_id, signature, parsed, command, sudo):
        with self._lock:
            data = self._load()
            data[self._key(server_id, signature, parsed)] = {
                "command": command,
                "sudo": sudo,
                "intent": parsed.intent,
                "cached_at": datetime.now().isoformat(timespec="seconds"),
            }
            self._save()


# Signature: (request_text, profile) -> (command, sudo), or None if it can't.
ClaudeFallback = Callable[[str, ServerProfile], Awaitable[Optional[tuple]]]


def _pick_server(parsed, servers):
    """Choose the target server: explicit id, else by service, else the only one."""
    if parsed.server_id:
        return next((s for s in servers if s.id == parsed.server_id), None)
    if parsed.service:
        match = next((s for s in servers if parsed.service in (s.services or [])), None)
        if match:
            return match
    if len(servers) == 1:
        return servers[0]
    return None


class CommandResolver:
    def __init__(self):
        self._cache = _ResolverCache()

    async def resolve(
        self,
        text: str,
        servers: list,
        ssh,
        claude_fallback: Optional[ClaudeFallback] = None,
    ) -> Optional[ResolvedCommand]:
        """Resolve ``text`` to a concrete command, or return ``None`` if the
        target is ambiguous / nothing matched (caller uses its legacy path).

        ``servers`` is a list of objects exposing ``.id``, ``.services`` and
        ``.distro`` (the project's ServerConfig).
        """
        server_objs = list(servers)
        server_ids = [s.id for s in server_objs]
        parsed = parse_request(text, server_ids)

        chosen = _pick_server(parsed, server_objs)
        if chosen is None:
            return None
        parsed.server_id = chosen.id

        profile = await get_profile_detector().detect(
            chosen.id, ssh, distro_hint=getattr(chosen, "distro", None)
        )

        # 1) Template registry — 0 tokens.
        templated = _build_template(parsed, profile)
        if templated:
            logger.debug(f"Resolver template hit: {parsed.intent} on {chosen.id}")
            return templated

        # 2) Per-server cache — 0 tokens.
        cached = self._cache.get(chosen.id, profile.signature, parsed)
        if cached:
            logger.debug(f"Resolver cache hit on {chosen.id}: {cached['command'][:50]}")
            return ResolvedCommand(
                command=cached["command"], sudo=cached.get("sudo", False),
                source="cache", intent=cached.get("intent"),
                server_id=chosen.id, service=parsed.service,
                description="cached resolution",
            )

        # 3) Claude fallback — caches its result for next time.
        if claude_fallback is not None:
            try:
                produced = await claude_fallback(parsed.raw, profile)
            except Exception as e:
                logger.warning(f"Resolver Claude fallback failed: {e}")
                produced = None
            if produced:
                command, sudo = produced
                self._cache.put(chosen.id, profile.signature, parsed, command, sudo)
                logger.info(f"Resolver Claude fallback -> cached for {chosen.id}")
                return ResolvedCommand(
                    command=command, sudo=sudo, source="claude",
                    intent=parsed.intent, server_id=chosen.id,
                    service=parsed.service, description="Claude-resolved",
                )

        return None


_resolver = None


def get_command_resolver() -> CommandResolver:
    global _resolver
    if _resolver is None:
        _resolver = CommandResolver()
    return _resolver
