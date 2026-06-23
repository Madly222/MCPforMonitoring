"""
SSH Connector for Cisco switches via Netmiko.
Handles old IOS devices with legacy ciphers (diffie-hellman-group1-sha1).
"""

import re
import os
from dataclasses import dataclass, field
from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException


@dataclass
class PortInfo:
    name: str               # e.g. "Gi0/1"
    status: str             # "connected", "notconnect", etc.
    vlan: str               # access vlan or "trunk"
    speed: str = ""
    duplex: str = ""
    description: str = ""
    trunk_vlans: list = field(default_factory=list)
    mode: str = ""          # "access" or "trunk"
    native_vlan: str = ""


@dataclass
class CDPNeighbor:
    local_port: str         # e.g. "Gi0/1"
    remote_device: str      # e.g. "CIS-4948-SW122-OFFICE"
    remote_port: str        # e.g. "Gi1/31"
    platform: str = ""


class CiscoSSH:
    def __init__(self, host: str, username: str = None, password: str = None):
        self.host = host
        self.username = username or os.getenv("SSH_USERNAME", "sg")
        self.password = password or os.getenv("SSH_PASSWORD", "")
        self.connection = None

    def connect(self) -> dict:
        """Establish SSH connection with legacy cipher support."""
        device = {
            "device_type": "cisco_ios",
            "host": self.host,
            "username": self.username,
            "password": self.password,
            "timeout": 30,
            "auth_timeout": 30,
            "banner_timeout": 30,
            "conn_timeout": 30,
            "ssh_config_file": None,
            "disabled_algorithms": {},  # netmiko handles this
        }

        # For old Cisco IOS — force legacy algorithms
        ssh_connect_params = {
            "disabled_algorithms": {
                "pubkeys": ["rsa-sha2-256", "rsa-sha2-512"],
            },
            "transport_factory": None,
        }

        try:
            device["disabled_algorithms"] = {
                "pubkeys": ["rsa-sha2-256", "rsa-sha2-512"],
                "kex": [],
            }
            self.connection = ConnectHandler(**device)
            # Disable paging (--More--)
            self.connection.send_command("terminal length 0", expect_string=r"#")
            hostname = self.connection.find_prompt().replace("#", "").replace(">", "").strip()
            return {"success": True, "hostname": hostname}
        except NetmikoTimeoutException:
            return {"success": False, "error": f"Timeout connecting to {self.host}"}
        except NetmikoAuthenticationException:
            return {"success": False, "error": f"Authentication failed for {self.host}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def disconnect(self):
        if self.connection:
            self.connection.disconnect()

    def get_connected_ports(self) -> list[PortInfo]:
        """Get all ports with 'connected' status."""
        output = self.connection.send_command("show interfaces status")
        ports = []

        for line in output.splitlines():
            # Match lines like: Gi0/1    Description    connected  200   a-full  a-100  ...
            match = re.match(
                r'^(\S+)\s+(.*?)\s+(connected|notconnect|disabled|err-disabled|monitoring)\s+'
                r'(\S+)\s+(\S+)\s+(\S+)\s+(\S+)',
                line.strip()
            )
            if match and match.group(3) == "connected":
                port = PortInfo(
                    name=match.group(1),
                    description=match.group(2).strip(),
                    status="connected",
                    vlan=match.group(4),
                    duplex=match.group(5),
                    speed=match.group(6),
                )
                ports.append(port)

        return ports

    def get_port_config(self, interface: str) -> PortInfo:
        """Get detailed config for a specific interface."""
        output = self.connection.send_command(f"show running-config interface {interface}")

        port = PortInfo(name=interface, status="", vlan="")

        # Description
        desc_match = re.search(r'description\s+(.+)', output)
        if desc_match:
            port.description = desc_match.group(1).strip()

        # Switchport mode
        if "switchport mode trunk" in output:
            port.mode = "trunk"
        elif "switchport mode access" in output:
            port.mode = "access"

        # Trunk allowed VLANs
        trunk_match = re.search(r'switchport trunk allowed vlan\s+(.+)', output)
        if trunk_match:
            vlan_str = trunk_match.group(1).strip()
            port.trunk_vlans = self._parse_vlan_list(vlan_str)
            port.mode = "trunk"  # if trunk vlans exist, it's trunk

        # Access VLAN
        access_match = re.search(r'switchport access vlan\s+(\d+)', output)
        if access_match:
            port.vlan = access_match.group(1)

        # Native VLAN
        native_match = re.search(r'switchport trunk native vlan\s+(\d+)', output)
        if native_match:
            port.native_vlan = native_match.group(1)

        return port

    def get_cdp_neighbors(self) -> list[CDPNeighbor]:
        """Parse CDP neighbors, strip domain suffix."""
        output = self.connection.send_command("show cdp neighbors")
        neighbors = []

        lines = output.splitlines()
        data_started = False

        for line in lines:
            if "Device ID" in line:
                data_started = True
                continue
            if not data_started or not line.strip():
                continue

            # CDP neighbor lines can wrap — handle both single and multi-line
            # Format: Device ID  Local Intrfce  Holdtme  Capability  Platform  Port ID
            parts = line.split()
            if len(parts) >= 6:
                device_id = parts[0]
                # Strip domain (e.g. .rapidlink.local)
                device_name = device_id.split('.')[0]

                # Find local interface — typically like "Gig 0/1" or "Fas 0/1"
                local_port = self._find_interface_in_parts(parts, 1)
                remote_port = self._find_interface_in_parts(parts, -1, reverse=True)

                platform = ""
                for p in parts:
                    if "WS-" in p or "C2950" in p or "C4948" in p or "cisco" in p.lower():
                        platform = p

                neighbors.append(CDPNeighbor(
                    local_port=local_port,
                    remote_device=device_name,
                    remote_port=remote_port,
                    platform=platform,
                ))

        return neighbors

    def get_cdp_neighbors_detail(self) -> list[CDPNeighbor]:
        """More reliable CDP parsing using 'show cdp neighbors detail'."""
        output = self.connection.send_command("show cdp neighbors detail")
        neighbors = []
        blocks = output.split("-------------------------")

        for block in blocks:
            if not block.strip():
                continue

            device_match = re.search(r'Device ID:\s*(\S+)', block)
            local_match = re.search(r'Interface:\s*(\S+?)\s*,', block)
            remote_match = re.search(r'Port ID \(outgoing port\):\s*(\S+)', block)
            platform_match = re.search(r'Platform:\s*(.+?),', block)
            ip_match = re.search(r'IP address:\s*(\S+)', block)

            if device_match and local_match and remote_match:
                device_name = device_match.group(1).split('.')[0]  # strip domain
                neighbors.append(CDPNeighbor(
                    local_port=self._normalize_interface(local_match.group(1)),
                    remote_device=device_name,
                    remote_port=self._normalize_interface(remote_match.group(1)),
                    platform=platform_match.group(1).strip() if platform_match else "",
                ))

        return neighbors

    def _parse_vlan_list(self, vlan_str: str) -> list[int]:
        """Parse VLAN list like '101,102,120,200-210' into flat list."""
        vlans = []
        for part in vlan_str.split(','):
            part = part.strip()
            if '-' in part:
                start, end = part.split('-')
                vlans.extend(range(int(start), int(end) + 1))
            else:
                try:
                    vlans.append(int(part))
                except ValueError:
                    continue
        return sorted(vlans)

    def _normalize_interface(self, name: str) -> str:
        """Normalize interface names: 'GigabitEthernet0/1' -> 'Gi0/1'."""
        replacements = [
            (r'GigabitEthernet', 'Gi'),
            (r'FastEthernet', 'Fa'),
            (r'TenGigabitEthernet', 'Te'),
            (r'Gig\s*', 'Gi'),
            (r'Fas\s*', 'Fa'),
        ]
        for pattern, repl in replacements:
            name = re.sub(pattern, repl, name)
        return name.strip()

    def _find_interface_in_parts(self, parts: list, start_idx: int, reverse: bool = False) -> str:
        """Find interface name in split line parts."""
        prefixes = ['Gig', 'Fas', 'Ten', 'Gi', 'Fa', 'Te', 'Eth']
        search_range = reversed(range(len(parts))) if reverse else range(start_idx, len(parts))

        for i in search_range:
            for prefix in prefixes:
                if parts[i].startswith(prefix):
                    # Next part might be the number (e.g. "Gig 0/1")
                    if i + 1 < len(parts) and re.match(r'\d+/\d+', parts[i + 1]):
                        return self._normalize_interface(parts[i] + parts[i + 1])
                    elif re.match(r'.*\d+/\d+', parts[i]):
                        return self._normalize_interface(parts[i])
        return ""


@dataclass
class RouterInterface:
    """Router interface info from 'show ip interface brief'."""
    name: str               # e.g. "GigabitEthernet0/0"
    ip_address: str         # e.g. "172.22.22.1" or "unassigned"
    status: str             # "up", "down", "administratively down"
    protocol: str           # "up", "down"
    description: str = ""
    mtu: int = None


@dataclass
class ConnectedRoute:
    """Connected route from 'show ip route connected'."""
    network: str            # e.g. "172.22.22.0/24"
    interface: str          # e.g. "GigabitEthernet0/0"
    next_hop: str = ""


@dataclass
class RouterInfo:
    """Router info from 'show version'."""
    hostname: str = ""
    model: str = ""         # e.g. "CISCO2811", "ISR4431"
    serial: str = ""
    ios_version: str = ""
    uptime: str = ""


class CiscoRouterSSH(CiscoSSH):
    """Extended SSH connector for Cisco routers."""

    def get_interfaces(self) -> list[RouterInterface]:
        """Get interfaces from 'show ip interface brief'."""
        output = self.connection.send_command("show ip interface brief")
        interfaces = []

        for line in output.splitlines():
            # Skip header line
            if "Interface" in line and "IP-Address" in line:
                continue
            # Match: GigabitEthernet0/0     172.22.22.1     YES manual up                    up
            match = re.match(
                r'^(\S+)\s+(\S+)\s+\S+\s+\S+\s+(up|down|administratively down)\s+(\S+)',
                line.strip()
            )
            if match:
                interfaces.append(RouterInterface(
                    name=self._normalize_interface(match.group(1)),
                    ip_address=match.group(2),
                    status=match.group(3),
                    protocol=match.group(4),
                ))

        return interfaces

    def get_interface_descriptions(self) -> dict:
        """Get interface descriptions from running config."""
        output = self.connection.send_command("show running-config | include interface|description")
        descriptions = {}
        current_iface = None

        for line in output.splitlines():
            iface_match = re.match(r'^interface\s+(\S+)', line)
            if iface_match:
                current_iface = self._normalize_interface(iface_match.group(1))
            desc_match = re.match(r'^\s*description\s+(.+)', line)
            if desc_match and current_iface:
                descriptions[current_iface] = desc_match.group(1).strip()

        return descriptions

    def get_connected_routes(self) -> list[ConnectedRoute]:
        """Get connected routes from 'show ip route connected'."""
        output = self.connection.send_command("show ip route connected")
        routes = []

        for line in output.splitlines():
            # Match: C    172.22.22.0/24 is directly connected, GigabitEthernet0/0
            match = re.search(
                r'C\s+(\d+\.\d+\.\d+\.\d+(?:/\d+)?)\s+is directly connected,\s*(\S+)',
                line
            )
            if match:
                routes.append(ConnectedRoute(
                    network=match.group(1),
                    interface=self._normalize_interface(match.group(2)),
                ))

        return routes

    def get_version_info(self) -> RouterInfo:
        """Get router info from 'show version'."""
        output = self.connection.send_command("show version")
        info = RouterInfo()

        # Hostname
        hostname_match = re.search(r'^(\S+)\s+uptime is', output, re.MULTILINE)
        if hostname_match:
            info.hostname = hostname_match.group(1)

        # Model - various formats
        model_match = re.search(r'[Cc]isco\s+(\S+)\s+.*(?:processor|revision)', output)
        if model_match:
            info.model = model_match.group(1)
        else:
            # Try another format
            model_match2 = re.search(r'[Cc]isco\s+(ISR\d+|C\d+|CISCO\d+)', output)
            if model_match2:
                info.model = model_match2.group(1)

        # Serial number
        serial_match = re.search(r'Processor board ID\s+(\S+)', output)
        if serial_match:
            info.serial = serial_match.group(1)

        # IOS version
        ios_match = re.search(r'Version\s+(\S+)', output)
        if ios_match:
            info.ios_version = ios_match.group(1).rstrip(',')

        # Uptime
        uptime_match = re.search(r'uptime is\s+(.+)', output)
        if uptime_match:
            info.uptime = uptime_match.group(1).strip()

        return info

    def scan_router(self) -> dict:
        """Full router scan - interfaces, routes, CDP, version."""
        interfaces = self.get_interfaces()
        descriptions = self.get_interface_descriptions()
        
        # Add descriptions and MTU to interfaces
        for iface in interfaces:
            if iface.name in descriptions:
                iface.description = descriptions[iface.name]
            # Get MTU for tunnel interfaces
            if "tunnel" in iface.name.lower():
                mtu = self.get_interface_mtu(iface.name)
                if mtu:
                    iface.mtu = mtu

        routes = self.get_connected_routes()
        cdp_neighbors = self.get_cdp_neighbors_detail()
        version_info = self.get_version_info()

        return {
            "hostname": version_info.hostname,
            "model": version_info.model,
            "serial": version_info.serial,
            "ios_version": version_info.ios_version,
            "uptime": version_info.uptime,
            "interfaces": interfaces,
            "routes": routes,
            "cdp_neighbors": cdp_neighbors,
        }

    def get_interface_mtu(self, interface: str) -> int | None:
        """Get IP MTU for specific interface from running-config."""
        try:
            import re
            output = self.connection.send_command(f"show running-config interface {interface}")
            # Match: ip mtu 1400
            match = re.search(r'ip mtu\s+(\d+)', output)
            if match:
                return int(match.group(1))
        except:
            pass
        return None
