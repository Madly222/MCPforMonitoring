"""Offline tests for the pure MAC-trace logic (no network/deps needed)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.monitoring.mac_port_sync import (
    normalize_mac,
    classify_vendor,
    parse_mac_table,
    parse_mikrotik_bridge_host,
    count_macs_per_port,
    build_mac_index,
    pick_leaf,
    _creds_for,
    _classify_ssh_error,
    parse_olt_mac_output,
    load_extra_devices,
)
import src.monitoring.mac_port_sync as mps


def test_normalize_mac():
    assert normalize_mac("ec23.7bb5.01f4") == "EC:23:7B:B5:01:F4"
    assert normalize_mac("EC-23-7B-B5-01-F4") == "EC:23:7B:B5:01:F4"
    assert normalize_mac("ec:23:7b:b5:01:f4") == "EC:23:7B:B5:01:F4"
    assert normalize_mac("garbage") is None


def test_classify_vendor():
    assert classify_vendor("ZTE", "") == "olt"
    assert classify_vendor("Cisco Systems", "ios") == "cisco"
    assert classify_vendor("Cisco", "SG550X-24") == "cisco_sg"
    assert classify_vendor("Cisco", "", "CIS-SG550-SW50-BDEC") == "cisco_sg"
    assert classify_vendor("Mikrotik", "RouterOS") == "mikrotik"
    assert classify_vendor("TP-Link", "JetStream") == "tplink"
    assert classify_vendor("D-Link", "DGS-1210") == "dlink"
    assert classify_vendor("RAD", "Optimux") == "unknown"
    assert classify_vendor("APC", "") == "unknown"
    assert classify_vendor("Juniper", "") == "unknown"


def test_parse_olt_mac_output():
    out = """
show mac gpon olt gpon-olt_1/1/4
ec23.7bb5.01f4   800    Dynamic   gpon-onu_1/1/4:14   vport 1
ec23.7bb5.01f4   800    Dynamic   gpon-onu_1/1/4:14   vport 2
aabb.ccdd.0001   801    Dynamic   gpon-onu_1/1/4:2    vport 1
--More--
bbcc.ddee.0002   802    Dynamic   gpon-onu_1/1/13:7   vport 1
"""
    entries = parse_olt_mac_output(out)
    assert ("EC:23:7B:B5:01:F4", "gpon-onu_1/1/4:14") in entries
    assert ("AA:BB:CC:DD:00:01", "gpon-onu_1/1/4:2") in entries
    assert ("BB:CC:DD:EE:00:02", "gpon-onu_1/1/13:7") in entries
    macs = [m for m, _ in entries]
    assert macs.count("EC:23:7B:B5:01:F4") == 1


def test_classify_ssh_error():
    assert _classify_ssh_error(Exception("Authentication to device failed.")) == "auth"
    assert _classify_ssh_error(Exception("TCP connection to device failed.")) == "conn"

    class NetmikoAuthenticationException(Exception):
        pass
    assert _classify_ssh_error(NetmikoAuthenticationException("nope")) == "auth"


def test_creds_precedence(monkeypatch=None):
    import os
    os.environ["SSH_USERNAME"] = "envuser"
    os.environ["SSH_PASSWORD"] = "envpass"
    os.environ.pop("TPLINK_SSH_USERNAME", None)
    os.environ.pop("TPLINK_SSH_PASSWORD", None)
    assert _creds_for("cisco", "rtuser", "rtpass") == ("rtuser", "rtpass")
    assert _creds_for("cisco", None, None) == ("envuser", "envpass")
    os.environ["TPLINK_SSH_USERNAME"] = "tpu"
    os.environ["TPLINK_SSH_PASSWORD"] = "tpp"
    assert _creds_for("tplink", None, None) == ("tpu", "tpp")


def test_load_extra_devices(tmp_path=None):
    import tempfile
    import os
    content = (
        "# comment line\n"
        "\n"
        "10.10.10.61,cisco,CIS-2960-SW61\n"
        "10.10.10.62,tplink\n"
        "bad-line-no-vendor\n"
    )
    fd, path = tempfile.mkstemp(suffix=".txt")
    with os.fdopen(fd, "w") as fh:
        fh.write(content)
    old = mps.EXTRA_DEVICES_FILE
    mps.EXTRA_DEVICES_FILE = path
    try:
        devices = load_extra_devices()
    finally:
        mps.EXTRA_DEVICES_FILE = old
        os.unlink(path)
    assert len(devices) == 2
    assert devices[0]["name"] == "CIS-2960-SW61"
    assert devices[0]["primary_ip"] == "10.10.10.61"
    assert devices[1]["name"] == "10.10.10.62"
    assert devices[1]["manufacturer"] == "tplink"


def test_required_callables_exist():
    import src.monitoring.mac_port_sync as m
    for fn in (
        "get_olt_mac_entries",
        "get_mac_table_via_netmiko",
        "get_mac_table_mikrotik",
        "_resolve_olt_device_name",
        "sync_ports_to_netbox",
    ):
        assert callable(getattr(m, fn, None)), f"missing callable: {fn}"


def test_parse_mikrotik_bridge_host():
    out = """
Flags: X - disabled, I - invalid, D - dynamic, L - local
 #    MAC-ADDRESS       VID ON-INTERFACE  BRIDGE   AGE
 0 DL EC:23:7B:B5:01:F4     ether5        bridge1  0s
 1 D  AA:BB:CC:DD:EE:01     ether5        bridge1  10s
"""
    entries = parse_mikrotik_bridge_host(out)
    counts = count_macs_per_port(entries)
    assert ("EC:23:7B:B5:01:F4", "ether5") in entries
    assert counts["ether5"] == 2


def test_parse_cisco_table():
    out = """
          Mac Address Table
-------------------------------------------

Vlan    Mac Address       Type        Ports
----    -----------       --------    -----
 800    ec23.7bb5.01f4    DYNAMIC     Gi0/2
 800    aabb.ccdd.0001    DYNAMIC     Gi0/1
 800    aabb.ccdd.0002    DYNAMIC     Gi0/1
 800    aabb.ccdd.0003    DYNAMIC     Gi0/1
"""
    entries = parse_mac_table(out)
    assert ("EC:23:7B:B5:01:F4", "Gi0/2") in entries
    counts = count_macs_per_port(entries)
    assert counts["Gi0/1"] == 3
    assert counts["Gi0/2"] == 1


def test_parse_tplink_table():
    out = """
MAC Address        VLAN   Port     Type
AA-BB-CC-DD-EE-01  1      Gi1/0/5  dynamic
AA-BB-CC-DD-EE-02  1      Gi1/0/5  dynamic
"""
    entries = parse_mac_table(out)
    counts = count_macs_per_port(entries)
    assert counts["Gi1/0/5"] == 2


def test_leaf_selection_real_example():
    # Same client MAC seen on a core uplink (many MACs) and on the OLT leaf.
    mac = "EC:23:7B:B5:01:F4"
    core = [(mac, "Gi0/1")] + [(f"AA:BB:CC:00:00:{i:02X}", "Gi0/1") for i in range(20)]
    olt = [(mac, "gpon-onu_1/1/5:1")]

    index = build_mac_index({
        "CORE-SW01": core,
        "ZTE-C320-SW30-N.TST": olt,
    })

    leaf = pick_leaf(index[mac], threshold=3)
    assert leaf["hostname"] == "ZTE-C320-SW30-N.TST"
    assert leaf["port"] == "gpon-onu_1/1/5:1"
    assert leaf["count"] == 1


def test_leaf_prefers_access_over_trunk():
    mac = "DE:AD:BE:EF:00:01"
    agg = [(mac, "Te1/1")] + [(f"11:22:33:44:00:{i:02X}", "Te1/1") for i in range(50)]
    access = [(mac, "Gi0/7"), ("11:22:33:44:55:66", "Gi0/7")]  # client + one TV box

    index = build_mac_index({"AGG-SW": agg, "ACCESS-SW12": access})
    leaf = pick_leaf(index[mac], threshold=3)
    assert leaf["hostname"] == "ACCESS-SW12"
    assert leaf["port"] == "Gi0/7"


def test_no_leaf_when_only_trunks():
    mac = "00:00:00:00:00:99"
    trunk = [(mac, "Po1")] + [(f"00:00:00:00:11:{i:02X}", "Po1") for i in range(10)]
    index = build_mac_index({"CORE": trunk})
    assert pick_leaf(index[mac], threshold=3) is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("All offline tests passed.")
