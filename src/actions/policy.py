"""
Risk policy for shell commands, backed by config/safe_actions.yaml.

Every command the app runs on its own initiative (a fix for a known error) or
on behalf of an operator's plain-language request goes through classify():

    risk 0  read-only or harmless (status, logs, reload)
    risk 1  low risk (restart a service)
    risk 2  medium risk (stop a service, flush a queue)
    risk 3  anything not recognised: never runs without a human

auto_allowed() says whether a classified command may run without asking, and
ActionLimiter enforces the cooldowns and rate limits from the same file.
"""

import re
import shlex
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import yaml
from loguru import logger

from src.core.config import CONFIG_DIR

SAFE_ACTIONS_FILE = CONFIG_DIR / "safe_actions.yaml"

READ_ONLY = "read_only"
UNKNOWN = "unknown"
UNKNOWN_RISK = 3

# Lifecycle verbs -> (action name, risk used when safe_actions.yaml has no rule for it)
_LIFECYCLE = {
    "restart": ("restart_service", 1),
    "try-restart": ("restart_service", 1),
    "reload-or-restart": ("restart_service", 1),
    "force-reload": ("reload_config", 0),
    "reload": ("reload_config", 0),
    "start": ("start_service", 1),
    "stop": ("stop_service", 2),
    "kill": ("stop_service", 2),
}
_STATUS_VERBS = {"status", "is-active", "is-enabled", "is-failed", "show", "cat", "list-units", "list-unit-files"}

# Programs that only read state. Flags that make some of them write are checked separately.
_READ_ONLY_PROGRAMS = {
    "awk", "cat", "cut", "date", "df", "dig", "du", "echo", "egrep", "env", "false", "fgrep", "file",
    "free", "grep", "head", "host", "hostname", "hostnamectl", "id", "last", "less", "ls", "lsblk",
    "lscpu", "lsof", "mailq", "more", "netstat", "nproc", "nslookup", "pgrep", "ping", "printf", "ps",
    "pwd", "readlink", "realpath", "sort", "ss", "stat", "tail", "test", "timedatectl", "top", "tr",
    "true", "uname", "uniq", "uptime", "w", "wc", "which", "who", "whoami", "zcat", "zgrep",
    "named-checkconf", "named-checkzone", "postqueue", "radiusd", "freeradius",
    "[", "[[", "]", "]]",
}
_SHELL_KEYWORDS = {
    "for", "do", "done", "if", "then", "elif", "else", "fi", "while", "until", "case", "esac",
    "break", "continue", "{", "}", "(", ")", "!",
}
# Config test switches: these programs only parse config with the flag present
_CONFIG_TEST_FLAGS = {
    "dhcpd": {"-t", "-T"},
    "kea-dhcp4": {"-t"},
    "kea-dhcp6": {"-t"},
    "apachectl": {"-t", "configtest"},
    "apache2ctl": {"-t", "configtest"},
    "nginx": {"-t", "-T"},
    "unbound-checkconf": None,
    "radiusd": {"-C", "-XC"},
    "freeradius": {"-C", "-XC"},
}

_SEPARATORS = {"|", "||", "&&", ";", "&", ";;", "|&"}
_REDIRECTS = {">", ">>", "&>", "&>>", ">|", ">&", "<", "<<", "<<<", "<&"}


@dataclass
class ActionRule:
    name: str
    risk_level: int
    allowed_services: Optional[list[str]] = None
    command: Optional[str] = None
    cooldown_seconds: int = 0
    max_attempts_per_hour: Optional[int] = None
    conditions: list[str] = field(default_factory=list)


@dataclass
class Classification:
    command: str
    action: str
    risk: int
    service: Optional[str] = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "risk": self.risk, "service": self.service, "reason": self.reason}


@dataclass
class Limits:
    max_actions_per_minute: int = 5
    max_actions_per_hour: int = 30
    max_consecutive_failures: int = 3
    backoff_multiplier: float = 2
    max_backoff_seconds: int = 3600


class ActionPolicy:
    def __init__(self, data: Optional[dict] = None):
        data = data or {}
        auto = data.get("auto_execute") or {}
        self.auto_max_risk: int = int(auto.get("max_risk_level", 1))
        self.auto_rules: dict[str, ActionRule] = {}
        for raw in auto.get("actions") or []:
            rule = ActionRule(
                name=raw["name"],
                risk_level=int(raw.get("risk_level", UNKNOWN_RISK)),
                allowed_services=raw.get("allowed_services"),
                command=raw.get("command"),
                cooldown_seconds=int(raw.get("cooldown_seconds", 0)),
                max_attempts_per_hour=raw.get("max_attempts_per_hour"),
                conditions=list(raw.get("conditions") or []),
            )
            self.auto_rules[rule.name] = rule
        self.never_auto: set[str] = set(data.get("never_auto_execute") or [])
        self.limits = Limits(**(data.get("limits") or {}))

    @classmethod
    def from_file(cls, path: Optional[Path] = None) -> "ActionPolicy":
        path = path or SAFE_ACTIONS_FILE
        try:
            with open(path, encoding="utf-8") as f:
                return cls(yaml.safe_load(f))
        except FileNotFoundError:
            logger.warning(f"{path} not found: every non-read-only command will need confirmation")
            return cls()

    # ------------------------------------------------------------------ classify

    def classify(self, command: str) -> Classification:
        """Classify a shell command; a compound command takes the risk of its riskiest part."""
        command = command.strip()
        if not command:
            return Classification(command, UNKNOWN, UNKNOWN_RISK, reason="empty command")

        for rule in self.auto_rules.values():
            if rule.command and _normalize(command) == _normalize(rule.command):
                return Classification(command, rule.name, rule.risk_level, reason="matches safe_actions.yaml")

        if "`" in command or "$(" in command or "<(" in command or ">(" in command:
            return Classification(command, UNKNOWN, UNKNOWN_RISK, reason="command substitution")

        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        try:
            tokens = list(lexer)
        except ValueError:
            return Classification(command, UNKNOWN, UNKNOWN_RISK, reason="unbalanced quotes")

        segments: list[list[str]] = [[]]
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok in _SEPARATORS:
                segments.append([])
            elif tok in _REDIRECTS:
                target = tokens[i + 1] if i + 1 < len(tokens) else ""
                if tok in (">&", "<&", "<") or target == "/dev/null":
                    if segments[-1] and segments[-1][-1].isdigit():
                        segments[-1].pop()  # the fd number in "2>/dev/null"
                    i += 2
                    continue
                return Classification(command, UNKNOWN, UNKNOWN_RISK, reason="writes to a file")
            else:
                segments[-1].append(tok)
            i += 1

        worst = Classification(command, READ_ONLY, 0, reason="read-only")
        for words in segments:
            part = self._classify_segment(words)
            if part.risk > worst.risk:
                worst = Classification(command, part.action, part.risk, part.service, part.reason)
        return worst

    def _classify_segment(self, words: list[str]) -> Classification:
        segment = " ".join(words)
        words = _strip_prefixes(words)
        if words and words[0] in ("for", "case", "select"):
            # "for VAR in LIST" / "case WORD in": a loop header, not a command
            return Classification(segment, READ_ONLY, 0, reason="shell syntax")
        while words and words[0] in _SHELL_KEYWORDS:
            words = words[1:]
        if not words or words[0] == "in":
            return Classification(segment, READ_ONLY, 0, reason="shell syntax")

        prog = words[0] if words[0].startswith("/etc/init.d/") else words[0].rsplit("/", 1)[-1]
        args = words[1:]

        if prog in ("sh", "bash") and len(args) >= 2 and args[0] == "-c":
            inner = self.classify(args[1])
            return Classification(segment, inner.action, inner.risk, inner.service, inner.reason)

        lifecycle = _lifecycle(prog, args)
        if lifecycle:
            verb, service = lifecycle
            if verb in _STATUS_VERBS:
                return Classification(segment, READ_ONLY, 0, service, "service status")
            action, default_risk = _LIFECYCLE[verb]
            rule = self.auto_rules.get(action)
            risk = rule.risk_level if rule else default_risk
            return Classification(segment, action, risk, service, f"{verb} {service}")

        if prog in _CONFIG_TEST_FLAGS:
            flags = _CONFIG_TEST_FLAGS[prog]
            if flags is None or flags & set(args):
                return Classification(segment, READ_ONLY, 0, reason="config test")
            return Classification(segment, UNKNOWN, UNKNOWN_RISK, reason=f"{prog} without a test flag")

        if prog == "journalctl":
            if any(a.startswith(("--vacuum", "--rotate", "--flush", "--sync")) for a in args):
                return Classification(segment, UNKNOWN, UNKNOWN_RISK, reason="journalctl maintenance")
            return Classification(segment, READ_ONLY, 0, reason="read-only")
        if prog == "sed" and any(a == "-i" or a.startswith("-i") or a == "--in-place" for a in args):
            return Classification(segment, UNKNOWN, UNKNOWN_RISK, reason="sed -i edits files")
        if prog == "find" and any(a in ("-delete", "-exec", "-execdir", "-ok", "-fprint") for a in args):
            return Classification(segment, UNKNOWN, UNKNOWN_RISK, reason="find with an action")
        if prog == "dmesg" and any(a in ("-c", "-C", "--clear", "--read-clear") for a in args):
            return Classification(segment, UNKNOWN, UNKNOWN_RISK, reason="dmesg clears the buffer")
        if prog == "ip" and args and args[0] in ("addr", "address", "a", "route", "r", "link", "l", "neigh", "n", "-br", "-4", "-6", "-s"):
            if not any(a in ("add", "del", "delete", "set", "flush", "change", "replace") for a in args):
                return Classification(segment, READ_ONLY, 0, reason="read-only")
        if prog == "sed" or prog in _READ_ONLY_PROGRAMS:
            return Classification(segment, READ_ONLY, 0, reason="read-only")

        return Classification(segment, UNKNOWN, UNKNOWN_RISK, reason=f"unrecognised program: {prog}")

    # ------------------------------------------------------------------ decide

    def auto_allowed(self, c: Classification) -> tuple[bool, str]:
        """May this command run with nobody confirming it?"""
        if c.action == READ_ONLY:
            return True, "read-only"
        if c.action in self.never_auto:
            return False, f"{c.action} is listed under never_auto_execute"
        rule = self.auto_rules.get(c.action)
        if rule is None:
            return False, f"{c.action} is not listed under auto_execute"
        if c.risk > self.auto_max_risk:
            return False, f"risk {c.risk} is above auto_execute.max_risk_level {self.auto_max_risk}"
        if rule.conditions:
            return False, "the rule has conditions this app cannot evaluate"
        if rule.allowed_services is not None and c.service not in rule.allowed_services:
            return False, f"service {c.service!r} is not in allowed_services for {c.action}"
        return True, f"{c.action} allowed by safe_actions.yaml"

    def cooldown_for(self, c: Classification) -> int:
        rule = self.auto_rules.get(c.action)
        return rule.cooldown_seconds if rule else 0

    def max_attempts_per_hour(self, c: Classification) -> Optional[int]:
        rule = self.auto_rules.get(c.action)
        return rule.max_attempts_per_hour if rule else None


def _normalize(command: str) -> str:
    return " ".join(command.split())


def _strip_prefixes(words: list[str]) -> list[str]:
    """Drop sudo, env and VAR=value prefixes so the real program is first."""
    while words:
        head = words[0]
        if head == "sudo":
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[1:] if words[0] not in ("-u", "-g", "-p") else words[2:]
        elif head == "env" or (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", head) is not None):
            words = words[1:]
        else:
            break
    return words


def _lifecycle(prog: str, args: list[str]) -> Optional[tuple[str, str]]:
    """Return (verb, service) for systemctl / service / init.d invocations."""
    if prog == "systemctl":
        rest = [a for a in args if not a.startswith("-")]
        if len(rest) >= 2 and (rest[0] in _LIFECYCLE or rest[0] in _STATUS_VERBS):
            return rest[0], rest[1].removesuffix(".service")
        if rest and rest[0] in _STATUS_VERBS:
            return rest[0], ""
        return None
    if prog == "service" and len(args) >= 2 and (args[1] in _LIFECYCLE or args[1] in _STATUS_VERBS):
        return args[1], args[0]
    if prog.startswith("/etc/init.d/") and args and (args[0] in _LIFECYCLE or args[0] in _STATUS_VERBS):
        return args[0], prog.rsplit("/", 1)[-1]
    if prog in ("rndc",) and args and args[0] in ("reload", "reconfig"):
        return "reload", "named"
    return None


# ==============================================================================
# RATE LIMITING
# ==============================================================================

class ActionLimiter:
    """Cooldowns, hourly caps and failure backoff for actions nobody confirmed."""

    def __init__(self, policy: ActionPolicy):
        self.policy = policy
        self._lock = threading.Lock()
        self._last_run: dict[str, datetime] = {}
        self._runs_by_key: dict[str, deque[datetime]] = defaultdict(deque)
        self._all_runs: deque[datetime] = deque()
        self._failures = 0
        self._blocked_until: Optional[datetime] = None

    @staticmethod
    def key(server_id: str, c: Classification) -> str:
        return f"{server_id}:{c.action}:{c.service or c.command}"

    def check(self, server_id: str, c: Classification, now: Optional[datetime] = None) -> tuple[bool, str]:
        now = now or datetime.now()
        key = self.key(server_id, c)
        limits = self.policy.limits
        with self._lock:
            if self._blocked_until and now < self._blocked_until:
                return False, f"backing off after {self._failures} failed actions until {self._blocked_until:%H:%M:%S}"
            last = self._last_run.get(key)
            cooldown = self.policy.cooldown_for(c)
            if last and now - last < timedelta(seconds=cooldown):
                return False, f"cooldown: last run {int((now - last).total_seconds())}s ago, cooldown {cooldown}s"
            runs = self._prune(self._runs_by_key[key], now, timedelta(hours=1))
            cap = self.policy.max_attempts_per_hour(c)
            if cap is not None and len(runs) >= cap:
                return False, f"already ran {len(runs)} times this hour (max {cap})"
            all_runs = self._prune(self._all_runs, now, timedelta(hours=1))
            if len(all_runs) >= limits.max_actions_per_hour:
                return False, f"global limit: {limits.max_actions_per_hour} actions per hour"
            if sum(1 for t in all_runs if now - t < timedelta(minutes=1)) >= limits.max_actions_per_minute:
                return False, f"global limit: {limits.max_actions_per_minute} actions per minute"
        return True, "ok"

    def record(self, server_id: str, c: Classification, success: bool, now: Optional[datetime] = None) -> None:
        now = now or datetime.now()
        key = self.key(server_id, c)
        limits = self.policy.limits
        with self._lock:
            self._last_run[key] = now
            self._runs_by_key[key].append(now)
            self._all_runs.append(now)
            if success:
                self._failures = 0
                self._blocked_until = None
                return
            self._failures += 1
            if self._failures >= limits.max_consecutive_failures:
                extra = self._failures - limits.max_consecutive_failures
                seconds = min(60 * limits.backoff_multiplier ** extra, limits.max_backoff_seconds)
                self._blocked_until = now + timedelta(seconds=seconds)

    @staticmethod
    def _prune(runs: deque[datetime], now: datetime, window: timedelta) -> deque[datetime]:
        while runs and now - runs[0] >= window:
            runs.popleft()
        return runs


_policy: Optional[ActionPolicy] = None


def get_action_policy() -> ActionPolicy:
    global _policy
    if _policy is None:
        _policy = ActionPolicy.from_file()
    return _policy
