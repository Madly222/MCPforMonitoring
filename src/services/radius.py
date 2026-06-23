"""
RADIUS Service Handler.

Handles monitoring and management of RADIUS servers:
- FreeRADIUS
"""

from typing import Any, Optional

from loguru import logger

from src.services.base import (
    BaseService,
    HealthCheckResult,
    DiagnosticResult,
)
from src.core.ssh_manager import SSHManager


class RADIUSService(BaseService):
    """
    RADIUS service handler.
    
    Supports FreeRADIUS (versions 2.x and 3.x).
    """
    
    service_type: str = "radius"
    
    def __init__(self, ssh_manager: SSHManager, server_id: str):
        super().__init__(ssh_manager, server_id)
        self._version: Optional[str] = None
    
    async def detect(self) -> Optional[dict]:
        """
        Auto-detect RADIUS server type.
        """
        if self._detected_service is not None:
            return self._detected_service
        
        # First try config-based detection
        detection = self.service_config.get("detection", {}).get("commands", [])
        
        for det in detection:
            result = await self.ssh.execute(self.server_id, det["check"], timeout=10.0)
            if result.success and "found" in result.stdout:
                self._detected_service = det
                logger.debug(f"Detected {det['name']} on {self.server_id}")
                return det
        
        # Fallback: auto-detect by checking processes
        radius_servers = [
            {
                "name": "freeradius",
                "service_name": "freeradius",
                "process_name": "freeradius",
                "check_cmd": "pgrep -x freeradius >/dev/null || pgrep -x radiusd >/dev/null"
            },
        ]
        
        for radius in radius_servers:
            result = await self.ssh.execute(self.server_id, radius["check_cmd"], timeout=10.0)
            if result.exit_code == 0:
                self._detected_service = {
                    "name": radius["name"],
                    "service_name": radius["service_name"],
                    "process_name": radius["process_name"]
                }
                logger.info(f"Auto-detected RADIUS server: {radius['name']} on {self.server_id}")
                return self._detected_service
        
        logger.warning(f"No RADIUS service detected on {self.server_id}")
        return None
    
    async def get_version(self) -> str:
        """Get FreeRADIUS version."""
        if self._version:
            return self._version
        
        result = await self.ssh.execute(
            self.server_id,
            "/usr/sbin/freeradius -v 2>/dev/null | head -1 || radiusd -v 2>/dev/null | head -1"
        )
        
        if result.success and result.stdout:
            # Parse: "freeradius: FreeRADIUS Version 2.1.12, ..."
            line = result.stdout.strip()
            if "Version" in line:
                try:
                    self._version = line.split("Version")[1].split(",")[0].strip()
                except:
                    self._version = "unknown"
            else:
                self._version = "unknown"
        else:
            self._version = "unknown"
        
        return self._version
    
    async def get_config_file(self) -> Optional[str]:
        """Find RADIUS config file."""
        if self._config_file is not None:
            return self._config_file
        
        config_paths = [
            "/etc/freeradius/3.0/radiusd.conf",
            "/etc/freeradius/radiusd.conf",
            "/etc/raddb/radiusd.conf",
            "/usr/local/etc/raddb/radiusd.conf"
        ]
        
        # Also check service_config if available
        det = await self.detect()
        if det:
            file_paths = self.service_config.get("file_paths", {}).get(det["name"], {})
            if file_paths.get("config"):
                config_paths = file_paths["config"] + config_paths
        
        self._config_file = await self.ssh.find_existing_file(self.server_id, config_paths)
        return self._config_file
    
    async def check_health(self) -> list[HealthCheckResult]:
        """
        Perform RADIUS-specific health checks.
        
        Checks:
        - Process is running
        - Ports 1812/1813 are listening (UDP)
        - Config file exists
        - Log file is being written
        """
        results = []
        
        # Check process
        status = await self.get_status()
        results.append(HealthCheckResult(
            name="process_running",
            passed=status.running,
            message="RADIUS process is running" if status.running else "RADIUS process is not running",
            details={"pid": status.pid} if status.pid else None
        ))
        
        # Check UDP port 1812 (authentication)
        port_check_1812 = await self.ssh.execute(
            self.server_id,
            "netstat -uln 2>/dev/null | grep -q ':1812 ' && echo 'ok' || "
            "ss -uln 2>/dev/null | grep -q ':1812 ' && echo 'ok' || echo 'fail'"
        )
        auth_listening = "ok" in port_check_1812.stdout
        results.append(HealthCheckResult(
            name="auth_port_listening",
            passed=auth_listening,
            message="UDP port 1812 (auth) is listening" if auth_listening else "UDP port 1812 (auth) is not listening"
        ))
        
        # Check UDP port 1813 (accounting)
        port_check_1813 = await self.ssh.execute(
            self.server_id,
            "netstat -uln 2>/dev/null | grep -q ':1813 ' && echo 'ok' || "
            "ss -uln 2>/dev/null | grep -q ':1813 ' && echo 'ok' || echo 'fail'"
        )
        acct_listening = "ok" in port_check_1813.stdout
        results.append(HealthCheckResult(
            name="acct_port_listening",
            passed=acct_listening,
            message="UDP port 1813 (acct) is listening" if acct_listening else "UDP port 1813 (acct) is not listening"
        ))
        
        # Check config file
        config_file = await self.get_config_file()
        results.append(HealthCheckResult(
            name="config_exists",
            passed=config_file is not None,
            message=f"Config file found: {config_file}" if config_file else "Config file not found",
            details={"path": config_file} if config_file else None
        ))
        
        # Check log file is recent (written in last hour)
        # This is informational only - not critical for health
        log_check = await self.ssh.execute_sudo(
            self.server_id,
            "find /var/log/freeradius/radius.log -mmin -60 2>/dev/null | grep -q . && echo 'ok' || echo 'stale'"
        )
        log_active = "ok" in log_check.stdout
        results.append(HealthCheckResult(
            name="log_active",
            passed=True,  # Always pass - this is informational
            message="Log file is being updated" if log_active else "Log file not updated recently (normal if no activity)",
            details={"is_active": log_active}
        ))
        
        return results
    
    async def get_extra_info(self) -> dict[str, Any]:
        """
        Get RADIUS-specific information.
        """
        info = {}
        
        det = await self.detect()
        info["radius_type"] = det["name"] if det else "unknown"
        info["version"] = await self.get_version()
        info["config_file"] = await self.get_config_file()
        
        # Get active sessions count from radutmp
        sessions_result = await self.ssh.execute_sudo(
            self.server_id,
            "wc -l < /var/log/freeradius/radutmp 2>/dev/null || echo '0'"
        )
        try:
            # radutmp has ~1 line per session (rough estimate)
            info["active_sessions_estimate"] = int(sessions_result.stdout.strip()) // 100
        except:
            info["active_sessions_estimate"] = 0
        
        # Get today's auth count from log
        auth_count_result = await self.ssh.execute_sudo(
            self.server_id,
            "grep -c 'Login OK' /var/log/freeradius/radius.log 2>/dev/null || echo '0'"
        )
        try:
            info["logins_today"] = int(auth_count_result.stdout.strip())
        except:
            info["logins_today"] = 0
        
        # Get failed auth count
        fail_count_result = await self.ssh.execute_sudo(
            self.server_id,
            "grep -c 'Login incorrect' /var/log/freeradius/radius.log 2>/dev/null || echo '0'"
        )
        try:
            info["failed_logins_today"] = int(fail_count_result.stdout.strip())
        except:
            info["failed_logins_today"] = 0
        
        return info
    
    async def get_log_files(self) -> list[str]:
        """Get RADIUS log file paths."""
        log_paths = [
            "/var/log/freeradius/radius.log",
            "/var/log/radius/radius.log",
            "/var/log/radiusd/radiusd.log",
            "/var/log/daloradius.log"
        ]
        
        # Check service_config
        det = await self.detect()
        if det:
            log_config = self.service_config.get("log_files", {}).get(det["name"], [])
            for log in log_config:
                path = log.get("path") if isinstance(log, dict) else log
                if path not in log_paths:
                    log_paths.insert(0, path)
        
        existing = []
        for path in log_paths:
            result = await self.ssh.execute_sudo(
                self.server_id,
                f"[ -f {path} ] && echo 'exists'"
            )
            if "exists" in result.stdout:
                existing.append(path)
        
        return existing if existing else ["/var/log/freeradius/radius.log"]
    
    async def run_diagnostic(self, name: str) -> DiagnosticResult:
        """
        Run RADIUS-specific diagnostic.
        
        Available diagnostics:
        - get_config: Show main configuration
        - config_test: Test configuration syntax
        - get_clients: Show configured NAS clients
        - get_users: Show configured users (first 50)
        - get_stats: Get authentication statistics
        - get_process_info: Show process details
        - get_recent_auths: Show recent authentications
        - get_failed_auths: Show recent failed authentications
        """
        det = await self.detect()
        if not det:
            return DiagnosticResult(
                name=name,
                success=False,
                output="",
                error="RADIUS service not detected"
            )
        
        if name == "get_config":
            config_file = await self.get_config_file()
            if not config_file:
                return DiagnosticResult(
                    name=name,
                    success=False,
                    output="",
                    error="Config file not found"
                )
            result = await self.ssh.execute_sudo(
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
            result = await self.ssh.execute_sudo(
                self.server_id,
                "/usr/sbin/freeradius -CX 2>&1 || radiusd -CX 2>&1"
            )
            # FreeRADIUS returns 0 on success, output includes "Configuration appears to be OK"
            success = result.exit_code == 0 or "Configuration appears to be OK" in result.stdout
            return DiagnosticResult(
                name=name,
                success=success,
                output=result.stdout if success else "",
                error=result.stdout if not success else None
            )
        
        elif name == "get_clients":
            result = await self.ssh.execute_sudo(
                self.server_id,
                "cat /etc/freeradius/clients.conf 2>/dev/null || cat /etc/freeradius/3.0/clients.conf 2>/dev/null || cat /etc/raddb/clients.conf 2>/dev/null"
            )
            return DiagnosticResult(
                name=name,
                success=result.success,
                output=result.stdout,
                error=result.stderr if not result.success else None
            )
        
        elif name == "get_users":
            result = await self.ssh.execute_sudo(
                self.server_id,
                "head -100 /etc/freeradius/users 2>/dev/null || head -100 /etc/freeradius/3.0/users 2>/dev/null || head -100 /etc/raddb/users 2>/dev/null"
            )
            return DiagnosticResult(
                name=name,
                success=result.success,
                output=result.stdout,
                error=result.stderr if not result.success else None
            )
        
        elif name == "get_stats":
            # Get various stats
            stats = []
            
            # Logins today
            result = await self.ssh.execute_sudo(
                self.server_id,
                "grep -c 'Login OK' /var/log/freeradius/radius.log 2>/dev/null || echo '0'"
            )
            stats.append(f"Successful logins (current log): {result.stdout.strip()}")
            
            # Failed logins
            result = await self.ssh.execute_sudo(
                self.server_id,
                "grep -c 'Login incorrect' /var/log/freeradius/radius.log 2>/dev/null || echo '0'"
            )
            stats.append(f"Failed logins (current log): {result.stdout.strip()}")
            
            # Active sessions estimate
            result = await self.ssh.execute_sudo(
                self.server_id,
                "wc -c < /var/log/freeradius/radutmp 2>/dev/null || echo '0'"
            )
            stats.append(f"Radutmp size: {result.stdout.strip()} bytes")
            
            # Radwtmp size (total accounting)
            result = await self.ssh.execute_sudo(
                self.server_id,
                "ls -lh /var/log/freeradius/radwtmp 2>/dev/null | awk '{print $5}' || echo 'N/A'"
            )
            stats.append(f"Radwtmp size: {result.stdout.strip()}")
            
            return DiagnosticResult(
                name=name,
                success=True,
                output="\n".join(stats),
                error=None
            )
        
        elif name == "get_process_info":
            result = await self.ssh.execute(
                self.server_id,
                "ps aux | grep -E '(freeradius|radiusd)' | grep -v grep"
            )
            return DiagnosticResult(
                name=name,
                success=result.success,
                output=result.stdout,
                error=result.stderr if not result.success else None
            )
        
        elif name == "get_recent_auths":
            result = await self.ssh.execute_sudo(
                self.server_id,
                "grep 'Login OK' /var/log/freeradius/radius.log 2>/dev/null | tail -20"
            )
            return DiagnosticResult(
                name=name,
                success=True,
                output=result.stdout or "No recent successful authentications",
                error=None
            )
        
        elif name == "get_failed_auths":
            result = await self.ssh.execute_sudo(
                self.server_id,
                "grep -E '(Login incorrect|Invalid user)' /var/log/freeradius/radius.log 2>/dev/null | tail -20"
            )
            return DiagnosticResult(
                name=name,
                success=True,
                output=result.stdout or "No recent failed authentications",
                error=None
            )
        
        else:
            return DiagnosticResult(
                name=name,
                success=False,
                output="",
                error=f"Unknown diagnostic: {name}"
            )
    
    async def get_recent_logs(self, lines: int = 50) -> str:
        """
        Get recent RADIUS log entries.
        """
        log_files = await self.get_log_files()
        
        if not log_files:
            return "No log files found"
        
        log_file = log_files[0]
        result = await self.ssh.execute_sudo(
            self.server_id,
            f"tail -n {lines} {log_file} 2>/dev/null || echo 'Cannot read log file'"
        )
        
        return result.stdout if result.success else f"Error: {result.stderr}"