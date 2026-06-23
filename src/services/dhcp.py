"""
DHCP Service Handler.

Handles monitoring and management of DHCP servers:
- isc-dhcp-server
- kea-dhcp4
- dnsmasq
"""

from typing import Any, Optional
from datetime import datetime

from loguru import logger

from src.services.base import (
    BaseService,
    HealthCheckResult,
    DiagnosticResult,
)
from src.core.ssh_manager import SSHManager


class DHCPService(BaseService):
    """
    DHCP service handler.
    
    Supports isc-dhcp-server, kea-dhcp4, and dnsmasq.
    """
    
    service_type: str = "dhcp"
    
    def __init__(self, ssh_manager: SSHManager, server_id: str):
        super().__init__(ssh_manager, server_id)
        self._leases_file: Optional[str] = None
    
    async def get_leases_file(self) -> Optional[str]:
        """Find and return leases file path."""
        if self._leases_file is not None:
            return self._leases_file
        
        det = await self.detect()
        if not det:
            return None
        
        file_paths = self.service_config.get("file_paths", {}).get(det["name"], {})
        leases_paths = file_paths.get("leases", [])
        
        if leases_paths:
            self._leases_file = await self.ssh.find_existing_file(
                self.server_id,
                leases_paths
            )
        
        return self._leases_file
    
    async def check_health(self) -> list[HealthCheckResult]:
        """
        Perform DHCP-specific health checks.
        
        Checks:
        - Process is running
        - Port 67 is listening
        - Config file exists
        - Leases file is accessible
        """
        results = []
        
        status = await self.get_status()
        results.append(HealthCheckResult(
            name="process_running",
            passed=status.running,
            message="DHCP process is running" if status.running else "DHCP process is not running",
            details={"pid": status.pid} if status.pid else None
        ))
        
        port_check = await self.ssh.execute(
            self.server_id,
            "netstat -uln 2>/dev/null | grep -q ':67 ' && echo 'ok' || "
            "ss -uln 2>/dev/null | grep -q ':67 ' && echo 'ok' || echo 'fail'"
        )
        port_listening = "ok" in port_check.stdout
        results.append(HealthCheckResult(
            name="port_listening",
            passed=port_listening,
            message="UDP port 67 is listening" if port_listening else "UDP port 67 is not listening"
        ))
        
        config_file = await self.get_config_file()
        results.append(HealthCheckResult(
            name="config_exists",
            passed=config_file is not None,
            message=f"Config file found: {config_file}" if config_file else "Config file not found",
            details={"path": config_file} if config_file else None
        ))
        
        leases_file = await self.get_leases_file()
        results.append(HealthCheckResult(
            name="leases_accessible",
            passed=leases_file is not None,
            message=f"Leases file found: {leases_file}" if leases_file else "Leases file not found",
            details={"path": leases_file} if leases_file else None
        ))
        
        return results
    
    async def get_extra_info(self) -> dict[str, Any]:
        """
        Get DHCP-specific information.
        
        Returns:
            - leases_count: Number of active leases
            - leases_file: Path to leases file
            - config_file: Path to config file
            - pool_info: DHCP pool information (if available)
        """
        info = {}
        
        info["config_file"] = await self.get_config_file()
        info["leases_file"] = await self.get_leases_file()
        
        leases_file = info["leases_file"]
        if leases_file:
            det = await self.detect()
            if det and det["name"] == "isc-dhcp-server":
                count_result = await self.ssh.execute(
                    self.server_id,
                    f"grep -c '^lease' {leases_file} 2>/dev/null || echo '0'"
                )
            else:
                count_result = await self.ssh.execute(
                    self.server_id,
                    f"wc -l < {leases_file} 2>/dev/null || echo '0'"
                )
            
            try:
                info["leases_count"] = int(count_result.stdout.strip())
            except (ValueError, TypeError):
                info["leases_count"] = 0
        else:
            info["leases_count"] = 0
        
        return info
    
    async def run_diagnostic(self, name: str) -> DiagnosticResult:
        """
        Run DHCP-specific diagnostic.
        
        Available diagnostics:
        - get_leases: Show current leases
        - get_config: Show configuration
        - config_test: Test configuration syntax
        - count_leases: Count active leases
        - get_process_info: Show process details
        """
        det = await self.detect()
        if not det:
            return DiagnosticResult(
                name=name,
                success=False,
                output="",
                error="DHCP service not detected"
            )
        
        if name == "get_leases":
            leases_file = await self.get_leases_file()
            if not leases_file:
                return DiagnosticResult(
                    name=name,
                    success=False,
                    output="",
                    error="Leases file not found"
                )
            result = await self.ssh.execute(
                self.server_id,
                f"cat {leases_file}"
            )
            return DiagnosticResult(
                name=name,
                success=result.success,
                output=result.stdout,
                error=result.stderr if not result.success else None
            )
        
        elif name == "get_config":
            config_file = await self.get_config_file()
            if not config_file:
                return DiagnosticResult(
                    name=name,
                    success=False,
                    output="",
                    error="Config file not found"
                )
            result = await self.ssh.execute(
                self.server_id,
                f"cat {config_file}"
            )
            return DiagnosticResult(
                name=name,
                success=result.success,
                output=result.stdout,
                error=result.stderr if not result.success else None
            )
        
        elif name == "config_test":
            config_file = await self.get_config_file()
            if not config_file:
                return DiagnosticResult(
                    name=name,
                    success=False,
                    output="",
                    error="Config file not found"
                )
            
            if det["name"] == "isc-dhcp-server":
                cmd = f"dhcpd -t -cf {config_file} 2>&1"
            elif det["name"] == "kea-dhcp4":
                cmd = f"kea-dhcp4 -t {config_file} 2>&1"
            else:
                cmd = "dnsmasq --test 2>&1"
            
            result = await self.ssh.execute(self.server_id, cmd)
            return DiagnosticResult(
                name=name,
                success=result.success,
                output=result.stdout,
                error=result.stderr if not result.success else None
            )
        
        elif name == "count_leases":
            leases_file = await self.get_leases_file()
            if not leases_file:
                return DiagnosticResult(
                    name=name,
                    success=False,
                    output="0",
                    error="Leases file not found"
                )
            
            if det["name"] == "isc-dhcp-server":
                cmd = f"grep -c '^lease' {leases_file} 2>/dev/null || echo '0'"
            else:
                cmd = f"wc -l < {leases_file} 2>/dev/null || echo '0'"
            
            result = await self.ssh.execute(self.server_id, cmd)
            return DiagnosticResult(
                name=name,
                success=result.success,
                output=result.stdout.strip(),
                error=result.stderr if not result.success else None
            )
        
        elif name == "get_process_info":
            process_name = await self.get_process_name()
            result = await self.ssh.execute(
                self.server_id,
                f"ps aux | grep {process_name} | grep -v grep"
            )
            return DiagnosticResult(
                name=name,
                success=result.success,
                output=result.stdout,
                error=result.stderr if not result.success else None
            )
        
        else:
            return DiagnosticResult(
                name=name,
                success=False,
                output="",
                error=f"Unknown diagnostic: {name}"
            )
    
    async def get_leases(self) -> list[dict]:
        """
        Parse and return current DHCP leases.
        
        Returns:
            List of lease dictionaries with IP, MAC, hostname, etc.
        """
        det = await self.detect()
        leases_file = await self.get_leases_file()
        
        if not det or not leases_file:
            return []
        
        result = await self.ssh.execute(
            self.server_id,
            f"cat {leases_file}"
        )
        
        if not result.success:
            return []
        
        if det["name"] == "isc-dhcp-server":
            return self._parse_isc_leases(result.stdout)
        elif det["name"] == "kea-dhcp4":
            return self._parse_kea_leases(result.stdout)
        else:
            return self._parse_dnsmasq_leases(result.stdout)
    
    def _parse_isc_leases(self, content: str) -> list[dict]:
        """Parse ISC DHCP server leases file."""
        leases = []
        current_lease = {}
        
        for line in content.split("\n"):
            line = line.strip()
            
            if line.startswith("lease "):
                if current_lease:
                    leases.append(current_lease)
                ip = line.split()[1].rstrip("{")
                current_lease = {"ip": ip}
            
            elif line.startswith("hardware ethernet"):
                mac = line.split()[-1].rstrip(";")
                current_lease["mac"] = mac
            
            elif line.startswith("client-hostname"):
                hostname = line.split('"')[1] if '"' in line else ""
                current_lease["hostname"] = hostname
            
            elif line.startswith("starts"):
                parts = line.split()
                if len(parts) >= 4:
                    current_lease["starts"] = f"{parts[2]} {parts[3].rstrip(';')}"
            
            elif line.startswith("ends"):
                parts = line.split()
                if len(parts) >= 4:
                    current_lease["ends"] = f"{parts[2]} {parts[3].rstrip(';')}"
            
            elif line.startswith("binding state"):
                state = line.split()[-1].rstrip(";")
                current_lease["state"] = state
            
            elif line == "}":
                if current_lease:
                    leases.append(current_lease)
                    current_lease = {}
        
        return leases
    
    def _parse_kea_leases(self, content: str) -> list[dict]:
        """Parse Kea DHCP4 leases CSV file."""
        leases = []
        lines = content.strip().split("\n")
        
        if not lines:
            return []
        
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) >= 3:
                leases.append({
                    "ip": parts[0],
                    "mac": parts[1] if len(parts) > 1 else "",
                    "hostname": parts[3] if len(parts) > 3 else "",
                    "state": "active"
                })
        
        return leases
    
    def _parse_dnsmasq_leases(self, content: str) -> list[dict]:
        """Parse dnsmasq leases file."""
        leases = []
        
        for line in content.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 4:
                leases.append({
                    "expires": parts[0],
                    "mac": parts[1],
                    "ip": parts[2],
                    "hostname": parts[3] if parts[3] != "*" else "",
                    "state": "active"
                })
        
        return leases

    async def get_recent_logs(self, lines: int = 50) -> str:
        """
        Get recent DHCP log entries.
        
        Args:
            lines: Number of lines to retrieve
            
        Returns:
            Recent log content
        """
        log_files = await self.get_log_files()
        
        if not log_files:
            # Fallback to syslog with dhcp filter
            result = await self.ssh.execute(
                self.server_id,
                f"grep -i dhcp /var/log/syslog 2>/dev/null | tail -n {lines} || tail -n {lines} /var/log/syslog 2>/dev/null || echo 'Cannot read logs'"
            )
            return result.stdout if result.success else f"Error: {result.stderr}"
        
        log_file = log_files[0]
        
        result = await self.ssh.execute(
            self.server_id,
            f"tail -n {lines} {log_file} 2>/dev/null || echo 'Cannot read log file'"
        )
        
        return result.stdout if result.success else f"Error: {result.stderr}"
