#!/usr/bin/env python3
"""
MAC -> leaf port -> NetBox Interface Assignment sync.

For every IP in NetBox that carries a MAC (custom field, populated by
dhcp_mac_sync), locate the *edge* device/port where that MAC actually sits and
assign the IP to the matching interface in NetBox.

Approach (agreed design):
  1. Pull all NetBox devices that have a primary IP + a vendor hint.
  2. Scan each device once for its full MAC table (Cisco/TP-Link via netmiko,
     ZTE C320 OLT via the existing onu_monitor SSH helper).
  3. Build an index  MAC -> [(hostname, port, mac_count_on_that_port)].
  4. For each client MAC, the leaf is the (device, port) whose port carries at
     most `leaf_threshold` MACs (a client plus a TV box or two). Uplinks/trunks
     carry many MACs and are discarded.
  5. Assign the IP to that interface, preserving the MAC custom field.

Missing interfaces are reported, never auto-created.
"""

import os
import re
import sys
import asyncio
from pathlib import Path

try:
    from loguru import logger
except ImportError:  # pragma: no cover - allows importing pure helpers bare
    import logging
    logger = logging.getLogger("mac_port_sync")

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except ImportError:  # pragma: no cover
    pass

_services_path = str(Path(__file__).parent.parent.parent / "services" / "netbox-autofill")
if _services_path not in sys.path:
    sys.path.insert(0, _services_path)


DEFAULT_LEAF_THRESHOLD = int(os.getenv("MAC_LEAF_THRESHOLD", "3"))
CREATE_MISSING_IFACE = os.getenv("MAC_CREATE_MISSING_IFACE", "false").lower() in ("1", "true", "yes")

NETMIKO_DEVICE_TYPES = {
    "cisco": "cisco_ios",
    "cisco_sg": "cisco_s300",
    "tplink": "tplink_jetstream",
    "mikrotik": "mikrotik_routeros",
    "dlink": "dlink_ds",
}

_MAC_RE = re.compile(
    r"(?:[0-9a-fA-F]{2}[:\-]){5}[0-9a-fA-F]{2}"
    r"|(?:[0-9a-fA-F]{4}\.){2}[0-9a-fA-F]{4}"
)
_PORT_RE = re.compile(
    r"(?:Gi|Te|Fa|Eth|Fo|Twe|Hu|Po|mgmt|gpon-onu_)\S*"
    r"|\d+/\d+(?:/\d+)?(?::\d+)?",
    re.IGNORECASE,
)


def normalize_mac(mac):
    """Return AA:BB:CC:DD:EE:FF or None."""
    if not mac:
        return None
    clean = re.sub(r"[.:\-\s]", "", str(mac).lower())
    if len(clean) != 12 or not re.match(r"^[0-9a-f]{12}$", clean):
        return None
    return ":".join(clean[i:i + 2] for i in range(0, 12, 2)).upper()


def classify_vendor(manufacturer, platform, name=""):
    """Map NetBox manufacturer/platform/name text to a scan strategy."""
    blob = f"{manufacturer} {platform} {name}".lower()
    if "zte" in blob:
        return "olt"
    if "mikrotik" in blob or "routeros" in blob:
        return "mikrotik"
    if "tp-link" in blob or "tplink" in blob or "jetstream" in blob:
        return "tplink"
    if "d-link" in blob or "dlink" in blob:
        return "dlink"
    if "cisco" in blob or re.search(r"\bcis-", blob):
        if re.search(r"sg\d|small business|sg3|sg5|s300", blob):
            return "cisco_sg"
        return "cisco"
    return "unknown"


def parse_mac_table(output):
    """
    Parse a generic switch 'show mac address-table' dump.

    Returns list of (mac, port). Handles Cisco (dotted MAC, port last) and
    TP-Link (dashed MAC) layouts by extracting the first MAC-looking token and
    the first port-looking token on each line.
    """
    entries = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        mac_match = _MAC_RE.search(line)
        if not mac_match:
            continue
        mac = normalize_mac(mac_match.group(0))
        if not mac:
            continue
        rest = line[mac_match.end():]
        port_match = _PORT_RE.search(rest)
        if not port_match:
            port_match = _PORT_RE.search(line[:mac_match.start()])
        if not port_match:
            continue
        port = port_match.group(0).strip()
        if port.lower() in ("dynamic", "static", "all"):
            continue
        entries.append((mac, port))
    return entries


def count_macs_per_port(entries):
    """entries: list of (mac, port) -> dict[port] = count."""
    counts = {}
    for _, port in entries:
        counts[port] = counts.get(port, 0) + 1
    return counts


def get_mac_table_via_netmiko(host, username, password, device_type, timeout=30):
    """Return list of (mac, port) from a Cisco/TP-Link switch over SSH."""
    from netmiko import ConnectHandler
    device = {
        "device_type": device_type,
        "host": host,
        "username": username,
        "password": password,
        "timeout": timeout,
        "auth_timeout": 15,
        "banner_timeout": 15,
        "conn_timeout": 8,
        "disabled_algorithms": {"pubkeys": ["rsa-sha2-256", "rsa-sha2-512"], "kex": []},
    }
    conn = None
    try:
        conn = ConnectHandler(**device)
        try:
            conn.send_command("terminal length 0", expect_string=r"[#>]")
        except Exception:
            pass
        output = conn.send_command("show mac address-table")
        if not output or "invalid" in output.lower():
            output = conn.send_command("show mac-address-table")
        return parse_mac_table(output)
    finally:
        if conn:
            try:
                conn.disconnect()
            except Exception:
                pass


_MIKROTIK_IFACE_RE = re.compile(r"\b(?:ether|sfp|sfp-sfpplus|combo|wlan|vlan|bridge)\S*", re.IGNORECASE)


def parse_mikrotik_bridge_host(output):
    """Parse RouterOS '/interface bridge host print' into (mac, on-interface)."""
    entries = []
    for line in output.splitlines():
        mac_match = _MAC_RE.search(line)
        if not mac_match:
            continue
        mac = normalize_mac(mac_match.group(0))
        if not mac:
            continue
        rest = line[mac_match.end():]
        ifaces = [m.group(0) for m in _MIKROTIK_IFACE_RE.finditer(rest)]
        ifaces = [i for i in ifaces if not i.lower().startswith("bridge")] or ifaces
        if not ifaces:
            continue
        entries.append((mac, ifaces[0]))
    return entries


def get_mac_table_mikrotik(host, username, password, timeout=30):
    """Return list of (mac, on-interface) from a MikroTik RouterOS device."""
    from netmiko import ConnectHandler
    device = {
        "device_type": "mikrotik_routeros",
        "host": host,
        "username": username,
        "password": password,
        "timeout": timeout,
        "auth_timeout": 15,
        "conn_timeout": 8,
        "disabled_algorithms": {"pubkeys": ["rsa-sha2-256", "rsa-sha2-512"], "kex": []},
    }
    conn = None
    try:
        conn = ConnectHandler(**device)
        output = conn.send_command("/interface bridge host print")
        return parse_mikrotik_bridge_host(output)
    finally:
        if conn:
            try:
                conn.disconnect()
            except Exception:
                pass


def parse_olt_mac_output(output):
    """Parse 'show mac gpon olt ...' output into unique (mac, gpon-onu interface) pairs."""
    entries = []
    seen = set()
    for line in output.splitlines():
        line = line.strip()
        m = re.match(
            r"^([0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4})\s+.*gpon-onu_1/1/(\d+):(\d+)",
            line, re.IGNORECASE,
        )
        if not m:
            continue
        mac = normalize_mac(m.group(1))
        if not mac:
            continue
        iface = f"gpon-onu_1/1/{m.group(2)}:{m.group(3)}"
        key = (mac, iface)
        if key in seen:
            continue
        seen.add(key)
        entries.append((mac, iface))
    return entries


def _build_olt_expect_script(host, username, password, port, max_port, timeout):
    header = f'''
set timeout {timeout}
spawn ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o KexAlgorithms=+diffie-hellman-group1-sha1 -o HostKeyAlgorithms=+ssh-dss -o Ciphers=+aes128-cbc -p {port} {username}@{host}
expect {{
    "password:" {{ send "{password}\\r"; exp_continue }}
    "#" {{ }}
    ">" {{ }}
    timeout {{ exit 1 }}
}}
'''
    body = ""
    for gp in range(1, max_port + 1):
        body += f'''
send "show mac gpon olt gpon-olt_1/1/{gp}\\r"
expect {{
    "--More--" {{ send " "; exp_continue }}
    " --More-- " {{ send " "; exp_continue }}
    "----- more -----" {{ send " "; exp_continue }}
    "Press any key" {{ send " "; exp_continue }}
    "#" {{ }}
    ">" {{ }}
    timeout {{ }}
}}
'''
    footer = '''
send "exit\\r"
expect eof
'''
    return header + body + footer


def _run_olt_full_scan(olt_cfg):
    """Paging-safe scan of all GPON ports; returns raw CLI text (best-effort)."""
    import subprocess
    host = olt_cfg.host
    username = olt_cfg.ssh_username
    password = olt_cfg.ssh_password
    port = getattr(olt_cfg, "ssh_port", 22) or 22
    max_port = int(os.getenv("MAC_OLT_MAX_PORT", "16"))
    per = int(os.getenv("MAC_OLT_SSH_TIMEOUT", "8"))
    script = f'''
set timeout {per}
spawn ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o KexAlgorithms=+diffie-hellman-group1-sha1 -o HostKeyAlgorithms=+ssh-dss -o Ciphers=+aes128-cbc -p {port} {username}@{host}
expect {{
    "password:" {{ send "{password}\\r"; exp_continue }}
    "#" {{ }}
    ">" {{ }}
    timeout {{ exit 1 }}
}}
'''
    for gp in range(1, max_port + 1):
        script += f'''
send "show mac gpon olt gpon-olt_1/1/{gp}\\r"
expect {{
    "--More--" {{ send " "; exp_continue }}
    "-- more --" {{ send " "; exp_continue }}
    "Press any key" {{ send " "; exp_continue }}
    "#" {{ }}
    ">" {{ }}
    timeout {{ }}
}}
'''
    script += '''
send "exit\\r"
expect eof
'''
    proc = subprocess.run(["expect", "-c", script], capture_output=True, timeout=per * max_port + 45)
    return proc.stdout.decode(errors="ignore")


def get_olt_mac_entries(olt_cfg, log=None):
    """Return unique (mac, gpon-onu interface): proven baseline merged with a full paging-safe scan."""
    entries = set()

    try:
        from src.monitoring.onu_monitor import ssh_get_mac_table
        table = asyncio.run(ssh_get_mac_table(
            olt_cfg.host,
            olt_cfg.ssh_username,
            olt_cfg.ssh_password,
            olt_cfg.ssh_port if hasattr(olt_cfg, "ssh_port") else 22,
        ))
        for key, mac in table.items():
            try:
                port_num, onu_id = key.split(":")
            except ValueError:
                continue
            nm = normalize_mac(mac)
            if nm:
                entries.add((nm, f"gpon-onu_1/1/{port_num}:{onu_id}"))
    except Exception as e:
        if log:
            log(f"    OLT {olt_cfg.id}: baseline scan error: {e}")
    baseline = len(entries)

    enhanced = 0
    raw_bytes = 0
    try:
        raw = _run_olt_full_scan(olt_cfg)
        raw_bytes = len(raw)
        for pair in parse_olt_mac_output(raw):
            enhanced += 1
            entries.add(pair)
    except Exception as e:
        if log:
            log(f"    OLT {olt_cfg.id}: full scan error: {e}")

    if log:
        log(f"    OLT {olt_cfg.id} scan: baseline={baseline} enhanced={enhanced} merged={len(entries)} (raw {raw_bytes}B)")
    return list(entries)


def build_mac_index(device_entries):
    """
    device_entries: dict[hostname] = list of (mac, port)
    Returns dict[mac] = list of {hostname, port, count}
    """
    index = {}
    for hostname, entries in device_entries.items():
        port_counts = count_macs_per_port(entries)
        for mac, port in entries:
            index.setdefault(mac, []).append({
                "hostname": hostname,
                "port": port,
                "count": port_counts[port],
            })
    return index


def pick_leaf(candidates, threshold):
    """
    Choose the edge (device, port) for a MAC.

    A leaf port carries at most `threshold` MACs. Ties are broken by fewest
    MACs, then by preferring a gpon-onu (physically an end ONU).
    """
    leaves = [c for c in candidates if c["count"] <= threshold]
    if not leaves:
        return None

    def rank(c):
        is_gpon = 0 if c["port"].lower().startswith("gpon-onu") else 1
        return (c["count"], is_gpon)

    leaves.sort(key=rank)
    return leaves[0]


EXTRA_DEVICES_FILE = os.getenv(
    "MAC_SCAN_DEVICES_FILE",
    str(Path(__file__).parent.parent.parent / "config" / "scan_devices.txt"),
)

MAC_MGMT_PREFIX = os.getenv("MAC_MGMT_PREFIX", "10.10.10.0/24")


def _creds_for(vendor, runtime_user, runtime_pass):
    """Pick SSH creds: runtime (from the button) overrides env; TP-Link may differ."""
    if runtime_user and runtime_pass:
        return runtime_user, runtime_pass
    if vendor == "tplink":
        return (
            os.getenv("TPLINK_SSH_USERNAME", os.getenv("SSH_USERNAME", "")),
            os.getenv("TPLINK_SSH_PASSWORD", os.getenv("SSH_PASSWORD", "")),
        )
    return os.getenv("SSH_USERNAME", ""), os.getenv("SSH_PASSWORD", "")


def load_extra_devices():
    """Read the optional inventory file: 'ip,vendor[,name]' per line, '#' comments."""
    devices = []
    path = Path(EXTRA_DEVICES_FILE)
    if not path.exists():
        return devices
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2 or not parts[0]:
            continue
        ip = parts[0]
        vendor = parts[1].lower()
        name = parts[2] if len(parts) > 2 and parts[2] else ip
        devices.append({
            "name": name,
            "primary_ip": ip,
            "manufacturer": vendor,
            "platform": "",
            "source": "file",
        })
    return devices


def _classify_ssh_error(exc):
    """Return 'auth' for authentication failures, else 'conn'."""
    name = exc.__class__.__name__.lower()
    msg = str(exc).lower()
    if "authentication" in name or "authentication" in msg or "auth failed" in msg or "bad password" in msg:
        return "auth"
    return "conn"


def get_switch_entries(vendor, host, user, password):
    """Dispatch a MAC-table scan to the right adapter. Returns list of (mac, port)."""
    if vendor == "mikrotik":
        return get_mac_table_mikrotik(host, user, password)
    if vendor in NETMIKO_DEVICE_TYPES:
        return get_mac_table_via_netmiko(host, user, password, NETMIKO_DEVICE_TYPES[vendor])
    raise ValueError(f"no scan adapter for vendor '{vendor}'")


def _resolve_olt_device_name(nb, olt, log):
    """Resolve a config OLT to its NetBox device name (explicit, then by IP, then fuzzy)."""
    explicit = getattr(olt, "netbox_name", None)
    if explicit and nb.find_device_by_name_exact(explicit):
        return explicit
    dev = nb.find_device_by_ip(olt.host)
    if dev and dev.get("name"):
        return dev["name"]
    dev = nb.find_device_by_name(olt.id)
    if dev and dev.get("name"):
        log(f"  OLT {olt.id}: matched NetBox device by name -> {dev['name']}")
        return dev["name"]
    return None


def sync_ports_to_netbox(leaf_threshold=None, cred_sets=None, progress_callback=None):
    """Run the full MAC -> leaf port -> NetBox assignment sync.

    cred_sets: ordered list of (username, password) tried per switch until one
    authenticates (e.g. a RADIUS account then a local SSH account). Empty/None
    falls back to credentials from .env.
    """
    import urllib3
    urllib3.disable_warnings()

    if leaf_threshold is None:
        leaf_threshold = DEFAULT_LEAF_THRESHOLD

    cred_sets = [(u, p) for (u, p) in (cred_sets or []) if u and p]

    logs = []
    failures = []
    stats = {
        "total": 0, "assigned": 0, "already_ok": 0,
        "no_leaf": 0, "iface_missing": 0, "dev_missing": 0, "errors": 0,
        "devices_scanned": 0, "devices_failed": 0, "devices_skipped": 0,
    }

    def log(msg):
        logs.append(msg)
        logger.info(f"MAC-PORT: {msg}")
        if progress_callback:
            progress_callback(msg)

    try:
        from netbox_client import NetBoxClient
        from src.core.config import get_config
        nb = NetBoxClient()

        log(f"Leaf threshold: {leaf_threshold} MAC(s) per port")
        if cred_sets:
            log(f"Switch SSH: {len(cred_sets)} credential set(s) provided, tried in order per device")
        else:
            log("Switch SSH: using credentials from .env")
        if CREATE_MISSING_IFACE:
            log("MAC_CREATE_MISSING_IFACE=on: missing interfaces will be created")

        device_entries = {}
        scanned_names = set()

        log("Scanning OLTs from config...")
        for olt in get_config().get_enabled_olts():
            nb_name = _resolve_olt_device_name(nb, olt, log)
            if not nb_name:
                stats["devices_failed"] += 1
                failures.append({"device": f"OLT {olt.id}", "ip": olt.host, "reason": "no matching NetBox device"})
                log(f"  SKIP OLT {olt.id} ({olt.host}): no matching NetBox device")
                continue
            try:
                entries = get_olt_mac_entries(olt, log=log)
                device_entries[nb_name] = device_entries.get(nb_name, []) + entries
                scanned_names.add(nb_name)
                stats["devices_scanned"] += 1
                log(f"  OLT {olt.id} -> {nb_name}: {len(entries)} ONU MAC entries")
            except Exception as e:
                stats["devices_failed"] += 1
                failures.append({"device": f"OLT {olt.id}", "ip": olt.host, "reason": str(e)})
                log(f"  FAIL OLT {olt.id} ({olt.host}): {e}")

        log(f"Listing NetBox devices in mgmt prefix {MAC_MGMT_PREFIX}...")
        prefix_devices = nb.list_devices_in_prefix(MAC_MGMT_PREFIX)
        log(f"  {len(prefix_devices)} device(s) have an IP in {MAC_MGMT_PREFIX}")

        primary_devices = nb.list_devices_with_primary_ip()
        log(f"  {len(primary_devices)} device(s) have a primary IP")

        extra_devices = load_extra_devices()
        if extra_devices:
            log(f"  {len(extra_devices)} extra device(s) from {EXTRA_DEVICES_FILE}")

        seen_ips = set()
        seen_names = set()
        all_devices = []
        for d in prefix_devices + primary_devices + extra_devices:
            ip = d.get("primary_ip")
            nm = d.get("name")
            if not ip or ip in seen_ips or nm in seen_names:
                continue
            seen_ips.add(ip)
            seen_names.add(nm)
            all_devices.append(d)
        log(f"Total unique devices to consider: {len(all_devices)}")

        for dev in all_devices:
            host = dev["primary_ip"]
            name = dev["name"]
            if name in scanned_names:
                continue
            vendor = dev.get("vendor") or classify_vendor(dev["manufacturer"], dev["platform"], name)
            if vendor == "unknown":
                mfr = nb.get_device_manufacturer(name)
                if mfr:
                    vendor = classify_vendor(mfr, "", name)

            if vendor == "olt":
                continue
            if vendor not in NETMIKO_DEVICE_TYPES and vendor != "mikrotik":
                stats["devices_skipped"] += 1
                log(f"  SKIP {name} ({host}): unsupported vendor '{dev.get('manufacturer') or vendor}'")
                continue

            user_pass_sets = cred_sets if cred_sets else [_creds_for(vendor, None, None)]
            user_pass_sets = [(u, p) for (u, p) in user_pass_sets if u and p]
            if not user_pass_sets:
                stats["devices_failed"] += 1
                failures.append({"device": name, "ip": host, "reason": "no SSH credentials"})
                log(f"  FAIL {name} ({host}): no SSH credentials (enter login/password on the button or set .env)")
                continue

            entries = None
            reason = None
            unreachable = False
            for idx, (u, p) in enumerate(user_pass_sets):
                try:
                    entries = get_switch_entries(vendor, host, u, p)
                    if len(user_pass_sets) > 1:
                        log(f"  {name}: authenticated with credential set #{idx + 1} (user '{u}')")
                    break
                except Exception as e:
                    kind = _classify_ssh_error(e)
                    first = str(e).strip().splitlines()[0].strip() if str(e).strip() else ""
                    reason = first or e.__class__.__name__
                    if kind == "auth":
                        continue
                    unreachable = True
                    break

            if entries is None:
                stats["devices_failed"] += 1
                if not unreachable and len(user_pass_sets) > 1:
                    reason = f"authentication failed for all {len(user_pass_sets)} credential set(s)"
                failures.append({"device": name, "ip": host, "vendor": vendor, "reason": reason})
                log(f"  FAIL {name} ({vendor}, {host}): {reason}")
                continue

            device_entries[name] = device_entries.get(name, []) + entries
            scanned_names.add(name)
            stats["devices_scanned"] += 1
            log(f"  {name} ({vendor}, {host}): {len(entries)} MAC entries")

        log("Building MAC index...")
        index = build_mac_index(device_entries)

        client_ips = list(nb.iter_ips_with_mac())
        client_macs = set()
        for ip_obj in client_ips:
            nm = normalize_mac(ip_obj["mac"])
            if nm:
                client_macs.add(nm)
        log(f"Client IPs with a MAC in NetBox: {len(client_ips)} ({len(client_macs)} unique MACs)")

        log("Per-device overlap with client MACs:")
        for hostname, entries in device_entries.items():
            dev_macs = set(m for m, _ in entries)
            overlap = len(dev_macs & client_macs)
            log(f"  {hostname}: {len(dev_macs)} unique MACs, {overlap} match client IPs")

        stats["no_leaf_unseen"] = 0
        stats["no_leaf_trunk"] = 0
        sample_unseen = 0
        sample_trunk = 0

        log("Assigning IPs to leaf interfaces...")
        seen_addresses = set()
        dup_addresses = 0
        for ip_obj in client_ips:
            address = ip_obj["address"]
            if address in seen_addresses:
                dup_addresses += 1
                continue
            seen_addresses.add(address)
            stats["total"] += 1
            mac = normalize_mac(ip_obj["mac"])
            if not mac:
                continue

            candidates = index.get(mac)
            if not candidates:
                stats["no_leaf"] += 1
                stats["no_leaf_unseen"] += 1
                if sample_unseen < 12:
                    sample_unseen += 1
                    log(f"  [unseen] {address} mac {mac}: not found on any scanned device")
                continue

            leaf = pick_leaf(candidates, leaf_threshold)
            if not leaf:
                stats["no_leaf"] += 1
                stats["no_leaf_trunk"] += 1
                if sample_trunk < 12:
                    sample_trunk += 1
                    where = ", ".join(f"{c['hostname']}/{c['port']}(cnt={c['count']})" for c in candidates[:3])
                    log(f"  [trunk] {address} mac {mac}: seen only on non-leaf ports (>{leaf_threshold}): {where}")
                continue

            device = nb.find_device_by_name_exact(leaf["hostname"])
            if not device:
                stats["dev_missing"] += 1
                log(f"  {address}: device '{leaf['hostname']}' not in NetBox")
                continue

            iface = nb.find_interface(device["id"], leaf["port"])
            if not iface:
                if CREATE_MISSING_IFACE:
                    created = nb.create_interface(device["id"], leaf["port"], description="auto: MAC sync")
                    if created.get("success"):
                        iface = {"id": created["interface_id"], "name": leaf["port"]}
                        log(f"  {address}: created interface '{leaf['port']}' on {leaf['hostname']}")
                    else:
                        stats["iface_missing"] += 1
                        log(f"  {address}: could not create '{leaf['port']}' on {leaf['hostname']}: {created.get('error')}")
                        continue
                else:
                    stats["iface_missing"] += 1
                    log(f"  {address}: no interface '{leaf['port']}' on {leaf['hostname']} (report only)")
                    continue

            if ip_obj["assigned_object_id"] == iface["id"]:
                stats["already_ok"] += 1
                continue

            res = nb.assign_ip_to_interface(ip_obj["id"], iface["id"])
            if res.get("success"):
                stats["assigned"] += 1
                log(f"  {address} -> {leaf['hostname']} / {leaf['port']}")
            else:
                stats["errors"] += 1
                log(f"  ERROR {address}: {res.get('error')}")

        if failures:
            log(f"--- {len(failures)} device(s) could not be scanned ---")
            for f in failures:
                log(f"  ! {f['device']} ({f.get('ip','')}): {f['reason']}")

        if dup_addresses:
            log(f"Skipped {dup_addresses} duplicate IP object(s) in NetBox (same address listed more than once)")

        log(
            "no_leaf breakdown: unseen={no_leaf_unseen} (MAC nowhere on scanned gear) "
            "trunk={no_leaf_trunk} (seen only on ports with > {thr} MACs)".format(thr=leaf_threshold, **stats)
        )
        log(
            "Done. assigned={assigned} already_ok={already_ok} no_leaf={no_leaf} "
            "iface_missing={iface_missing} dev_missing={dev_missing} errors={errors} "
            "| scanned={devices_scanned} failed={devices_failed} skipped={devices_skipped}".format(**stats)
        )
        return {"success": True, "stats": stats, "logs": logs, "failures": failures}

    except Exception as e:
        logger.error(f"MAC-PORT sync error: {e}")
        logs.append(f"Error: {str(e)}")
        return {"success": False, "stats": stats, "logs": logs, "failures": failures, "error": str(e)}
