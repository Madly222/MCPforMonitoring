"""Demo mode: the simulated hosts answer the commands the real code sends."""

import asyncio

import pytest

from src.demo.feeds import DemoONUMonitor
from src.demo.ssh import DemoSSHManager
from src.monitoring.onu_monitor import ONUStatus
from src.services.registry import SERVICE_HANDLERS


@pytest.fixture
def ssh():
    # Answers from its own simulated fleet, so no secrets.yaml is needed
    return DemoSSHManager()


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("server_id, service_type, detected", [
    ("dhcp-01", "dhcp", "isc-dhcp-server"),
    ("dns-01", "dns", "bind9"),
    ("radius-01", "radius", "freeradius"),
])
def test_services_are_detected_and_healthy(ssh, server_id, service_type, detected):
    handler = SERVICE_HANDLERS[service_type](ssh, server_id)

    assert run(handler.detect())["name"] == detected
    info = run(handler.get_info())
    assert info.state.value == "running"
    assert info.health.value == "healthy"


def test_down_host_fails_the_probe(ssh):
    ok, reason = run(ssh.probe_connection("dns-02"))
    assert not ok and "timed out" in reason.lower()


def test_restart_goes_through_sudo_and_changes_state(ssh):
    host = ssh.hosts["dhcp-01"]
    host.services["isc-dhcp-server"] = False

    result = run(ssh.restart_service("dhcp-01", "isc-dhcp-server"))

    assert result.success
    assert host.services["isc-dhcp-server"] is True


def test_restart_without_sudo_is_refused(ssh):
    result = run(ssh.execute("dhcp-01", "systemctl restart isc-dhcp-server"))
    assert not result.success


def test_system_info(ssh):
    info = run(ssh.get_system_info("dns-01"))
    assert info["hostname"] == "dns-01"
    assert info["init_system"] == "systemd"
    assert info["memory"].endswith("MB")


def test_onu_poll_has_online_low_signal_and_offline():
    from src.core.config import OLTConfig

    onus = run(DemoONUMonitor().poll_olt(OLTConfig(id="olt-01", host="192.0.2.100")))
    statuses = {o.status for o in onus}
    assert {ONUStatus.ONLINE, ONUStatus.LOW_SIGNAL, ONUStatus.OFFLINE} <= statuses
    assert len(onus) == 16
