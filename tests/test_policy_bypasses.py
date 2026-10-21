"""Known ways to sneak a write or code execution past the read-only classification.

Every command in BYPASSES was classified as read-only at some point and would
have run as root without confirmation. LEGITIMATE keeps the fix from turning
ordinary diagnostics into confirmation prompts.
"""

import pytest

from src.actions.policy import READ_ONLY, ActionPolicy
from src.core.command_resolver import _ERR_GREP


@pytest.fixture(scope="module")
def policy():
    return ActionPolicy.from_file()


BYPASSES = [
    # the parser and the shell disagreed about where a command ends
    "uptime x#y; rm -rf /",
    "uptime\nrm -rf /",
    "uptime\rrm -rf /",
    "uptime ;rm -rf /",
    "cat /etc/hosts >& /etc/cron.d/x",
    "cat /etc/hosts >&/etc/cron.d/x",
    ">&",
    # read-only programs that run code
    "awk 'BEGIN{system(\"rm -rf /\")}'",
    "sed -n '1e id' /etc/hosts",
    "sed 's/x/id/e' /etc/hosts",
    "sed -f /tmp/script /etc/hosts",
    "less /etc/hosts",
    "more /etc/hosts",
    # ... or write files
    "sed -n 'w /etc/cron.d/x' /etc/hosts",
    "sed 's/x/y/w /etc/cron.d/x' /etc/hosts",
    "sed -i s/a/b/ /etc/hosts",
    "sort -o /etc/passwd /tmp/x",
    "sort -ro /etc/passwd /tmp/x",
    "sort --compress-program=sh /tmp/x",
    "uniq /tmp/a /etc/passwd",
    "named-checkzone -o /etc/x example.test db",
    "find / -fprint /etc/x",
    "find / -name x -execdir rm {} +",
    # ... or change the system
    "date -s '2020-01-01'",
    "date 010100002020",
    "hostname evil",
    "hostname -F /tmp/name",
    "hostnamectl set-hostname evil",
    "timedatectl set-time 2020-01-01",
    "ss -K dst 192.0.2.1",
    "ss -tK dst 192.0.2.1",
    "ip netns exec x rm -rf /",
    "ip route add 10.0.0.0/8 via 192.0.2.1",
    "dmesg -C",
    "postqueue -f",
    "ping -f 192.0.2.1",
    "top",
    # prefixes that change what a read-only program does
    "LD_PRELOAD=/tmp/x.so cat /etc/hosts",
    "PAGER='sh -c id' systemctl status named",
    "env -S 'rm -rf /' cat",
    "sudo -i",
    "sudo -s",
    "sudo",
    "env",
]

LEGITIMATE = [
    "sed -n '1,20p' /var/log/syslog",
    "sed -n '/error/p' /var/log/syslog",
    "sed '/^#/d' /etc/dhcp/dhcpd.conf",
    "sed -E 's/[0-9]+/N/g' /var/log/syslog",
    "sed -n '$p' /var/log/syslog",
    "sed -e 's/a/b/' -e '5q' /etc/hosts",
    "date",
    "date +%F",
    "date -u +%H:%M",
    "date -d yesterday +%F",
    "hostname -f",
    "hostnamectl",
    "timedatectl status",
    "top -bn1 | head -n 15",
    "ping -c 3 192.0.2.1",
    "postqueue -p",
    "sort -rn /tmp/x | uniq -c",
    "uniq -c /tmp/x",
    "ss -tlnp",
    "dmesg -T | tail -n 50",
    "find /var/log -name '*.log' -mtime -1",
    "ip -br addr",
    "ip route show",
    "named-checkzone example.test /var/cache/bind/db.example.test",
    "LANG=C free -m",
    "SYSTEMD_COLORS=0 systemctl status named --no-pager",
    "grep '#' /etc/hosts",
    "journalctl -n 5 2>&1 | tail -n 5",
    "ls /nope 2>/dev/null >&2",
    "grep -c 'a#b' /etc/hosts",
    _ERR_GREP + " /var/log/syslog | tail -n 50",
    "uptime; echo '--- memory ---'; free -m 2>/dev/null | head -n 2; echo '--- disk / ---'; df -h / | tail -1",
]


@pytest.mark.parametrize("command", BYPASSES)
def test_bypass_is_held_for_confirmation(policy, command):
    c = policy.classify(command)
    allowed, why = policy.auto_allowed(c)
    assert not allowed, f"{command!r} would run unconfirmed: {c.reason}"


@pytest.mark.parametrize("command", LEGITIMATE)
def test_ordinary_diagnostics_still_run(policy, command):
    c = policy.classify(command)
    assert c.action == READ_ONLY, f"{command!r} now needs confirmation: {c.reason}"
