"""
Updates Checker.

Periodically checks for available system updates on all servers.
Runs once per day and caches results.
"""

import asyncio
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from loguru import logger

from src.core.config import get_config
from src.core.ssh_manager import get_ssh_manager, SSHManager


@dataclass
class UpdateStatus:
    """Update status for a server."""
    server_id: str
    updates_available: int = 0
    security_updates: int = 0
    packages: list = field(default_factory=list)
    checked_at: datetime = field(default_factory=datetime.now)
    error: Optional[str] = None
    
    @property
    def has_updates(self) -> bool:
        return self.updates_available > 0
    
    @property
    def status(self) -> str:
        """Return status: 'ok', 'updates', 'error'."""
        if self.error:
            return "error"
        return "updates" if self.has_updates else "ok"


def get_package_manager_commands(distro: str) -> dict:
    """Get package manager commands based on distribution."""
    distro = (distro or "").lower()
    
    if distro in ("debian", "ubuntu"):
        return {
            "update": "apt-get update -qq",
            "list_upgradable": "apt-get -s upgrade 2>/dev/null | grep -E '^Inst ' | awk '{print $2}'",
            "count_security": "apt-get -s upgrade 2>/dev/null | grep -i security | wc -l"
        }
    elif distro in ("centos", "rhel", "rocky", "alma"):
        return {
            "update": "yum makecache -q",
            "list_upgradable": "yum check-update -q 2>/dev/null | awk 'NF==3 {print $1}' || true",
            "count_security": "yum check-update --security -q 2>/dev/null | wc -l || echo 0"
        }
    elif distro == "fedora":
        return {
            "update": "dnf makecache -q",
            "list_upgradable": "dnf check-update -q 2>/dev/null | awk 'NF==3 {print $1}' || true",
            "count_security": "dnf check-update --security -q 2>/dev/null | wc -l || echo 0"
        }
    else:
        return {
            "update": "apt-get update -qq",
            "list_upgradable": "apt-get -s upgrade 2>/dev/null | grep -E '^Inst ' | awk '{print $2}'",
            "count_security": "apt-get -s upgrade 2>/dev/null | grep -i security | wc -l"
        }


class UpdatesChecker:
    """
    Checks for available updates on all servers.
    
    Runs automatically once per day.
    """
    
    def __init__(self, ssh_manager: Optional[SSHManager] = None):
        self.ssh = ssh_manager or get_ssh_manager()
        self.config = get_config()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._update_status: dict[str, UpdateStatus] = {}
        self._check_interval = 24 * 60 * 60  # 24 hours in seconds
    
    async def check_server_updates(self, server_id: str) -> UpdateStatus:
        """Check updates for a single server."""
        server = self.config.get_server_by_id(server_id)
        
        if not server:
            return UpdateStatus(
                server_id=server_id,
                error=f"Server not found: {server_id}"
            )
        
        status = UpdateStatus(server_id=server_id)
        
        try:
            # Test connection first
            connected = await self.ssh.test_connection(server_id)
            if not connected:
                status.error = "Connection failed"
                return status
            
            pm_commands = get_package_manager_commands(server.distro)
            
            # Update package cache (with sudo)
            update_result = await self.ssh.execute_sudo(
                server_id,
                pm_commands['update'],
                timeout=120.0
            )
            
            if not update_result.success:
                # Try without sudo for systems where apt update doesn't need it
                update_result = await self.ssh.execute(
                    server_id,
                    pm_commands['update'],
                    timeout=120.0
                )
            
            # List upgradable packages
            list_result = await self.ssh.execute(
                server_id,
                pm_commands['list_upgradable'],
                timeout=60.0
            )
            
            packages = []
            for line in list_result.stdout.strip().split("\n"):
                line = line.strip()
                if line and not line.startswith(("Listing", "Loaded", "Loading", "Last", "Reading")):
                    pkg_name = line.split()[0] if line.split() else line
                    if pkg_name and not pkg_name.startswith(("WARNING", "E:", "W:")):
                        packages.append(pkg_name)
            
            status.packages = packages[:100]  # Limit to 100 packages
            status.updates_available = len(packages)
            
            # Count security updates
            sec_result = await self.ssh.execute(
                server_id,
                pm_commands['count_security'],
                timeout=30.0
            )
            try:
                status.security_updates = int(sec_result.stdout.strip())
            except (ValueError, TypeError):
                status.security_updates = 0
            
            logger.info(f"Updates check for {server_id}: {status.updates_available} available ({status.security_updates} security)")
            
        except Exception as e:
            logger.error(f"Failed to check updates for {server_id}: {e}")
            status.error = str(e)
        
        # Cache result
        self._update_status[server_id] = status
        
        return status
    
    async def check_all_servers(self) -> dict[str, UpdateStatus]:
        """Check updates for all enabled servers in parallel."""
        servers = self.config.get_enabled_servers()
        
        if not servers:
            return {}
        
        logger.info(f"Checking updates for {len(servers)} servers...")
        
        # Check all servers in parallel
        tasks = [self.check_server_updates(server.id) for server in servers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        for i, result in enumerate(results):
            server_id = servers[i].id
            if isinstance(result, Exception):
                self._update_status[server_id] = UpdateStatus(
                    server_id=server_id,
                    error=str(result)
                )
            else:
                self._update_status[server_id] = result
        
        # Log summary
        total_updates = sum(s.updates_available for s in self._update_status.values())
        servers_with_updates = sum(1 for s in self._update_status.values() if s.has_updates)
        logger.info(f"Updates check complete: {total_updates} updates on {servers_with_updates} servers")
        
        return self._update_status
    
    async def _check_loop(self):
        """Main updates check loop - runs once per day."""
        logger.info("Updates checker started (interval: 24h)")
        
        # Initial check after 1 minute (let system stabilize)
        await asyncio.sleep(60)
        
        while self._running:
            try:
                await self.check_all_servers()
            except Exception as e:
                logger.error(f"Updates check loop error: {e}")
            
            # Wait 24 hours
            await asyncio.sleep(self._check_interval)
        
        logger.info("Updates checker stopped")
    
    async def start(self):
        """Start periodic updates checking."""
        if self._running:
            logger.warning("Updates checker already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info("Updates checker started")
    
    async def stop(self):
        """Stop periodic updates checking."""
        if not self._running:
            return
        
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("Updates checker stopped")
    
    def get_status(self, server_id: str) -> Optional[UpdateStatus]:
        """Get cached update status for a server."""
        return self._update_status.get(server_id)
    
    def get_all_status(self) -> dict[str, UpdateStatus]:
        """Get all cached update statuses."""
        return self._update_status.copy()
    
    @property
    def is_running(self) -> bool:
        """Check if updates checker is running."""
        return self._running


_updates_checker: Optional[UpdatesChecker] = None


def get_updates_checker() -> UpdatesChecker:
    """Get updates checker singleton instance."""
    global _updates_checker
    if _updates_checker is None:
        _updates_checker = UpdatesChecker()
    return _updates_checker