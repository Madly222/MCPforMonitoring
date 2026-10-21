"""Property-based tests for the risk classifier.

The classifier decides which commands run as root without anyone confirming
them, so its contract is checked against generated input, not just examples:

1. A dangerous command glued to a safe one, by any shell construct, never runs
   unconfirmed.
2. For commands built from known parts, the verdict matches what the parts are.
3. Arbitrary text never crashes the classifier, and nothing with a line break or
   command substitution is ever allowed.
"""

import os
import shlex

from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from src.actions.policy import READ_ONLY, ActionPolicy

POLICY = ActionPolicy.from_file()
# HYPOTHESIS_EXAMPLES=5000 python -m pytest tests/test_policy_properties.py for a deeper run
SETTINGS = settings(max_examples=int(os.environ.get("HYPOTHESIS_EXAMPLES", "400")), deadline=None,
                    suppress_health_check=[HealthCheck.too_slow])


def runs_unconfirmed(command: str) -> bool:
    return POLICY.auto_allowed(POLICY.classify(command))[0]


SAFE = [
    "uptime", "free -m", "df -h /", "cat /etc/hosts", "grep -c lease /var/lib/dhcp/dhcpd.leases",
    "tail -n 50 /var/log/syslog", "journalctl -u named -n 20 --no-pager", "systemctl status named",
    "ps aux", "ss -tlnp", "ip -br addr", "date +%F", "hostname -f", "sed -n '1,5p' /etc/hosts",
]
DANGEROUS = [
    "rm -rf /var/lib/dhcp", "sh", "bash -i", "python3 -c 'import os'", "chmod 777 /etc/shadow",
    "curl http://203.0.113.9/x", "dd if=/dev/zero of=/dev/sda", "reboot", "mkfs.ext4 /dev/sda1",
    "tee /etc/cron.d/x", "systemctl stop named", "kill -9 1", "iptables -F", "useradd x",
    "awk 'BEGIN{system(\"id\")}'", "sed -i d /etc/hosts", "date -s 2020-01-01", "hostname evil",
    "crontab -r", "nc -l 4444", "mv /etc/hosts /tmp", "cp /bin/sh /tmp/x", "ln -sf /bin/sh /usr/bin/x",
]
GLUE = [
    "{s}; {d}", "{s};{d}", "{s} && {d}", "{s} || {d}", "{s} | {d}", "{s}|{d}", "{s} & {d}",
    "{s}\n{d}", "{s}\r\n{d}", "{s} `{d}`", "{s} $({d})", "{s} <({d})", "{s} > >({d})",
    "{d}; {s}", "{d} && {s}", "{s} x#y; {d}", "bash -c '{s}; {d}'", 'sh -c "{d}"',
    "sudo {d}", "sudo -u root {d}", "env {d}", "LANG=C {d}", "LD_PRELOAD=/tmp/x.so {s}",
    "{s} > /etc/x; {s}", "( {d} )", "{{ {d}; }}", "if true; then {d}; fi", "for f in a; do {d}; done",
    "  {d}  ", "{s} ;; {d}",
]


@SETTINGS
@given(st.sampled_from(SAFE), st.sampled_from(DANGEROUS), st.sampled_from(GLUE))
def test_glued_dangerous_command_never_runs_unconfirmed(safe, dangerous, glue):
    command = glue.format(s=safe, d=dangerous)
    assert not runs_unconfirmed(command), command


@SETTINGS
@given(st.sampled_from(SAFE), st.sampled_from(DANGEROUS))
def test_dangerous_program_name_in_quotes_is_still_dangerous(safe, dangerous):
    program, _, rest = dangerous.partition(" ")
    for quoted in (f"'{program}' {rest}", f'"{program}" {rest}', f"\\{program} {rest}"):
        assert not runs_unconfirmed(f"{safe}; {quoted}"), quoted


# --- 2. verdicts for commands built from known parts --------------------------------

READERS = ["cat", "grep", "head", "tail", "wc", "ls", "stat", "uname", "uptime", "ps", "df", "du", "id"]
WRITERS = ["rm", "tee", "mv", "cp", "chmod", "chown", "dd", "sh", "bash", "python3", "perl", "awk",
           "less", "vi", "crontab", "kill", "reboot", "shutdown", "curl", "wget", "nc", "touch", "truncate"]
WORD = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789/._", min_size=1, max_size=12)
SEPARATOR = st.sampled_from([";", " ; ", " && ", " || ", " | ", " & "])


@st.composite
def pipelines(draw):
    segments = draw(st.lists(
        st.tuples(st.sampled_from(READERS + WRITERS), st.lists(WORD, max_size=3)),
        min_size=1, max_size=4,
    ))
    seps = [draw(SEPARATOR) for _ in segments[1:]]
    parts = [" ".join([prog, *args]) for prog, args in segments]
    command = parts[0] + "".join(sep + part for sep, part in zip(seps, parts[1:], strict=True))
    all_readers = all(prog in READERS for prog, _ in segments)
    return command, all_readers


@SETTINGS
@given(pipelines())
def test_verdict_matches_the_programs_used(case):
    command, all_readers = case
    c = POLICY.classify(command)
    if all_readers:
        assert c.action == READ_ONLY, (command, c.reason)
    else:
        assert c.risk == 3 and not runs_unconfirmed(command), (command, c.reason)


# --- 3. arbitrary input --------------------------------------------------------------

SHELLISH = st.text(
    alphabet=st.sampled_from(list("abcrmsht -/;|&<>$`()'\"\\#\n\r\t{}*?=!~0123456789") + ["\x00", "ｒ", "é"]),
    max_size=40,
)


@SETTINGS
@given(st.one_of(SHELLISH, st.text(max_size=60)))
@example(">&0")  # found in CI: descriptor duplication is not a write
@example("grep 'a>b' /etc/hosts")
@example("cat /etc/hosts >& /etc/cron.d/x")
def test_arbitrary_text_never_crashes_and_dangerous_syntax_is_never_allowed(text):
    c = POLICY.classify(text)
    assert 0 <= c.risk <= 3
    if runs_unconfirmed(text):
        for forbidden in ("\n", "\r", "\x00", "`", "$(", "<(", ">("):
            assert forbidden not in text, (text, c.reason)
        assert not _writing_redirects(text), (text, c.reason)


def _writing_redirects(text: str) -> list[str]:
    """Redirections that can write a file. Reading (<), descriptor
    duplication (2>&1, >&-) and /dev/null are harmless."""
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens = list(lexer)
    found = []
    for i, tok in enumerate(tokens):
        if not set(tok) & {">"} or not set(tok) <= set("<>&|"):
            continue
        target = tokens[i + 1] if i + 1 < len(tokens) else ""
        if tok in (">&", "<&") and (target.isdigit() or target == "-"):
            continue
        if target == "/dev/null":
            continue
        found.append(f"{tok} {target}")
    return found
