"""
Orchestrator: connects SSH data from Cisco switches with NetBox API.
Implements the full automation workflow.
"""

from dataclasses import dataclass, field, asdict
from ssh_connector import CiscoSSH, PortInfo, CDPNeighbor
from netbox_client import NetBoxClient


@dataclass
class PortAction:
    """Represents a planned action for a port."""
    port_name: str
    description: str = ""
    mode: str = ""
    trunk_vlans: list = field(default_factory=list)
    access_vlan: str = ""
    native_vlan: str = ""
    cdp_neighbor: str = ""
    cdp_remote_port: str = ""
    netbox_interface_id: int = 0
    netbox_neighbor_device_id: int = 0
    netbox_neighbor_interface_id: int = 0
    cable_exists: bool = False
    status: str = "pending"


@dataclass
class ScanResult:
    """Full scan result for a device."""
    host: str
    hostname: str = ""
    device_id: int = 0
    device_name: str = ""
    ports: list = field(default_factory=list)
    errors: list = field(default_factory=list)


class Orchestrator:
    def __init__(self, ssh_username: str = None, ssh_password: str = None):
        self.nb = NetBoxClient()
        self.ssh_username = ssh_username
        self.ssh_password = ssh_password

    def scan_device(self, host: str, progress_callback=None) -> ScanResult:
        """
        Phase 1: Scan - collect all data from SSH and NetBox.
        """
        result = ScanResult(host=host)

        def log(msg):
            if progress_callback:
                progress_callback(msg)

        # Step 1: Find device in NetBox
        log(f"🔍 Searching NetBox for {host}...")
        nb_device = self.nb.find_device_by_ip(host)
        if not nb_device:
            result.errors.append(f"Device {host} not found in NetBox")
            log(f"⚠️  Device not found in NetBox.")
        else:
            result.device_id = nb_device["id"]
            result.device_name = nb_device["name"]
            log(f"✅ Found device: {nb_device['name']} (ID: {nb_device['id']})")

        # Step 2: Connect SSH
        log(f"🔌 Connecting SSH to {host}...")
        ssh = CiscoSSH(host, username=self.ssh_username, password=self.ssh_password)
        conn_result = ssh.connect()

        if not conn_result["success"]:
            result.errors.append(f"SSH: {conn_result['error']}")
            log(f"❌ SSH failed: {conn_result['error']}")
            return result

        result.hostname = conn_result["hostname"]
        log(f"✅ SSH connected: {result.hostname}")

            # Update device name in NetBox to match real hostname
        if result.device_id and result.hostname:
            current_name = result.device_name
            if current_name != result.hostname:
                log(f"📛 Renaming device in NetBox: {current_name} → {result.hostname}")
                rename_res = self.nb.update_device_name(result.device_id, result.hostname)
                if rename_res["success"]:
                    result.device_name = result.hostname
                    log(f"  ✅ Device renamed to {result.hostname}")
                else:
                    log(f"  ❌ Rename failed: {rename_res['error']}")

        try:
            # Step 3: Get connected ports
            log("📡 Getting connected ports...")
            connected_ports = ssh.get_connected_ports()
            log(f"✅ Found {len(connected_ports)} connected ports")

            # Step 4: Get CDP neighbors
            log("🔗 Getting CDP neighbors...")
            cdp_neighbors = ssh.get_cdp_neighbors_detail()
            cdp_map = {}
            for n in cdp_neighbors:
                cdp_map[n.local_port] = n
            log(f"✅ Found {len(cdp_neighbors)} CDP neighbors")

            # Step 5: For each connected port, get config and plan actions
            for i, port in enumerate(connected_ports):
                log(f"📋 [{i+1}/{len(connected_ports)}] Analyzing {port.name}...")

                port_config = ssh.get_port_config(port.name)

                action = PortAction(
                    port_name=port.name,
                    description=port_config.description or port.description,
                    mode=port_config.mode or ("trunk" if port.vlan == "trunk" else "access"),
                    trunk_vlans=port_config.trunk_vlans,
                    access_vlan=port_config.vlan or port.vlan,
                    native_vlan=port_config.native_vlan,
                )

                # CDP neighbor info
                cdp = cdp_map.get(port.name)
                if cdp:
                    action.cdp_neighbor = cdp.remote_device
                    action.cdp_remote_port = cdp.remote_port

                # Find NetBox interface IDs
                if result.device_id:
                    nb_iface = self.nb.find_interface(result.device_id, port.name)
                    if nb_iface:
                        action.netbox_interface_id = nb_iface["id"]
                        action.cable_exists = self.nb.check_cable_exists(nb_iface["id"])

                    # Find neighbor device and interface in NetBox
                    if cdp and cdp.remote_device:
                        nb_neighbor = self.nb.find_device_by_name(cdp.remote_device)
                        if nb_neighbor:
                            action.netbox_neighbor_device_id = nb_neighbor["id"]
                            nb_remote_iface = self.nb.find_interface(
                                nb_neighbor["id"], cdp.remote_port
                            )
                            if nb_remote_iface:
                                action.netbox_neighbor_interface_id = nb_remote_iface["id"]

                result.ports.append(action)

        finally:
            ssh.disconnect()
            log("🔌 SSH disconnected")

        log(f"✅ Scan complete: {len(result.ports)} ports analyzed")
        return result

    def apply_actions(self, scan_result: ScanResult, selected_ports: list[str] = None,
                      progress_callback=None) -> list[dict]:
        """
        Phase 2: Apply - push changes to NetBox for selected ports.
        Includes: Step 1 (VLAN interface + IP), Step 2 (port config), Step 3 (cables).
        """
        results = []

        def log(msg):
            if progress_callback:
                progress_callback(msg)

        # ════════════════════════════════════════════════════════════
        # STEP 1: Create VLAN 200 interface + assign IP address
        # ════════════════════════════════════════════════════════════
        if scan_result.device_id and scan_result.host:
            log("🌐 Step 1: Setting up VLAN 200 management interface...")

            # Check if Vlan200 interface already exists
            vlan_iface = self.nb.find_interface(scan_result.device_id, "Vlan200")
            if not vlan_iface:
                vlan_iface = self.nb.find_interface(scan_result.device_id, "Vlan 200")

            if vlan_iface:
                log(f"  ℹ️  Vlan200 interface already exists (ID: {vlan_iface['id']})")
            else:
                # Find VLAN 200 in NetBox
                vlan200 = self.nb.find_vlan_by_vid(200)
                if vlan200:
                    # Create Vlan200 interface with mode=access, untagged_vlan=200
                    create_res = self.nb.create_vlan_interface(
                        device_id=scan_result.device_id,
                        vlan_vid=200,
                        ip_address=f"{scan_result.host}/24",
                        untagged_vlan_id=vlan200["id"],
                    )
                    if create_res["success"]:
                        log(f"  ✅ Created Vlan200 interface")
                        vlan_iface = {"id": create_res["interface_id"]}
                    else:
                        log(f"  ❌ Failed to create Vlan200: {create_res['error']}")
                else:
                    log("  ⚠️  VLAN 200 not found in NetBox, skipping VLAN interface creation")

            # Check/create IP address on Vlan200
            if vlan_iface:
                ip_addr = f"{scan_result.host}/24"
                ip_exists = self.nb.check_ip_on_interface(vlan_iface["id"], ip_addr)
                if ip_exists:
                    log(f"  ℹ️  IP {ip_addr} already assigned")
                else:
                    ip_res = self.nb.create_ip_address(ip_addr, interface_id=vlan_iface["id"])
                    if ip_res["success"]:
                        log(f"  ✅ Assigned IP {ip_addr} to Vlan200")
                    else:
                        log(f"  ❌ Failed to assign IP: {ip_res['error']}")

        # ════════════════════════════════════════════════════════════
        # STEP 2 & 3: Update ports + create cables
        # ════════════════════════════════════════════════════════════
        for action in scan_result.ports:
            if selected_ports and action.port_name not in selected_ports:
                continue

            port_result = {"port": action.port_name, "steps": []}

            if not action.netbox_interface_id:
                port_result["steps"].append({
                    "action": "skip",
                    "reason": "Interface not found in NetBox"
                })
                results.append(port_result)
                continue

            # ── Step 2: Update interface mode, VLANs, description ──
            log(f"📝 Updating {action.port_name}...")
            update_data = {}

            if action.mode == "trunk":
                update_data["mode"] = "tagged"
                if action.trunk_vlans:
                    vlan_ids = self.nb.get_vlan_ids_for_vids(action.trunk_vlans)
                    update_data["tagged_vlans"] = vlan_ids
            elif action.mode == "access":
                update_data["mode"] = "access"
                if action.access_vlan and action.access_vlan.isdigit():
                    vlan = self.nb.find_vlan_by_vid(int(action.access_vlan))
                    if vlan:
                        update_data["untagged_vlan"] = vlan["id"]

            if action.description:
                update_data["description"] = action.description

            if update_data:
                res = self.nb.update_interface(action.netbox_interface_id, update_data)
                port_result["steps"].append({
                    "action": "update_interface",
                    "data": update_data,
                    "result": res,
                })
                if res["success"]:
                    log(f"  ✅ Interface updated")
                else:
                    log(f"  ❌ Update failed: {res['error']}")

            # ── Step 3: Create cable if CDP neighbor found ──
            if (action.netbox_interface_id and
                action.netbox_neighbor_interface_id):

                # Delete existing cables if any (overwrite mode)
                if action.cable_exists:
                    self.nb.delete_cable(action.netbox_interface_id)
                    log(f"  🔄 Removed old cable on {action.port_name}")
                # Also check B side
                if self.nb.check_cable_exists(action.netbox_neighbor_interface_id):
                    self.nb.delete_cable(action.netbox_neighbor_interface_id)
                    log(f"  🔄 Removed old cable on {action.cdp_neighbor} {action.cdp_remote_port}")

                log(f"  🔗 Creating cable: {action.port_name} ↔ {action.cdp_neighbor} {action.cdp_remote_port}")
                cable_res = self.nb.create_cable(
                    action.netbox_interface_id,
                    action.netbox_neighbor_interface_id,
                    cable_type="cat6",
                )
                port_result["steps"].append({
                    "action": "create_cable",
                    "result": cable_res,
                })
                if cable_res["success"]:
                    log(f"  ✅ Cable created (CAT6)")
                else:
                    log(f"  ❌ Cable failed: {cable_res['error']}")
            elif action.cdp_neighbor and not action.netbox_neighbor_interface_id:
                log(f"  ⚠️  CDP neighbor {action.cdp_neighbor} port {action.cdp_remote_port} not found in NetBox - cable skipped")

            results.append(port_result)

        return results
