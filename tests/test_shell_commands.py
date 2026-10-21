"""Commands sent to remote hosts keep untrusted values as single arguments."""

import shlex

import pytest

from src.core.ssh_manager import (
    SUDO_PATH,
    build_sudo_command,
    build_tail_command,
    validate_service_name,
)


@pytest.mark.parametrize("name", ["isc-dhcp-server", "named", "getty@tty1", "systemd-resolved.service", "kea-dhcp4"])
def test_plain_unit_names_are_accepted(name):
    assert validate_service_name(name) == name


@pytest.mark.parametrize("name", ["", "-h", "dhcp; rm -rf /", "a b", "x$(id)", "../init.d/x", "svc|cat"])
def test_unsafe_service_names_are_rejected(name):
    with pytest.raises(ValueError):
        validate_service_name(name)


def test_sudo_wraps_the_whole_command():
    cmd = build_sudo_command("service x status || /etc/init.d/x status", None)

    assert shlex.split(cmd) == [
        "sudo", "-n", "env", f"PATH={SUDO_PATH}", "sh", "-c",
        "service x status || /etc/init.d/x status",
    ]


def test_sudo_password_is_passed_as_one_literal_argument():
    password = "-n it's $(reboot)"
    cmd = build_sudo_command("id", password)

    printf_part, sudo_part = cmd.split(" | ", 1)
    assert shlex.split(printf_part) == ["printf", "%s\\n", password]
    assert shlex.split(sudo_part)[:4] == ["sudo", "-S", "-p", ""]


def test_tail_command_quotes_path_and_pattern():
    cmd = build_tail_command("/var/log/my app.log", "it's | dangerous")

    tail_part, grep_part = cmd.split(" | grep ", 1)
    assert shlex.split(tail_part)[:3] == ["tail", "-F", "/var/log/my app.log"]
    assert shlex.split("grep " + grep_part) == ["grep", "--line-buffered", "it's | dangerous"]


def test_tail_without_pattern_has_no_grep():
    assert "grep" not in build_tail_command("/var/log/syslog")
