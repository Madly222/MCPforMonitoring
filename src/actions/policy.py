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

# Programs that only read, whatever their arguments. Programs that can also write,
# set something or run code (awk, less, sed with e/w, sort -o, date -s, ...) are
# either absent, so they count as unknown, or have their arguments checked in
# _ARG_CHECKS below.
_READ_ONLY_PROGRAMS = {
    "cat", "cut", "df", "dig", "du", "echo", "egrep", "false", "fgrep", "file", "free", "grep",
    "head", "host", "id", "last", "ls", "lsblk", "lscpu", "lsof", "mailq", "netstat", "nproc",
    "nslookup", "pgrep", "printf", "ps", "pwd", "readlink", "realpath", "stat", "tail", "test",
    "tr", "true", "uname", "uptime", "w", "wc", "which", "who", "whoami", "zcat", "zgrep",
    "named-checkconf",
    "[", "[[", "]", "]]",
}
# Environment assignments allowed in front of a command (VAR=value cmd). Others,
# such as LD_PRELOAD or PAGER, can make a read-only program run arbitrary code.
_SAFE_ENV_VARS = {"LANG", "LANGUAGE", "TZ", "SYSTEMD_COLORS", "SYSTEMD_PAGER", "COLUMNS"}
_SAFE_ENV_PREFIXES = ("LC_",)
_SHELL_KEYWORDS = {
    "for", "do", "done", "if", "then", "elif", "else", "fi", "while", "until", "case", "esac",
    "break", "continue", "{", "}", "!",
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
# A parenthesis opens or closes a subshell, a case pattern, a function body or an
# arithmetic loop header; whatever follows it is a new command
_PARENS = {"(", ")"}
_ENV_ASSIGNMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=.*", re.S)
_REDIRECTS = {">", ">>", "&>", "&>>", ">|", ">&", "<", "<<", "<<<", "<&", "<>"}
# shlex returns a run of these characters as one token (")>", ";>", "((;;))");
# _split_operators cuts it into the operators sh reads
_PUNCTUATION = set("();<>|&")
_OPERATORS = sorted(_SEPARATORS | _REDIRECTS | _PARENS, key=len, reverse=True)


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
        if any(ch in command for ch in "\n\r\x00") or not command.replace("\t", " ").isprintable():
            # A newline separates commands in sh, but not for the tokenizer below
            return Classification(command, UNKNOWN, UNKNOWN_RISK, reason="line break or control character")
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
        # sh only starts a comment at the beginning of a word; shlex would also cut
        # "x#y; rm -rf /" at the '#'. Treat '#' as an ordinary character instead,
        # so anything after it is still classified.
        lexer.commenters = ""
        try:
            tokens = [op for tok in lexer for op in _split_operators(tok)]
        except ValueError:
            return Classification(command, UNKNOWN, UNKNOWN_RISK, reason="unbalanced quotes")

        segments: list[list[str]] = [[]]
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok in _SEPARATORS or tok in _PARENS:
                segments.append([])
            elif tok in _REDIRECTS:
                target = tokens[i + 1] if i + 1 < len(tokens) else ""
                # ">&2" duplicates a descriptor, but ">& file" writes the file in bash
                fd_dup = tok in (">&", "<&") and (target.isdigit() or target == "-")
                if fd_dup or tok == "<" or target == "/dev/null":
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
            # A risk-0 action such as a reload still outranks read-only, so that
            # auto_allowed checks it against its rule's allowed_services
            if part.risk > worst.risk or (worst.action == READ_ONLY and part.action != READ_ONLY):
                worst = Classification(command, part.action, part.risk, part.service, part.reason)
        return worst

    def _classify_segment(self, words: list[str]) -> Classification:
        segment = " ".join(words)
        if not words:
            return Classification(segment, READ_ONLY, 0, reason="empty")
        stripped, unsafe = _strip_prefixes(words)
        if unsafe:
            return Classification(segment, UNKNOWN, UNKNOWN_RISK, reason=unsafe)
        if not stripped:
            return Classification(segment, UNKNOWN, UNKNOWN_RISK, reason="sudo or env without a command")
        words = stripped
        if words and words[0] in ("for", "select"):
            # "for VAR in LIST" is a loop header, but in "for VAR do CMD" the body
            # starts in the same segment, so whatever follows "do" is classified
            if "do" not in words:
                return Classification(segment, READ_ONLY, 0, reason="shell syntax")
            words = words[words.index("do") + 1:]
        elif words and words[0] == "case":
            # "case WORD in PATTERN": the ")" closing the pattern starts a new segment
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
            verb, units = lifecycle
            if verb in _STATUS_VERBS:
                return Classification(segment, READ_ONLY, 0, " ".join(units), "service status")
            action, default_risk = _LIFECYCLE[verb]
            rule = self.auto_rules.get(action)
            risk = rule.risk_level if rule else default_risk
            # "systemctl restart named networking" acts on every unit it names, so no
            # single service stands for it in allowed_services
            service = units[0] if len(units) == 1 else None
            return Classification(segment, action, risk, service, f"{verb} {', '.join(units)}")

        if prog in _CONFIG_TEST_FLAGS:
            flags = _CONFIG_TEST_FLAGS[prog]
            if flags is None or flags & set(args):
                return Classification(segment, READ_ONLY, 0, reason="config test")
            return Classification(segment, UNKNOWN, UNKNOWN_RISK, reason=f"{prog} without a test flag")

        if prog == "journalctl":
            if any(a.startswith(("--vacuum", "--rotate", "--flush", "--sync")) for a in args):
                return Classification(segment, UNKNOWN, UNKNOWN_RISK, reason="journalctl maintenance")
            return Classification(segment, READ_ONLY, 0, reason="read-only")
        check = _ARG_CHECKS.get(prog)
        if check is not None:
            problem = check(args)
            if problem:
                return Classification(segment, UNKNOWN, UNKNOWN_RISK, reason=f"{prog}: {problem}")
            return Classification(segment, READ_ONLY, 0, reason="read-only")
        if prog in _READ_ONLY_PROGRAMS:
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
        if rule.allowed_services is not None and c.service is None:
            return False, f"{c.reason}: several services in one command always need confirmation"
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


def _split_operators(tok: str) -> list[str]:
    """Cut a run of shell punctuation such as ")>" or ";>" into separate operators."""
    if not tok or not set(tok) <= _PUNCTUATION:
        return [tok]
    ops = []
    while tok:
        op = next(o for o in _OPERATORS if tok.startswith(o))
        ops.append(op)
        tok = tok[len(op):]
    return ops


def _strip_prefixes(words: list[str]) -> tuple[list[str], Optional[str]]:
    """Drop sudo, env and VAR=value prefixes so the real program is first.

    Returns the remaining words and, if a prefix itself is unsafe, why.
    """
    while words:
        head = words[0]
        if head == "sudo":
            words = words[1:]
            while words and words[0].startswith("-"):
                if words[0] in ("-i", "-s", "--login", "--shell", "-e", "--edit"):
                    return words, f"sudo {words[0]}"
                words = words[1:] if words[0] not in ("-u", "-g", "-p", "-C", "-h") else words[2:]
        elif head == "env":
            words = words[1:]
            if words and words[0].startswith("-"):
                return words, f"env {words[0]}"
        elif (m := _ENV_ASSIGNMENT.fullmatch(head)) is not None:
            name = m.group(1)
            if name not in _SAFE_ENV_VARS and not name.startswith(_SAFE_ENV_PREFIXES):
                return words, f"sets {name}"
            words = words[1:]
        else:
            break
    return words, None


def _lifecycle(prog: str, args: list[str]) -> Optional[tuple[str, list[str]]]:
    """Return (verb, units) for systemctl / service / init.d invocations."""
    if prog == "systemctl":
        rest = [a for a in args if not a.startswith("-")]
        if len(rest) >= 2 and (rest[0] in _LIFECYCLE or rest[0] in _STATUS_VERBS):
            return rest[0], [unit.removesuffix(".service") for unit in rest[1:]]
        if rest and rest[0] in _STATUS_VERBS:
            return rest[0], []
        return None
    if prog == "service" and len(args) >= 2 and (args[1] in _LIFECYCLE or args[1] in _STATUS_VERBS):
        return args[1], [args[0]]
    if prog.startswith("/etc/init.d/") and args and (args[0] in _LIFECYCLE or args[0] in _STATUS_VERBS):
        return args[0], [prog.rsplit("/", 1)[-1]]
    if prog in ("rndc",) and args and args[0] in ("reload", "reconfig"):
        return "reload", ["named"]
    return None


# ==============================================================================
# ARGUMENT CHECKS
# ==============================================================================
# Each returns why the arguments make the command unsafe, or None.

def _short_flags(args: list[str]) -> set[str]:
    """Letters of grouped short options: ["-tK", "-n"] -> {"t", "K", "n"}."""
    return {ch for a in args if a.startswith("-") and not a.startswith("--") for ch in a[1:]}


def _positionals(args: list[str]) -> list[str]:
    return [a for a in args if not a.startswith("-")]


def _check_date(args):
    prev = ""
    for a in args:
        if a in ("-s", "--set") or a.startswith("--set="):
            return "sets the clock"
        if not a.startswith(("-", "+")) and prev not in ("-d", "--date", "-r", "--reference"):
            return "a bare argument sets the clock"
        prev = a
    return None


_HOSTNAME_FLAGS = {"-s", "-f", "-d", "-i", "-I", "-a", "-A", "--short", "--fqdn", "--long", "--domain",
                   "--ip-address", "--all-ip-addresses", "--alias", "--all-fqdns"}


def _check_hostname(args):
    bad = [a for a in args if a not in _HOSTNAME_FLAGS]
    return f"{bad[0]} changes the host name" if bad else None


def _verb_check(allowed):
    def check(args):
        verbs = _positionals(args)
        if verbs and verbs[0] not in allowed:
            return f"{verbs[0]} changes settings"
        return None
    return check


def _check_ss(args):
    if "K" in _short_flags(args) or "--kill" in args:
        return "-K kills sockets"
    return None


def _check_sort(args):
    if "o" in _short_flags(args) or any(a.startswith(("--output", "--compress-program")) for a in args):
        return "writes a file or runs a program"
    return None


def _check_uniq(args):
    return "a second file argument is written" if len(_positionals(args)) > 1 else None


def _check_top(args):
    return None if "b" in _short_flags(args) else "interactive without -b"


def _check_ping(args):
    return "-f floods" if "f" in _short_flags(args) else None


def _check_postqueue(args):
    return None if args and all(a in ("-p", "-j") for a in args) else "only -p and -j are read-only"


def _check_named_checkzone(args):
    return "-o writes a file" if "-o" in args else None


def _check_dmesg(args):
    if {"c", "C", "D", "E", "n"} & _short_flags(args) or any(
            a in ("--clear", "--read-clear", "--console-off", "--console-on", "--console-level") for a in args):
        return "changes the kernel log"
    return None


_FIND_ACTIONS = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}


def _check_find(args):
    used = _FIND_ACTIONS.intersection(args)
    return f"{sorted(used)[0]} acts on files" if used else None


_IP_READ = {"addr", "address", "a", "route", "r", "link", "l", "neigh", "n", "rule", "maddr", "-br", "-4", "-6",
            "-s", "-c", "-d", "-j", "-o"}
_IP_WRITE = {"add", "del", "delete", "set", "flush", "change", "replace", "append", "exec", "netns", "monitor"}


def _check_ip(args):
    if not args or args[0] not in _IP_READ:
        return "not a read-only ip subcommand"
    return "changes network state" if _IP_WRITE.intersection(args) else None


# sed scripts allowed: print/delete/quit/line-number with an optional address, and
# s/// or y/// without the e and w flags. Anything else (e, w, r, W, R, labels...) is unknown.
_SED_ADDRESS = r"(?:\d+|\$|/(?:\\.|[^/\\])*/I?)"
_SED_SIMPLE = re.compile(rf"(?:{_SED_ADDRESS}(?:,{_SED_ADDRESS})?)?!?\s*[pdq=]?")
_SED_SUBST = re.compile(
    rf"(?:{_SED_ADDRESS}(?:,{_SED_ADDRESS})?)?\s*(?:s|y)([^\w\s\\])(?:\\.|(?!\1).)*\1(?:\\.|(?!\1).)*\1[gpiI0-9]*")


def _sed_script_ok(script: str) -> bool:
    return all(_SED_SIMPLE.fullmatch(part.strip()) or _SED_SUBST.fullmatch(part.strip())
               for part in script.split(";"))


def _check_sed(args):
    scripts, i, have_e = [], 0, False
    while i < len(args):
        a = args[i]
        if a in ("-i", "--in-place") or a.startswith(("-i", "--in-place")) or a in ("-f", "--file") \
                or a.startswith("--file="):
            return f"{a} edits files or reads a script"
        if a in ("-e", "--expression"):
            if i + 1 >= len(args):
                return "-e without a script"
            scripts.append(args[i + 1])
            have_e = True
            i += 2
            continue
        if a.startswith("--expression="):
            scripts.append(a.split("=", 1)[1])
            have_e = True
        elif a.startswith("-") and a not in ("-n", "--quiet", "--silent", "-E", "-r", "--regexp-extended",
                                              "-u", "--unbuffered", "-z", "--null-data", "-s", "--separate"):
            return f"unexpected option {a}"
        elif not a.startswith("-") and not have_e and not scripts:
            scripts.append(a)
        i += 1
    if not scripts:
        return "no script"
    bad = [sc for sc in scripts if not _sed_script_ok(sc)]
    return f"script {bad[0]!r} is not plainly read-only" if bad else None


_ARG_CHECKS = {
    "date": _check_date,
    "hostname": _check_hostname,
    "hostnamectl": _verb_check({"status", "show"}),
    "timedatectl": _verb_check({"status", "show", "timesync-status", "show-timesync", "list-timezones"}),
    "ss": _check_ss,
    "sort": _check_sort,
    "uniq": _check_uniq,
    "top": _check_top,
    "ping": _check_ping,
    "postqueue": _check_postqueue,
    "named-checkzone": _check_named_checkzone,
    "dmesg": _check_dmesg,
    "find": _check_find,
    "ip": _check_ip,
    "sed": _check_sed,
}


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
