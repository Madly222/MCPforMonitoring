"""
NetBox API client for automating interface configuration.
Handles: device lookup, VLAN assignment, interface updates, cable creation.
"""

import os
import pynetbox
from dataclasses import dataclass


@dataclass
class NetBoxConfig:
    url: str
    token: str


class NetBoxClient:
    def __init__(self, config: NetBoxConfig = None):
        if config is None:
            config = NetBoxConfig(
                url=os.getenv("NETBOX_URL", "http://172.22.22.57/"),
                token=os.getenv("NETBOX_TOKEN", ""),
            )
        self.nb = pynetbox.api(config.url, token=config.token)
        # Disable SSL verification for internal instances
        import requests
        session = requests.Session()
        session.verify = False
        self.nb.http_session = session

    # ── Device Operations ──────────────────────────────────────────

    def find_device_by_ip(self, ip: str) -> dict | None:
        """Find device by its primary or any assigned IP."""
        ip_results = self.nb.ipam.ip_addresses.filter(address=ip)
        ip_obj = next(iter(ip_results), None)
        if ip_obj and ip_obj.assigned_object:
            device = ip_obj.assigned_object.device if hasattr(ip_obj.assigned_object, 'device') else None
            if device:
                return {
                    "id": device.id,
                    "name": str(device),
                    "ip": ip,
                    "device_type": str(device.device_type) if device.device_type else "",
                    "site": str(device.site) if device.site else "",
                }

        # Fallback: search by name in IP
        devices = self.nb.dcim.devices.filter(name__ic=ip)
        for d in devices:
            return {"id": d.id, "name": str(d), "ip": ip}

        return None

    def find_device_by_name(self, name: str) -> dict | None:
        """Find device by hostname with fuzzy matching.
        
        CDP gives hostnames like CIS-NX3K-SW36-N.TST but NetBox may have
        CIS-NX3K-SW36-ECB. We extract the core identifier (e.g. SW36)
        and model prefix (e.g. NX3K) to find the right device.
        """
        import re

        # 1. Try exact match first
        device = self.nb.dcim.devices.get(name=name)
        if device:
            return self._device_to_dict(device)

        # 2. Try partial match — search by key parts of the name
        # Extract switch number pattern like SW36, SW19, SW122
        sw_match = re.search(r'(SW\d+)', name, re.IGNORECASE)
        if sw_match:
            sw_num = sw_match.group(1)
            
            # Also extract model prefix like NX3K, 4948, 2950, 3750
            model_match = re.search(r'(NX\d+K|[A-Z]*\d{4})', name, re.IGNORECASE)
            
            # Search NetBox with switch number
            devices = list(self.nb.dcim.devices.filter(name__ic=sw_num))
            
            if len(devices) == 1:
                return self._device_to_dict(devices[0])
            elif len(devices) > 1 and model_match:
                # Multiple results — narrow down by model
                model = model_match.group(1)
                for d in devices:
                    if model.lower() in str(d.name).lower():
                        return self._device_to_dict(d)
                # If still no exact model match, return first
                return self._device_to_dict(devices[0])
            elif devices:
                return self._device_to_dict(devices[0])

        # 3. Try broader search with first meaningful part
        parts = name.replace('.', '-').split('-')
        for i in range(len(parts), 1, -1):
            search_term = '-'.join(parts[:i])
            devices = list(self.nb.dcim.devices.filter(name__ic=search_term))
            if len(devices) == 1:
                return self._device_to_dict(devices[0])

        return None

    def _device_to_dict(self, device) -> dict:
        """Convert pynetbox device object to dict."""
        primary_ip = str(device.primary_ip).split('/')[0] if device.primary_ip else ""
        return {
            "id": device.id,
            "name": str(device),
            "ip": primary_ip,
            "device_type": str(device.device_type) if device.device_type else "",
            "site": str(device.site) if device.site else "",
        }

    def update_device_name(self, device_id: int, new_name: str) -> dict:
        """Update device name (hostname) in NetBox."""
        try:
            device = self.nb.dcim.devices.get(device_id)
            if not device:
                return {"success": False, "error": f"Device {device_id} not found"}
            device.update({"name": new_name})
            return {"success": True, "name": new_name}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Interface Operations ───────────────────────────────────────

    def get_device_interfaces(self, device_id: int) -> list[dict]:
        """Get all interfaces for a device."""
        interfaces = self.nb.dcim.interfaces.filter(device_id=device_id)
        result = []
        for iface in interfaces:
            result.append({
                "id": iface.id,
                "name": str(iface.name),
                "type": str(iface.type) if iface.type else "",
                "description": str(iface.description) if iface.description else "",
                "mode": str(iface.mode) if iface.mode else "",
                "enabled": iface.enabled,
                "tagged_vlans": [v.vid for v in iface.tagged_vlans] if iface.tagged_vlans else [],
                "untagged_vlan": iface.untagged_vlan.vid if iface.untagged_vlan else None,
                "cable": iface.cable.id if iface.cable else None,
            })
        return result

    def _generate_interface_name_variants(self, name: str) -> list[str]:
        """Generate possible NetBox name variants for a Cisco interface name."""
        import re
        variants = [name]

        # Fa1/0/1 -> Fa1/01, Fa1/0/10 -> Fa1/010
        m = re.match(r'^(Fa|Gi|Te)(\d+)/0/(\d+)$', name)
        if m:
            prefix, stack, port = m.group(1), m.group(2), m.group(3)
            variants.append(f"{prefix}{stack}/0{port}")
            variants.append(f"{prefix}{stack}/0/{port}")
            # Also try FastEthernet/GigabitEthernet full names
            full = {"Fa": "FastEthernet", "Gi": "GigabitEthernet", "Te": "TenGigabitEthernet"}
            if prefix in full:
                variants.append(f"{full[prefix]}{stack}/0/{port}")
                variants.append(f"{full[prefix]}{stack}/0{port}")

        # Fa0/1 -> FastEthernet0/1, Gi0/1 -> GigabitEthernet0/1
        m2 = re.match(r'^(Fa|Gi|Te)(.+)$', name)
        if m2:
            full = {"Fa": "FastEthernet", "Gi": "GigabitEthernet", "Te": "TenGigabitEthernet"}
            if m2.group(1) in full:
                variants.append(f"{full[m2.group(1)]}{m2.group(2)}")

        # Reverse: FastEthernet -> Fa, GigabitEthernet -> Gi
        for long, short in [("FastEthernet", "Fa"), ("GigabitEthernet", "Gi"), ("TenGigabitEthernet", "Te")]:
            if name.startswith(long):
                variants.append(name.replace(long, short, 1))

        # mgmt0, Management, etc
        if name.lower().startswith("mgmt") or name.lower().startswith("management"):
            variants.extend(["mgmt0", "Mgmt0", "MGMT", "Management0", "management0", "mgmt 0", name])

        # [Gi]1/46 format — NetBox uses brackets around prefix
        m3 = re.match(r'^(Fa|Gi|Te)(.+)$', name)
        if m3:
            prefix = m3.group(1)
            rest = m3.group(2)
            variants.append(f"[{prefix}]{rest}")

        # Eth variants — Nexus uses Ethernet, NetBox might have Eth
        if name.lower().startswith("fa") and "/" not in name:
            # Fa1 -> could be Eth1/1, [Gi]1/1, FastEthernet1, etc.
            num_match = re.search(r'(\d+)$', name)
            if num_match:
                num = num_match.group(1)
                variants.extend([
                    f"Eth1/{num}", f"Ethernet1/{num}", f"eth1/{num}",
                    f"[Gi]1/{num}", f"[Fa]1/{num}",
                    f"Gi1/{num}", f"Fa1/{num}",
                    f"FastEthernet{num}", f"FastEthernet0/{num}",
                    f"Fa0/{num}",
                ])
        
        # GigabitEthernet without slash — Gi1 -> [Gi]1/1
        if re.match(r'^(Gi|GigabitEthernet)(\d+)$', name):
            num_match = re.search(r'(\d+)$', name)
            if num_match:
                num = num_match.group(1)
                variants.extend([f"[Gi]1/{num}", f"Gi1/{num}", f"GigabitEthernet1/{num}"])

        # Reverse: [Gi]1/46 -> Gi1/46
        bracket_match = re.match(r'^\[(\w+)\](.+)$', name)
        if bracket_match:
            variants.append(f"{bracket_match.group(1)}{bracket_match.group(2)}")

        return list(dict.fromkeys(variants))  # dedupe, preserve order

    def find_interface(self, device_id: int, interface_name: str) -> dict | None:
        """Find specific interface on a device, trying multiple name variants."""
        variants = self._generate_interface_name_variants(interface_name)

        for variant in variants:
            interfaces = self.nb.dcim.interfaces.filter(
                device_id=device_id,
                name=variant
            )
            for iface in interfaces:
                return {
                    "id": iface.id,
                    "name": str(iface.name),
                    "description": str(iface.description) if iface.description else "",
                    "mode": str(iface.mode) if iface.mode else "",
                }
        return None

    def update_interface(self, interface_id: int, data: dict) -> dict:
        """
        Update interface in NetBox. Always overwrites existing values.
        """
        iface = self.nb.dcim.interfaces.get(interface_id)
        if not iface:
            return {"success": False, "error": f"Interface {interface_id} not found"}

        update_data = {}

        if "mode" in data:
            mode_map = {
                "access": "access",
                "trunk": "tagged",
                "tagged": "tagged",
            }
            update_data["mode"] = mode_map.get(data["mode"], data["mode"])

        if "tagged_vlans" in data:
            update_data["tagged_vlans"] = data["tagged_vlans"]

        if "untagged_vlan" in data:
            update_data["untagged_vlan"] = data["untagged_vlan"]

        if "description" in data:
            update_data["description"] = data["description"]

        try:
            iface.update(update_data)
            return {"success": True, "interface": str(iface.name)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── VLAN Operations ────────────────────────────────────────────

    def get_vlans(self, site: str = None) -> list[dict]:
        """Get all VLANs, optionally filtered by site."""
        params = {}
        if site:
            params["site"] = site
        vlans = self.nb.ipam.vlans.all() if not params else self.nb.ipam.vlans.filter(**params)
        return [{"id": v.id, "vid": v.vid, "name": str(v.name)} for v in vlans]

    def find_vlan_by_vid(self, vid: int, site: str = None) -> dict | None:
        """Find VLAN by its VID number."""
        params = {"vid": vid}
        if site:
            params["site"] = site
        vlans = self.nb.ipam.vlans.filter(**params)
        for v in vlans:
            return {"id": v.id, "vid": v.vid, "name": str(v.name)}
        return None

    def get_vlan_ids_for_vids(self, vids: list[int]) -> list[int]:
        """Convert list of VLAN VIDs to NetBox VLAN object IDs."""
        nb_ids = []
        for vid in vids:
            vlan = self.find_vlan_by_vid(vid)
            if vlan:
                nb_ids.append(vlan["id"])
        return nb_ids

    # ── IP Address Operations ──────────────────────────────────────

    def create_ip_address(self, address: str, interface_id: int = None) -> dict:
        """Create IP address and optionally assign to interface."""
        data = {"address": address}
        if interface_id:
            data["assigned_object_type"] = "dcim.interface"
            data["assigned_object_id"] = interface_id

        try:
            ip = self.nb.ipam.ip_addresses.create(data)
            return {"success": True, "id": ip.id, "address": str(ip.address)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Cable Operations ───────────────────────────────────────────

    def create_cable(self, interface_a_id: int, interface_b_id: int, cable_type: str = "cat6") -> dict:
        """Create cable connection between two interfaces."""
        try:
            cable = self.nb.dcim.cables.create({
                "termination_a_type": "dcim.interface",
                "termination_a_id": interface_a_id,
                "termination_b_type": "dcim.interface",
                "termination_b_id": interface_b_id,
                "status": "connected",
                "type": cable_type,
            })
            return {"success": True, "cable_id": cable.id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def check_cable_exists(self, interface_id: int) -> bool:
        """Check if interface already has a cable."""
        iface = self.nb.dcim.interfaces.get(interface_id)
        return iface.cable is not None if iface else False

    def delete_cable(self, interface_id: int) -> bool:
        """Delete existing cable on an interface."""
        try:
            iface = self.nb.dcim.interfaces.get(interface_id)
            if iface and iface.cable:
                cable = self.nb.dcim.cables.get(iface.cable.id)
                if cable:
                    cable.delete()
                    return True
        except:
            pass
        return False

    # ── VLAN Interface (SVI) Operations ────────────────────────────

    def create_vlan_interface(self, device_id: int, vlan_vid: int, ip_address: str, untagged_vlan_id: int = None) -> dict:
        """Create VLAN interface (SVI) on device with mode=access, untagged VLAN, and assign IP."""
        try:
            iface_data = {
                "device": device_id,
                "name": f"Vlan{vlan_vid}",
                "type": "virtual",
                "mode": "access",
                "description": f"VLAN {vlan_vid} Management",
            }
            if untagged_vlan_id:
                iface_data["untagged_vlan"] = untagged_vlan_id

            iface = self.nb.dcim.interfaces.create(iface_data)

            # Assign IP
            if ip_address:
                self.create_ip_address(ip_address, interface_id=iface.id)

            return {"success": True, "interface_id": iface.id, "name": f"Vlan{vlan_vid}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def check_ip_on_interface(self, interface_id: int, address: str) -> bool:
        """Check if IP is already assigned to an interface."""
        try:
            ips = self.nb.ipam.ip_addresses.filter(interface_id=interface_id)
            for ip in ips:
                if str(ip.address).split('/')[0] == address.split('/')[0]:
                    return True
        except:
            pass
        return False

    def reassign_ip(self, address: str, interface_id: int) -> dict:
        """Delete existing IP and create fresh assignment."""
        try:
            existing = self.nb.ipam.ip_addresses.filter(address=address)
            for ip in existing:
                ip.delete()
            return self.create_ip_address(address, interface_id=interface_id)
        except Exception as e:
            return {"success": False, "error": str(e)}


    def create_device(self, name: str, device_type_id: int = None, site_id: int = None,
                      role_id: int = None, serial: str = None) -> dict:
        """Create a new device in NetBox."""
        try:
            if not device_type_id:
                device_types = list(self.nb.dcim.device_types.all())
                if device_types:
                    device_type_id = device_types[0].id
                else:
                    return {"success": False, "error": "No device types found"}

            if not site_id:
                sites = list(self.nb.dcim.sites.all())
                if sites:
                    site_id = sites[0].id
                else:
                    return {"success": False, "error": "No sites found"}

            if not role_id:
                roles = list(self.nb.dcim.device_roles.all())
                if roles:
                    role_id = roles[0].id
                else:
                    return {"success": False, "error": "No device roles found"}

            data = {
                "name": name,
                "device_type": device_type_id,
                "site": site_id,
                "device_role": role_id,
                "status": "active",
            }
            if serial:
                data["serial"] = serial

            device = self.nb.dcim.devices.create(data)
            return {"success": True, "device_id": device.id, "device": {"id": device.id, "name": str(device)}}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def find_or_create_device_type(self, model: str, manufacturer: str = "Cisco") -> dict:
        """Find or create device type by model name."""
        try:
            manufacturers = list(self.nb.dcim.manufacturers.filter(name=manufacturer))
            if manufacturers:
                manufacturer_id = manufacturers[0].id
            else:
                mfr = self.nb.dcim.manufacturers.create({"name": manufacturer, "slug": manufacturer.lower()})
                manufacturer_id = mfr.id

            device_types = list(self.nb.dcim.device_types.filter(model=model))
            if device_types:
                return {"success": True, "device_type_id": device_types[0].id}

            slug = model.lower().replace(" ", "-").replace("/", "-")
            dt = self.nb.dcim.device_types.create({
                "manufacturer": manufacturer_id,
                "model": model,
                "slug": slug,
            })
            return {"success": True, "device_type_id": dt.id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def find_ip_address(self, address: str) -> dict | None:
        """Find IP address in NetBox."""
        try:
            ips = list(self.nb.ipam.ip_addresses.filter(address=address))
            if ips:
                return {"id": ips[0].id, "address": str(ips[0].address)}
            return None
        except:
            return None

    def find_device_by_name_exact(self, name: str) -> dict | None:
        """Find device by EXACT hostname match."""
        try:
            device = self.nb.dcim.devices.get(name=name)
            if device:
                return self._device_to_dict(device)
            return None
        except:
            return None

    def create_interface(self, device_id: int, name: str, description: str = "", mtu: int = None) -> dict:
        """Create interface on device."""
        try:
            # Determine interface type based on name
            iface_type = "other"
            name_lower = name.lower()
            if "gigabit" in name_lower or name_lower.startswith("gi"):
                iface_type = "1000base-t"
            elif "fastethernet" in name_lower or name_lower.startswith("fa"):
                iface_type = "100base-tx"
            elif "tunnel" in name_lower:
                iface_type = "virtual"
            elif "vlan" in name_lower:
                iface_type = "virtual"
            elif "loopback" in name_lower:
                iface_type = "virtual"
            
            data = {
                "device": device_id,
                "name": name,
                "type": iface_type,
            }
            if description:
                data["description"] = description
            if mtu:
                data["mtu"] = mtu
            
            iface = self.nb.dcim.interfaces.create(data)
            return {"success": True, "interface_id": iface.id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── MAC → Port assignment ──────────────────────────────────────

    def list_devices_with_primary_ip(self) -> list[dict]:
        """List active devices that have a primary IP, with vendor hints."""
        result = []
        for d in self.nb.dcim.devices.filter(has_primary_ip=True):
            primary_ip = None
            if d.primary_ip:
                primary_ip = str(d.primary_ip.address).split("/")[0]
            manufacturer = ""
            try:
                if d.device_type and d.device_type.manufacturer:
                    manufacturer = str(d.device_type.manufacturer)
            except Exception:
                pass
            platform = str(d.platform) if d.platform else ""
            result.append({
                "id": d.id,
                "name": str(d.name),
                "primary_ip": primary_ip,
                "manufacturer": manufacturer,
                "platform": platform,
            })
        return result

    def iter_ips_with_mac(self, mac_field: str = "MAC"):
        """Yield {id, address, mac} for every IP that has the MAC custom field set."""
        for ip in self.nb.ipam.ip_addresses.all():
            cf = ip.custom_fields or {}
            mac = cf.get(mac_field)
            if not mac:
                continue
            assigned = None
            if ip.assigned_object_id:
                assigned = ip.assigned_object_id
            yield {
                "id": ip.id,
                "address": str(ip.address),
                "mac": mac,
                "assigned_object_id": assigned,
            }

    def assign_ip_to_interface(self, ip_id: int, interface_id: int) -> dict:
        """Point an existing IP at an interface, preserving custom fields and data."""
        try:
            ip = self.nb.ipam.ip_addresses.get(ip_id)
            if not ip:
                return {"success": False, "error": f"IP {ip_id} not found"}
            ip.assigned_object_type = "dcim.interface"
            ip.assigned_object_id = interface_id
            ip.save()
            return {"success": True, "id": ip_id, "interface_id": interface_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_devices_in_prefix(self, prefix: str) -> list[dict]:
        """List devices that have ANY IP inside a management prefix (not just primary)."""
        result = {}
        try:
            ips = self.nb.ipam.ip_addresses.filter(parent=prefix)
        except Exception:
            return []
        for ip in ips:
            try:
                if str(ip.assigned_object_type or "") != "dcim.interface":
                    continue
                ao = ip.assigned_object
                dev = getattr(ao, "device", None) if ao else None
                if not dev:
                    continue
                name = str(dev.name)
                addr = str(ip.address).split("/")[0]
                if name not in result:
                    result[name] = {"name": name, "primary_ip": addr, "manufacturer": "", "platform": ""}
            except Exception:
                continue
        return list(result.values())

    def get_device_manufacturer(self, name: str) -> str:
        """Return the manufacturer name for a device (empty string if unknown)."""
        try:
            dev = self.nb.dcim.devices.get(name=name)
            if dev and dev.device_type and dev.device_type.manufacturer:
                return str(dev.device_type.manufacturer)
        except Exception:
            pass
        return ""
