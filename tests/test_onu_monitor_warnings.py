"""The 'no SSH credentials' warning must fire only when credentials are missing."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

import src.monitoring.onu_monitor as om
from src.core.config import OLTConfig

NO_CREDS = "ssh_username/ssh_password not set"


class _Config:
    def get_onu_monitoring_config(self):
        return None


def _poll(monkeypatch, olt, rx_table):
    async def fake_snmpwalk(host, community, oid, timeout=30):
        if oid == om.ZTE_C320_OIDS["onu_name"]:
            return {"268501248.1": "ONU-1:1"}
        if oid == om.ZTE_C320_OIDS["onu_status"]:
            return {"268501248.1": "1"}
        return {}

    async def fake_ssh(*args, **kwargs):
        return {}, dict(rx_table), {}

    monkeypatch.setattr(om, "snmpwalk_cli", fake_snmpwalk)
    monkeypatch.setattr(om, "ssh_get_olt_data", fake_ssh)

    monitor = om.ONUMonitor.__new__(om.ONUMonitor)
    monitor.config = _Config()
    monitor._onu_cache, monitor._last_poll, monitor._power_history = {}, {}, {}

    messages = []
    sink = logger.add(lambda m: messages.append(m.record["message"]), level="WARNING")
    try:
        onus = asyncio.run(monitor.poll_olt(olt))
    finally:
        logger.remove(sink)
    return onus, messages


def test_no_warning_when_optics_arrive(monkeypatch):
    olt = OLTConfig(id="olt-1", host="192.0.2.5", ssh_username="u", ssh_password="p")
    onus, messages = _poll(monkeypatch, olt, {"1:1": -20.5})
    assert len(onus) == 1 and onus[0].rx_power == -20.5
    assert not any(NO_CREDS in m for m in messages)


def test_warning_when_credentials_missing(monkeypatch):
    olt = OLTConfig(id="olt-1", host="192.0.2.5")
    _, messages = _poll(monkeypatch, olt, {})
    assert any(NO_CREDS in m for m in messages)
