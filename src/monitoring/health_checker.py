"""
Health Checker.

Performs periodic health checks on all monitored servers and services.
"""

import asyncio
from typing import Optional, Callable, Awaitable, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from loguru import logger

from src.core.config import get_config
from src.core.ssh_manager import get_ssh_manager, SSHManager
from src.services.dhcp import DHCPService
from src.services.dns import DNSService
from src.services.radius import RADIUSService
from src.services.base import HealthStatus, ServiceState


class CheckResult(Enum):
    """Health check result."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNREACHABLE = "unreachable"


@dataclass
class ServerHealthReport:
    """Health report for a server."""
    server_id: str
    host: str
    reachable: bool
    check_result: CheckResult
    services: list[dict]
    system_info: Optional[dict] = None
    checked_at: datetime = field(default_factory=datetime.now)
    error: Optional[str] = None


HealthReportHandler = Callable[[ServerHealthReport], Awaitable[None]]


# Service handlers registry
SERVICE_HANDLERS = {
    "dhcp": DHCPService,
    "dns": DNSService,
    "radius": RADIUSService,
}


class HealthChecker:
    """
    Performs periodic health checks on servers.
    
    Features:
    - Connectivity checks
    - Service health checks
    - System resource monitoring
    - Parallel execution for speed
    """
    
    def __init__(self, ssh_manager: Optional[SSHManager] = None):
        self.ssh = ssh_manager or get_ssh_manager()
        self.config = get_config()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._handlers: list[HealthReportHandler] = []
        self._last_reports: dict[str, ServerHealthReport] = {}
    
    def add_handler(self, handler: HealthReportHandler):
        """Add health report handler."""
        self._handlers.append(handler)
    
    def remove_handler(self, handler: HealthReportHandler):
        """Remove health report handler."""
        if handler in self._handlers:
            self._handlers.remove(handler)
    
    async def _notify_handlers(self, report: ServerHealthReport):
        """Notify all handlers about health report."""
        for handler in self._handlers:
            try:
                await handler(report)
            except Exception as e:
                logger.error(f"Health handler error: {e}")
    
    async def _check_service(self, server_id: str, service_type: str) -> dict:
        """Check a single service and return status dict."""
        handler_class = SERVICE_HANDLERS.get(service_type)
        
        if handler_class:
            handler = handler_class(self.ssh, server_id)
            
            try:
                info = await handler.get_info()
                
                return {
                    "type": service_type,
                    "name": info.service_name,
                    "state": info.state.value,
                    "health": info.health.value,
                    "pid": info.pid,
                    "extra": info.extra_info,
                    "is_healthy": info.health == HealthStatus.HEALTHY,
                    "is_running": info.state == ServiceState.RUNNING
                }
                
            except Exception as e:
                logger.debug(f"Service check error for {service_type}@{server_id}: {e}")
                return {
                    "type": service_type,
                    "name": service_type,
                    "state": "unknown",
                    "health": "unknown",
                    "error": str(e),
                    "is_healthy": False,
                    "is_running": False
                }
        else:
            # Basic check for unknown services
            try:
                status = await self.ssh.check_service_status(server_id, service_type)
                return {
                    "type": service_type,
                    "name": service_type,
                    "state": "running" if status.running else "stopped",
                    "health": "healthy" if status.running else "unhealthy",
                    "pid": status.pid,
                    "is_healthy": status.running,
                    "is_running": status.running
                }
            except Exception as e:
                return {
                    "type": service_type,
                    "name": service_type,
                    "state": "unknown",
                    "health": "unknown",
                    "error": str(e),
                    "is_healthy": False,
                    "is_running": False
                }
    
    async def check_server(self, server_id: str) -> ServerHealthReport:
        """
        Perform health check on a single server.
        
        Returns:
            ServerHealthReport with check results
        """
        server = self.config.get_server_by_id(server_id)
        
        if not server:
            return ServerHealthReport(
                server_id=server_id,
                host="unknown",
                reachable=False,
                check_result=CheckResult.UNREACHABLE,
                services=[],
                error=f"Server not found: {server_id}"
            )
        
        report = ServerHealthReport(
            server_id=server_id,
            host=server.host,
            reachable=False,
            check_result=CheckResult.UNREACHABLE,
            services=[]
        )
        
        try:
            # Check connectivity
            reachable = await self.ssh.test_connection(server_id)
            report.reachable = reachable
            
            if not reachable:
                report.check_result = CheckResult.UNREACHABLE
                report.error = "SSH connection failed"
                return report
            
            # Get system info
            report.system_info = await self.ssh.get_system_info(server_id)
            
            # Check all services in parallel
            if server.services:
                service_tasks = [
                    self._check_service(server_id, svc_type)
                    for svc_type in server.services
                ]
                service_results = await asyncio.gather(*service_tasks, return_exceptions=True)
                
                all_healthy = True
                any_unhealthy = False
                
                for result in service_results:
                    if isinstance(result, Exception):
                        service_report = {
                            "type": "unknown",
                            "name": "unknown",
                            "state": "error",
                            "health": "unknown",
                            "error": str(result)
                        }
                        any_unhealthy = True
                    else:
                        service_report = result
                        if not result.get("is_healthy", False):
                            all_healthy = False
                        if not result.get("is_running", False):
                            any_unhealthy = True
                    
                    # Remove internal flags before adding to report
                    service_report.pop("is_healthy", None)
                    service_report.pop("is_running", None)
                    report.services.append(service_report)
                
                # Determine overall health
                if any_unhealthy:
                    report.check_result = CheckResult.UNHEALTHY
                elif not all_healthy:
                    report.check_result = CheckResult.DEGRADED
                else:
                    report.check_result = CheckResult.HEALTHY
            else:
                # No services configured, just check connectivity
                report.check_result = CheckResult.HEALTHY
                
        except Exception as e:
            logger.error(f"Health check failed for {server_id}: {e}")
            report.error = str(e)
            report.check_result = CheckResult.UNREACHABLE
        
        # Store last report
        self._last_reports[server_id] = report
        
        return report
    
    async def check_all_servers(self) -> list[ServerHealthReport]:
        """Check health of all enabled servers in parallel."""
        servers = self.config.get_enabled_servers()
        
        if not servers:
            return []
        
        # Check all servers in parallel
        tasks = [self.check_server(server.id) for server in servers]
        reports = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results and notify handlers
        valid_reports = []
        for i, report in enumerate(reports):
            if isinstance(report, Exception):
                # Create error report
                server = servers[i]
                error_report = ServerHealthReport(
                    server_id=server.id,
                    host=server.host,
                    reachable=False,
                    check_result=CheckResult.UNREACHABLE,
                    services=[],
                    error=str(report)
                )
                valid_reports.append(error_report)
                await self._notify_handlers(error_report)
            else:
                valid_reports.append(report)
                await self._notify_handlers(report)
        
        return valid_reports
    
    async def _check_loop(self):
        """Main health check loop."""
        settings = self.config.load_settings()
        interval = settings.monitoring.health_check.interval_seconds
        
        logger.info(f"Health check loop started (interval: {interval}s)")
        
        while self._running:
            try:
                logger.debug("Running health checks...")
                reports = await self.check_all_servers()
                
                # Log summary
                healthy = sum(1 for r in reports if r.check_result == CheckResult.HEALTHY)
                unhealthy = sum(1 for r in reports if r.check_result == CheckResult.UNHEALTHY)
                unreachable = sum(1 for r in reports if r.check_result == CheckResult.UNREACHABLE)
                
                logger.info(f"Health check complete: {healthy} healthy, {unhealthy} unhealthy, {unreachable} unreachable")
                
            except Exception as e:
                logger.error(f"Health check loop error: {e}")
            
            await asyncio.sleep(interval)
        
        logger.info("Health check loop stopped")
    
    async def start(self):
        """Start periodic health checks."""
        if self._running:
            logger.warning("Health checker already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info("Health checker started")
    
    async def stop(self):
        """Stop periodic health checks."""
        if not self._running:
            return
        
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("Health checker stopped")
    
    def get_last_report(self, server_id: str) -> Optional[ServerHealthReport]:
        """Get last health report for server."""
        return self._last_reports.get(server_id)
    
    def get_all_reports(self) -> list[ServerHealthReport]:
        """Get all last health reports."""
        return list(self._last_reports.values())
    
    @property
    def is_running(self) -> bool:
        """Check if health checker is running."""
        return self._running


_health_checker: Optional[HealthChecker] = None


def get_health_checker() -> HealthChecker:
    """Get health checker singleton instance."""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker