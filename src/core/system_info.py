"""
System Information Collector.

Gathers comprehensive information about remote servers.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger
from src.core.ssh_manager import SSHManager


@dataclass
class ServerReport:
    """Complete server information report."""
    server_id: str
    collected_at: datetime = field(default_factory=datetime.now)
    
    # OS
    os_name: str = ""
    os_version: str = ""
    os_codename: str = ""
    kernel: str = ""
    arch: str = ""
    
    # Hardware
    cpu_model: str = ""
    cpu_cores: int = 0
    memory_total_mb: int = 0
    memory_used_mb: int = 0
    memory_percent: float = 0.0
    disk_total_gb: float = 0.0
    disk_used_gb: float = 0.0
    disk_percent: float = 0.0
    
    # Network
    hostname: str = ""
    interfaces: list = field(default_factory=list)
    open_ports: list = field(default_factory=list)
    
    # Status
    uptime: str = ""
    load_average: str = ""
    init_system: str = ""
    
    # Security
    updates_available: int = 0
    security_updates: int = 0
    reboot_required: bool = False
    firewall_status: str = "unknown"
    
    # Services
    total_services: int = 0
    running_services: int = 0
    failed_services: int = 0
    
    errors: list = field(default_factory=list)


class SystemInfoCollector:
    """Collects system information from remote servers."""
    
    def __init__(self, ssh: SSHManager):
        self.ssh = ssh
    
    async def collect(self, server_id: str) -> ServerReport:
        """Collect full system report."""
        report = ServerReport(server_id=server_id)
        
        try:
            await self._collect_os(server_id, report)
            await self._collect_hardware(server_id, report)
            await self._collect_network(server_id, report)
            await self._collect_status(server_id, report)
            await self._collect_security(server_id, report)
            await self._collect_services(server_id, report)
        except Exception as e:
            logger.error(f"Error collecting info for {server_id}: {e}")
            report.errors.append(str(e))
        
        return report
    
    async def _run(self, server_id: str, cmd: str, timeout: float = 10.0) -> str:
        """Execute command and return stdout."""
        result = await self.ssh.execute(server_id, cmd, timeout=timeout)
        return result.stdout.strip() if result.success else ""
    
    async def _run_sudo(self, server_id: str, cmd: str, timeout: float = 30.0) -> str:
        """Execute command with sudo and return stdout."""
        result = await self.ssh.execute_sudo(server_id, cmd, timeout=timeout)
        return result.stdout.strip() if result.success else ""
    
    async def _collect_os(self, server_id: str, report: ServerReport):
        """Collect OS information."""
        # Parse /etc/os-release
        output = await self._run(server_id, "cat /etc/os-release 2>/dev/null")
        for line in output.split("\n"):
            if "=" in line:
                key, value = line.split("=", 1)
                value = value.strip('"')
                if key == "PRETTY_NAME":
                    report.os_name = value
                elif key == "VERSION_ID":
                    report.os_version = value
                elif key == "VERSION_CODENAME":
                    report.os_codename = value
        
        report.kernel = await self._run(server_id, "uname -r")
        report.arch = await self._run(server_id, "uname -m")
    
    async def _collect_hardware(self, server_id: str, report: ServerReport):
        """Collect hardware information."""
        # CPU
        cpu = await self._run(server_id, "grep 'model name' /proc/cpuinfo | head -1 | cut -d: -f2")
        report.cpu_model = cpu.strip()
        
        cores = await self._run(server_id, "nproc 2>/dev/null || grep -c processor /proc/cpuinfo")
        try:
            report.cpu_cores = int(cores)
        except ValueError:
            pass
        
        # Memory
        mem = await self._run(server_id, "free -m | grep Mem | awk '{print $2,$3}'")
        parts = mem.split()
        if len(parts) >= 2:
            try:
                report.memory_total_mb = int(parts[0])
                report.memory_used_mb = int(parts[1])
                if report.memory_total_mb > 0:
                    report.memory_percent = round(report.memory_used_mb / report.memory_total_mb * 100, 1)
            except ValueError:
                pass
        
        # Disk
        disk = await self._run(server_id, "df -BG / | tail -1 | awk '{gsub(\"G\",\"\"); print $2,$3,$5}'")
        parts = disk.split()
        if len(parts) >= 3:
            try:
                report.disk_total_gb = float(parts[0])
                report.disk_used_gb = float(parts[1])
                report.disk_percent = float(parts[2].rstrip('%'))
            except ValueError:
                pass
    
    async def _collect_network(self, server_id: str, report: ServerReport):
        """Collect network information."""
        report.hostname = await self._run(server_id, "hostname -f 2>/dev/null || hostname")
        
        # Interfaces
        output = await self._run(
            server_id,
            "ip -4 addr show 2>/dev/null | grep inet | awk '{print $NF, $2}'"
        )
        for line in output.split("\n"):
            parts = line.split()
            if len(parts) >= 2:
                report.interfaces.append({
                    "name": parts[0],
                    "ip": parts[1].split("/")[0]
                })
        
        # Open ports
        output = await self._run(
            server_id,
            "ss -tlnp 2>/dev/null | grep LISTEN | awk '{print $4}' | rev | cut -d: -f1 | rev | sort -un | head -15"
        )
        for port in output.split("\n"):
            if port.isdigit():
                report.open_ports.append(int(port))
    
    async def _collect_status(self, server_id: str, report: ServerReport):
        """Collect system status."""
        report.uptime = await self._run(server_id, "uptime -p 2>/dev/null || uptime | sed 's/.*up/up/'")
        report.load_average = await self._run(server_id, "cat /proc/loadavg | cut -d' ' -f1-3")
        
        # Init system
        init = await self._run(
            server_id,
            "if command -v systemctl >/dev/null 2>&1 && systemctl is-system-running >/dev/null 2>&1; then echo 'systemd'; else echo 'sysvinit'; fi"
        )
        report.init_system = init or "unknown"
    
    async def _collect_security(self, server_id: str, report: ServerReport):
        """Collect security information."""
        # Available updates (may be slow)
        updates = await self._run(
            server_id,
            "apt list --upgradable 2>/dev/null | grep -v Listing | wc -l",
            timeout=30.0
        )
        try:
            report.updates_available = int(updates)
        except ValueError:
            pass
        
        # Security updates
        sec = await self._run(
            server_id,
            "apt list --upgradable 2>/dev/null | grep -i security | wc -l",
            timeout=30.0
        )
        try:
            report.security_updates = int(sec)
        except ValueError:
            pass
        
        # Reboot required
        reboot = await self._run(server_id, "[ -f /var/run/reboot-required ] && echo yes || echo no")
        report.reboot_required = reboot == "yes"
        
        # Firewall
        fw = await self._run(server_id, "ufw status 2>/dev/null | head -1 || echo unknown")
        if "active" in fw.lower():
            report.firewall_status = "active"
        elif "inactive" in fw.lower():
            report.firewall_status = "inactive"
        else:
            report.firewall_status = "unknown"
    
    async def _collect_services(self, server_id: str, report: ServerReport):
        """Collect services information."""
        if report.init_system == "systemd":
            total = await self._run(server_id, "systemctl list-units --type=service --no-legend 2>/dev/null | wc -l")
            running = await self._run(server_id, "systemctl list-units --type=service --state=running --no-legend 2>/dev/null | wc -l")
            failed = await self._run(server_id, "systemctl list-units --type=service --state=failed --no-legend 2>/dev/null | wc -l")
        else:
            total = await self._run(server_id, "ls /etc/init.d/ 2>/dev/null | wc -l")
            running = await self._run(server_id, "ps aux | grep -v grep | wc -l")
            failed = "0"
        
        try:
            report.total_services = int(total)
            report.running_services = int(running)
            report.failed_services = int(failed)
        except ValueError:
            pass


def report_to_dict(report: ServerReport) -> dict:
    """Convert report to dictionary for API."""
    return {
        "server_id": report.server_id,
        "collected_at": report.collected_at.isoformat(),
        "os": {
            "name": report.os_name,
            "version": report.os_version,
            "codename": report.os_codename,
            "kernel": report.kernel,
            "arch": report.arch
        },
        "hardware": {
            "cpu_model": report.cpu_model,
            "cpu_cores": report.cpu_cores,
            "memory_total_mb": report.memory_total_mb,
            "memory_used_mb": report.memory_used_mb,
            "memory_percent": report.memory_percent,
            "disk_total_gb": report.disk_total_gb,
            "disk_used_gb": report.disk_used_gb,
            "disk_percent": report.disk_percent
        },
        "network": {
            "hostname": report.hostname,
            "interfaces": report.interfaces,
            "open_ports": report.open_ports
        },
        "status": {
            "uptime": report.uptime,
            "load_average": report.load_average,
            "init_system": report.init_system
        },
        "security": {
            "updates_available": report.updates_available,
            "security_updates": report.security_updates,
            "reboot_required": report.reboot_required,
            "firewall_status": report.firewall_status
        },
        "services": {
            "total": report.total_services,
            "running": report.running_services,
            "failed": report.failed_services
        },
        "errors": report.errors
    }
