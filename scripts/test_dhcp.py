#!/usr/bin/env python3
"""
DHCP Service Test Script.

Tests DHCP service monitoring capabilities.
Usage: python scripts/test_dhcp.py <server_id>
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from src.core.config import get_config
from src.core.ssh_manager import get_ssh_manager
from src.services.dhcp import DHCPService


def setup_logging():
    """Configure logging for test script."""
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="DEBUG"
    )


async def test_dhcp_service(server_id: str) -> bool:
    """Test DHCP service on specified server."""
    ssh = get_ssh_manager()
    
    try:
        logger.info(f"Testing DHCP service on {server_id}")
        logger.info("=" * 50)
        
        dhcp = DHCPService(ssh, server_id)
        
        logger.info("Detecting DHCP service...")
        det = await dhcp.detect()
        if not det:
            logger.error("DHCP service not detected")
            return False
        
        logger.success(f"Detected: {det['name']}")
        logger.info(f"  Service name: {det['service_name']}")
        logger.info(f"  Process name: {det.get('process_name', det['service_name'])}")
        
        logger.info("-" * 50)
        logger.info("Getting service status...")
        status = await dhcp.get_status()
        
        state = "running" if status.running else "stopped"
        logger.info(f"  Status: {state}")
        logger.info(f"  Enabled: {status.enabled}")
        if status.pid:
            logger.info(f"  PID: {status.pid}")
        logger.info(f"  Init system: {status.init_system.value}")
        
        logger.info("-" * 50)
        logger.info("Running health checks...")
        health_results = await dhcp.check_health()
        
        all_healthy = True
        for check in health_results:
            status_icon = "✓" if check.passed else "✗"
            log_fn = logger.success if check.passed else logger.warning
            log_fn(f"  [{status_icon}] {check.name}: {check.message}")
            if not check.passed:
                all_healthy = False
        
        logger.info("-" * 50)
        logger.info("Getting extra info...")
        extra = await dhcp.get_extra_info()
        
        logger.info(f"  Config file: {extra.get('config_file', 'not found')}")
        logger.info(f"  Leases file: {extra.get('leases_file', 'not found')}")
        logger.info(f"  Leases count: {extra.get('leases_count', 0)}")
        
        logger.info("-" * 50)
        logger.info("Running diagnostics...")
        
        diag = await dhcp.run_diagnostic("count_leases")
        logger.info(f"  Lease count: {diag.output}")
        
        diag = await dhcp.run_diagnostic("get_process_info")
        if diag.success and diag.output:
            logger.info(f"  Process info:")
            for line in diag.output.strip().split("\n")[:3]:
                logger.info(f"    {line[:80]}")
        
        logger.info("-" * 50)
        logger.info("Parsing leases...")
        leases = await dhcp.get_leases()
        
        if leases:
            logger.info(f"  Found {len(leases)} lease(s)")
            for lease in leases[:5]:
                ip = lease.get("ip", "?")
                mac = lease.get("mac", "?")
                hostname = lease.get("hostname", "")
                state = lease.get("state", "?")
                logger.info(f"    {ip} | {mac} | {hostname} | {state}")
            if len(leases) > 5:
                logger.info(f"    ... and {len(leases) - 5} more")
        else:
            logger.info("  No leases found")
        
        logger.info("-" * 50)
        logger.info("Getting full service info...")
        info = await dhcp.get_info()
        
        logger.info(f"  Service type: {info.service_type}")
        logger.info(f"  Service name: {info.service_name}")
        logger.info(f"  State: {info.state.value}")
        logger.info(f"  Health: {info.health.value}")
        
        logger.info("=" * 50)
        if all_healthy and info.state.value == "running":
            logger.success("DHCP service test PASSED")
            return True
        else:
            logger.warning("DHCP service test completed with warnings")
            return True
        
    except Exception as e:
        logger.error(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await ssh.close()


async def main():
    """Main entry point."""
    setup_logging()
    
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_dhcp.py <server_id>")
        print("Example: python scripts/test_dhcp.py dhcp-primary")
        sys.exit(1)
    
    server_id = sys.argv[1]
    
    config = get_config()
    server = config.get_server_by_id(server_id)
    
    if not server:
        logger.error(f"Server not found: {server_id}")
        sys.exit(1)
    
    if "dhcp" not in server.services:
        logger.error(f"Server {server_id} does not have DHCP service configured")
        logger.info(f"Configured services: {', '.join(server.services)}")
        sys.exit(1)
    
    success = await test_dhcp_service(server_id)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
