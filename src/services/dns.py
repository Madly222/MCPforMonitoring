"""
DNS Service Handler.

Handles monitoring and management of DNS servers:
- bind9 (named)
- dnsmasq
- unbound
- pdns (PowerDNS)
"""

from typing import Any, Optional

from loguru import logger

from src.services.base import (
    BaseService,
    HealthCheckResult,
    DiagnosticResult,
)
from src.core.ssh_manager import SSHManager


class DNSService(BaseService):
    """
    DNS service handler.
    
    Supports bind9, dnsmasq, unbound, and PowerDNS.
    Auto-detects which DNS server is running.
    """
    
    service_type: str = "dns"
    
    def __init__(self, ssh_manager: SSHManager, server_id: str):
        super().__init__(ssh_manager, server_id)
        self._zones_dir: Optional[str] = None
    
    async def detect(self) -> Optional[dict]:
        """
        Auto-detect DNS server type.
        
        Checks for running processes and installed packages to determine
        which DNS server is in use.
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
        
        # Fallback: auto-detect by checking processes and packages
        dns_servers = [
            {
                "name": "bind9",
                "service_name": "bind9",
                "process_name": "named",
                "check_cmd": "pgrep -x named >/dev/null || dpkg -l bind9 2>/dev/null | grep -q '^ii' || rpm -q bind >/dev/null 2>&1"
            },
            {
                "name": "dnsmasq",
                "service_name": "dnsmasq",
                "process_name": "dnsmasq",
                "check_cmd": "pgrep -x dnsmasq >/dev/null || dpkg -l dnsmasq 2>/dev/null | grep -q '^ii'"
            },
            {
                "name": "unbound",
                "service_name": "unbound",
                "process_name": "unbound",
                "check_cmd": "pgrep -x unbound >/dev/null || dpkg -l unbound 2>/dev/null | grep -q '^ii'"
            },
            {
                "name": "pdns",
                "service_name": "pdns",
                "process_name": "pdns_server",
                "check_cmd": "pgrep -x pdns_server >/dev/null || dpkg -l pdns-server 2>/dev/null | grep -q '^ii'"
            },
        ]
        
        for dns in dns_servers:
            result = await self.ssh.execute(self.server_id, dns["check_cmd"], timeout=10.0)
            if result.exit_code == 0:
                self._detected_service = {
                    "name": dns["name"],
                    "service_name": dns["service_name"],
                    "process_name": dns["process_name"]
                }
                logger.info(f"Auto-detected DNS server: {dns['name']} on {self.server_id}")
                return self._detected_service
        
        logger.warning(f"No DNS service detected on {self.server_id}")
        return None
    
    async def get_config_file(self) -> Optional[str]:
        """Find DNS config file based on detected server type."""
        if self._config_file is not None:
            return self._config_file
        
        det = await self.detect()
        if not det:
            return None
        
        # Config file paths by DNS server type
        config_paths = {
            "bind9": [
                "/etc/bind/named.conf",
                "/etc/bind/named.conf.local",
                "/etc/named.conf",
                "/etc/named/named.conf"
            ],
            "dnsmasq": [
                "/etc/dnsmasq.conf",
                "/etc/dnsmasq.d/local.conf"
            ],
            "unbound": [
                "/etc/unbound/unbound.conf",
                "/usr/local/etc/unbound/unbound.conf"
            ],
            "pdns": [
                "/etc/powerdns/pdns.conf",
                "/etc/pdns/pdns.conf"
            ]
        }
        
        paths = config_paths.get(det["name"], [])
        
        # Also check service_config if available
        file_paths = self.service_config.get("file_paths", {}).get(det["name"], {})
        if file_paths.get("config"):
            paths = file_paths["config"] + paths
        
        self._config_file = await self.ssh.find_existing_file(self.server_id, paths)
        return self._config_file
    
    async def get_zones_dir(self) -> Optional[str]:
        """Find DNS zones directory."""
        if self._zones_dir is not None:
            return self._zones_dir
        
        det = await self.detect()
        if not det:
            return None
        
        zones_paths = {
            "bind9": [
                "/etc/bind/zones",
                "/etc/bind",
                "/var/named",
                "/var/cache/bind"
            ],
            "pdns": [
                "/etc/powerdns/zones",
                "/var/lib/powerdns"
            ]
        }
        
        paths = zones_paths.get(det["name"], [])
        
        for path in paths:
            result = await self.ssh.execute(
                self.server_id,
                f"[ -d {path} ] && echo 'exists'"
            )
            if "exists" in result.stdout:
                self._zones_dir = path
                return self._zones_dir
        
        return None
    
    async def check_health(self) -> list[HealthCheckResult]:
        """
        Perform DNS-specific health checks.
        
        Checks:
        - Process is running
        - Port 53 is listening (TCP and UDP)
        - Config file exists
        - DNS resolution works
        """
        results = []
        
        # Check process
        status = await self.get_status()
        results.append(HealthCheckResult(
            name="process_running",
            passed=status.running,
            message="DNS process is running" if status.running else "DNS process is not running",
            details={"pid": status.pid} if status.pid else None
        ))
        
        # Check UDP port 53
        port_check_udp = await self.ssh.execute(
            self.server_id,
            "netstat -uln 2>/dev/null | grep -q ':53 ' && echo 'ok' || "
            "ss -uln 2>/dev/null | grep -q ':53 ' && echo 'ok' || echo 'fail'"
        )
        udp_listening = "ok" in port_check_udp.stdout
        results.append(HealthCheckResult(
            name="udp_port_listening",
            passed=udp_listening,
            message="UDP port 53 is listening" if udp_listening else "UDP port 53 is not listening"
        ))
        
        # Check TCP port 53
        port_check_tcp = await self.ssh.execute(
            self.server_id,
            "netstat -tln 2>/dev/null | grep -q ':53 ' && echo 'ok' || "
            "ss -tln 2>/dev/null | grep -q ':53 ' && echo 'ok' || echo 'fail'"
        )
        tcp_listening = "ok" in port_check_tcp.stdout
        results.append(HealthCheckResult(
            name="tcp_port_listening",
            passed=tcp_listening,
            message="TCP port 53 is listening" if tcp_listening else "TCP port 53 is not listening"
        ))
        
        # Check config file
        config_file = await self.get_config_file()
        results.append(HealthCheckResult(
            name="config_exists",
            passed=config_file is not None,
            message=f"Config file found: {config_file}" if config_file else "Config file not found",
            details={"path": config_file} if config_file else None
        ))
        
        # Check DNS resolution. A variant can define its own probe in
        # dns.yaml -> resolution_test (e.g. Technitium, which answers for its
        # own zones rather than a generic 'localhost' lookup); otherwise use the
        # generic check below.
        det = await self.detect()
        variant = det["name"] if det else None
        custom_test = self.service_config.get("resolution_test", {}).get(variant)
        if custom_test and "{zone}" in custom_test:
            try:
                from src.web import runtime_config as rc
                zone = rc.get_dns_test_zone()
            except Exception:
                zone = "rapidlink.md"
            custom_test = custom_test.replace("{zone}", zone)
        
        dns_test = await self.ssh.execute(
            self.server_id,
            custom_test or (
                "dig @127.0.0.1 localhost +short +time=2 +tries=1 >/dev/null 2>&1 && echo 'ok' || "
                "nslookup localhost 127.0.0.1 >/dev/null 2>&1 && echo 'ok' || "
                "host localhost 127.0.0.1 >/dev/null 2>&1 && echo 'ok' || echo 'fail'"
            )
        )
        dns_works = "ok" in dns_test.stdout
        results.append(HealthCheckResult(
            name="dns_resolution",
            passed=dns_works,
            message="DNS resolution working" if dns_works else "DNS resolution failed"
        ))
        
        return results
    
    async def get_extra_info(self) -> dict[str, Any]:
        """
        Get DNS-specific information.
        
        Returns:
            - dns_type: Type of DNS server (bind9, dnsmasq, etc.)
            - config_file: Path to config file
            - zones_dir: Path to zones directory (if applicable)
            - zones_count: Number of zone files
            - query_stats: Query statistics (if available)
        """
        info = {}
        
        det = await self.detect()
        info["dns_type"] = det["name"] if det else "unknown"
        info["config_file"] = await self.get_config_file()
        info["zones_dir"] = await self.get_zones_dir()
        
        # Count zones for bind9
        if det and det["name"] == "bind9" and info["zones_dir"]:
            count_result = await self.ssh.execute(
                self.server_id,
                f"find {info['zones_dir']} -name '*.zone' -o -name 'db.*' 2>/dev/null | wc -l"
            )
            try:
                info["zones_count"] = int(count_result.stdout.strip())
            except (ValueError, TypeError):
                info["zones_count"] = 0
        
        # Get query stats for bind9
        if det and det["name"] == "bind9":
            stats_result = await self.ssh.execute(
                self.server_id,
                "rndc stats 2>/dev/null && cat /var/cache/bind/named.stats 2>/dev/null | tail -20 || echo ''"
            )
            if stats_result.stdout.strip():
                info["has_stats"] = True
        
        return info
    
    async def get_log_files(self) -> list[str]:
        """Get DNS log file paths."""
        det = await self.detect()
        if not det:
            return []
        
        # Log file paths by DNS server type
        log_paths = {
            "bind9": [
                "/var/log/named/queries.log",
                "/var/log/named.log",
                "/var/log/bind.log",
                "/var/log/syslog"
            ],
            "dnsmasq": [
                "/var/log/dnsmasq.log",
                "/var/log/syslog"
            ],
            "unbound": [
                "/var/log/unbound.log",
                "/var/log/syslog"
            ],
            "pdns": [
                "/var/log/pdns.log",
                "/var/log/syslog"
            ]
        }
        
        paths = log_paths.get(det["name"], ["/var/log/syslog"])
        
        # Also check service_config
        log_config = self.service_config.get("log_files", {}).get(det["name"], [])
        for log in log_config:
            path = log.get("path") if isinstance(log, dict) else log
            if path not in paths:
                paths.insert(0, path)
        
        existing = []
        for path in paths:
            if await self.ssh.file_exists(self.server_id, path):
                existing.append(path)
        
        return existing if existing else ["/var/log/syslog"]
    
    async def run_diagnostic(self, name: str) -> DiagnosticResult:
        """
        Run DNS-specific diagnostic.
        
        Available diagnostics:
        - get_config: Show configuration
        - config_test: Test configuration syntax
        - get_zones: List zone files
        - query_test: Test DNS query
        - get_stats: Get query statistics
        - get_process_info: Show process details
        - get_cache_stats: Show cache statistics
        """
        det = await self.detect()
        if not det:
            return DiagnosticResult(
                name=name,
                success=False,
                output="",
                error="DNS service not detected"
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
            if det["name"] == "bind9":
                cmd = "named-checkconf 2>&1"
            elif det["name"] == "dnsmasq":
                cmd = "dnsmasq --test 2>&1"
            elif det["name"] == "unbound":
                cmd = "unbound-checkconf 2>&1"
            elif det["name"] == "pdns":
                cmd = "pdns_server --config-check 2>&1"
            else:
                return DiagnosticResult(
                    name=name,
                    success=False,
                    output="",
                    error=f"Config test not supported for {det['name']}"
                )
            
            result = await self.ssh.execute(self.server_id, cmd)
            # For named-checkconf, empty output means success
            success = result.exit_code == 0 or (det["name"] == "bind9" and not result.stderr)
            return DiagnosticResult(
                name=name,
                success=success,
                output=result.stdout or "Configuration OK",
                error=result.stderr if not success else None
            )
        
        elif name == "get_zones":
            zones_dir = await self.get_zones_dir()
            if not zones_dir:
                return DiagnosticResult(
                    name=name,
                    success=False,
                    output="",
                    error="Zones directory not found"
                )
            
            result = await self.ssh.execute(
                self.server_id,
                f"find {zones_dir} -type f \\( -name '*.zone' -o -name 'db.*' \\) 2>/dev/null | head -50"
            )
            return DiagnosticResult(
                name=name,
                success=result.success,
                output=result.stdout or "No zone files found",
                error=result.stderr if not result.success else None
            )
        
        elif name == "query_test":
            # Test DNS resolution
            result = await self.ssh.execute(
                self.server_id,
                "dig @127.0.0.1 google.com A +short +time=5 2>&1 || "
                "nslookup google.com 127.0.0.1 2>&1 || "
                "host google.com 127.0.0.1 2>&1"
            )
            return DiagnosticResult(
                name=name,
                success=result.success and result.stdout.strip() != "",
                output=result.stdout or "No response",
                error=result.stderr if not result.success else None
            )
        
        elif name == "get_stats":
            if det["name"] == "bind9":
                cmd = "rndc stats 2>/dev/null; cat /var/cache/bind/named.stats 2>/dev/null | tail -50 || echo 'Stats not available'"
            elif det["name"] == "unbound":
                cmd = "unbound-control stats_noreset 2>&1 || echo 'Stats not available'"
            elif det["name"] == "pdns":
                cmd = "pdns_control show '*' 2>&1 || echo 'Stats not available'"
            else:
                return DiagnosticResult(
                    name=name,
                    success=False,
                    output="",
                    error=f"Stats not supported for {det['name']}"
                )
            
            result = await self.ssh.execute(self.server_id, cmd)
            return DiagnosticResult(
                name=name,
                success=result.success,
                output=result.stdout,
                error=result.stderr if not result.success else None
            )
        
        elif name == "get_process_info":
            process_name = await self.get_process_name()
            result = await self.ssh.execute(
                self.server_id,
                f"ps aux | grep -E '{process_name}' | grep -v grep"
            )
            return DiagnosticResult(
                name=name,
                success=result.success,
                output=result.stdout,
                error=result.stderr if not result.success else None
            )
        
        elif name == "get_cache_stats":
            if det["name"] == "bind9":
                cmd = "rndc dumpdb -cache 2>/dev/null && wc -l /var/cache/bind/named_dump.db 2>/dev/null || echo 'Cache dump not available'"
            elif det["name"] == "unbound":
                cmd = "unbound-control dump_cache 2>&1 | wc -l || echo 'Cache not available'"
            elif det["name"] == "dnsmasq":
                # dnsmasq doesn't have easy cache inspection
                cmd = "echo 'Cache inspection not supported for dnsmasq'"
            else:
                cmd = "echo 'Cache inspection not supported'"
            
            result = await self.ssh.execute(self.server_id, cmd)
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
    
    async def get_recent_logs(self, lines: int = 50) -> str:
        """
        Get recent DNS log entries.
        
        Args:
            lines: Number of lines to retrieve
            
        Returns:
            Recent log content
        """
        det = await self.detect()
        log_files = await self.get_log_files()
        
        if not log_files:
            # Fallback to syslog with dns filter - use sudo for protected files
            filter_pattern = "named|dns|bind|unbound" if det else "dns"
            result = await self.ssh.execute_sudo(
                self.server_id,
                f"grep -iE '{filter_pattern}' /var/log/syslog 2>/dev/null | tail -n {lines} || "
                f"tail -n {lines} /var/log/syslog 2>/dev/null || echo 'Cannot read logs'"
            )
            return result.stdout if result.success else f"Error: {result.stderr}"
        
        log_file = log_files[0]
        
        # Try without sudo first, then with sudo
        result = await self.ssh.execute(
            self.server_id,
            f"tail -n {lines} {log_file} 2>/dev/null"
        )
        
        if result.success and result.stdout.strip():
            return result.stdout
        
        # Try with sudo for protected log files
        result = await self.ssh.execute_sudo(
            self.server_id,
            f"tail -n {lines} {log_file} 2>/dev/null || echo 'Cannot read log file'"
        )
        
        return result.stdout if result.success else f"Error: {result.stderr}"
    
    async def query(self, domain: str, record_type: str = "A") -> DiagnosticResult:
        """
        Query DNS for a specific domain.
        
        Args:
            domain: Domain name to query
            record_type: Record type (A, AAAA, MX, NS, TXT, etc.)
            
        Returns:
            DiagnosticResult with query output
        """
        result = await self.ssh.execute(
            self.server_id,
            f"dig @127.0.0.1 {domain} {record_type} +short +time=5 2>&1 || "
            f"nslookup -type={record_type} {domain} 127.0.0.1 2>&1"
        )
        
        return DiagnosticResult(
            name=f"query_{domain}_{record_type}",
            success=result.success and bool(result.stdout.strip()),
            output=result.stdout or "No records found",
            error=result.stderr if not result.success else None
        )