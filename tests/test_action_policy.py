"""Risk classification and limits from config/safe_actions.yaml."""

from datetime import datetime, timedelta

import pytest

from src.actions.pending import PendingCommands
from src.actions.policy import READ_ONLY, UNKNOWN, ActionLimiter, ActionPolicy
from src.core.command_resolver import _ERR_GREP


@pytest.fixture(scope="module")
def policy():
    # The shipped file, so the tests also guard its contents
    return ActionPolicy.from_file()


@pytest.mark.parametrize("command", [
    "systemctl status isc-dhcp-server --no-pager -l | head -n 25",
    "service bind9 status 2>/dev/null || /etc/init.d/bind9 status 2>/dev/null"
    " || (pgrep -x bind9 >/dev/null && echo running || echo stopped)",
    "journalctl -u named -p err -n 50 --no-pager",
    _ERR_GREP + " /var/log/syslog 2>/dev/null | tail -n 50",
    "bash -c 'for f in /var/log/syslog /var/log/messages; do [ -f \"$f\" ] && { tail -n 50 \"$f\"; break; }; done'",
    "uptime; free -m; df -h",
    "grep 'a > b' /var/log/syslog",
    "/usr/bin/tail -n 5 /var/log/syslog",
    "ip -br addr",
    "dhcpd -t -cf /etc/dhcp/dhcpd.conf 2>&1",
])
def test_read_only_commands(policy, command):
    c = policy.classify(command)
    assert (c.action, c.risk) == (READ_ONLY, 0), c.reason
    assert policy.auto_allowed(c)[0]


@pytest.mark.parametrize("command, reason", [
    ("rm -rf /var/log/x", "unrecognised program"),
    ("echo hi > /etc/passwd", "writes to a file"),
    ("cat $(ls /root)", "command substitution"),
    ("cat `ls`", "command substitution"),
    ("sed -i s/a/b/ /etc/hosts", "-i edits files"),
    ("find /var/log -name '*.gz' -delete", "-delete acts on files"),
    ("ip route add 10.0.0.0/8 via 192.0.2.1", "changes network state"),
    ("journalctl --vacuum-size=100M", "maintenance"),
    ("dhcpd -cf /etc/dhcp/dhcpd.conf", "without a test flag"),
    ("uptime; reboot", "unrecognised program"),
    ("grep 'unterminated", "unbalanced quotes"),
])
def test_unknown_or_writing_commands_need_a_human(policy, command, reason):
    c = policy.classify(command)
    assert (c.action, c.risk) == (UNKNOWN, 3)
    assert reason in c.reason
    assert not policy.auto_allowed(c)[0]


def test_restart_of_a_listed_service_may_run_alone(policy):
    c = policy.classify("sudo systemctl restart isc-dhcp-server")
    assert (c.action, c.risk, c.service) == ("restart_service", 1, "isc-dhcp-server")
    assert policy.auto_allowed(c)[0]


def test_restart_of_an_unlisted_service_needs_a_human(policy):
    allowed, why = policy.auto_allowed(policy.classify("systemctl restart nginx"))
    assert not allowed
    assert "allowed_services" in why


def test_stop_is_medium_risk(policy):
    c = policy.classify("service postfix stop")
    assert (c.action, c.risk, c.service) == ("stop_service", 2, "postfix")
    assert not policy.auto_allowed(c)[0]


def test_exact_commands_from_the_yaml(policy):
    assert policy.auto_allowed(policy.classify("rndc flush"))[0]
    allowed, why = policy.auto_allowed(policy.classify("postsuper -d ALL deferred"))
    assert not allowed  # risk 2 and has conditions


def test_compound_command_takes_the_highest_risk(policy):
    c = policy.classify("systemctl status named; systemctl stop named")
    assert (c.action, c.risk) == ("stop_service", 2)


def test_never_auto_execute_wins():
    p = ActionPolicy({
        "auto_execute": {"max_risk_level": 3, "actions": [{"name": "restart_service", "risk_level": 1}]},
        "never_auto_execute": ["restart_service"],
    })
    assert not p.auto_allowed(p.classify("systemctl restart named"))[0]


def test_missing_file_means_nothing_runs_alone(tmp_path):
    p = ActionPolicy.from_file(tmp_path / "missing.yaml")
    assert not p.auto_allowed(p.classify("systemctl restart named"))[0]
    assert p.auto_allowed(p.classify("uptime"))[0]


# ------------------------------------------------------------------------------
# ActionLimiter
# ------------------------------------------------------------------------------

def test_cooldown_and_hourly_cap(policy):
    limiter = ActionLimiter(policy)
    c = policy.classify("systemctl restart isc-dhcp-server")  # cooldown 300 s, 3 per hour
    t0 = datetime(2026, 1, 1, 12, 0)

    assert limiter.check("dhcp1", c, t0)[0]
    limiter.record("dhcp1", c, True, t0)
    ok, why = limiter.check("dhcp1", c, t0 + timedelta(seconds=10))
    assert not ok and "cooldown" in why
    assert limiter.check("dhcp2", c, t0 + timedelta(seconds=10))[0]  # per server

    limiter.record("dhcp1", c, True, t0 + timedelta(minutes=6))
    limiter.record("dhcp1", c, True, t0 + timedelta(minutes=12))
    ok, why = limiter.check("dhcp1", c, t0 + timedelta(minutes=18))
    assert not ok and "this hour" in why
    assert limiter.check("dhcp1", c, t0 + timedelta(minutes=61))[0]


def test_consecutive_failures_back_off(policy):
    limiter = ActionLimiter(policy)
    c = policy.classify("rndc flush")
    t0 = datetime(2026, 1, 1, 12, 0)
    for i in range(policy.limits.max_consecutive_failures):
        limiter.record(f"s{i}", c, False, t0)

    ok, why = limiter.check("other", c, t0 + timedelta(seconds=5))
    assert not ok and "backing off" in why


# ------------------------------------------------------------------------------
# PendingCommands
# ------------------------------------------------------------------------------

def test_pending_command_is_taken_once_by_its_owner(policy):
    pending = PendingCommands()
    item = pending.add("alice", "dns1", "systemctl stop named", True, policy.classify("systemctl stop named"))

    assert pending.take(item.id, "bob") is None
    assert pending.take(item.id, "alice") is item
    assert pending.take(item.id, "alice") is None


def test_pending_command_expires(policy):
    pending = PendingCommands(ttl=timedelta(minutes=5))
    item = pending.add("alice", "dns1", "x", False, policy.classify("x"))
    item.created_at -= timedelta(minutes=6)

    assert pending.take(item.id, "alice") is None
