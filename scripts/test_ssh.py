#!/usr/bin/env python3
"""
SSH Connection Test Script.

Tests SSH connectivity to configured servers.
Usage: python scripts/test_ssh.py [server_id]
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from src.core.config import get_config, SECRETS_FILE
from src.core.ssh_manager import get_ssh_manager


def setup_logging():
    """Configure logging for test script."""
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="DEBUG"
    )


async def test_single_server(server_id: str) -> bool:
    """Test connection to a single server."""
    config = get_config()
    ssh = get_ssh_manager()
    
    server = config.get_server_by_id(server_id)
    if not server:
        logger.error(f"Server not found: {server_id}")
        return False
    
    logger.info(f"Testing connection to {server_id} ({server.host}:{server.port})")
    logger.info(f"  User: {server.user}")
    logger.info(f"  Auth: {server.auth_type}")
    logger.info(f"  Distro: {server.distro}")
    logger.info(f"  Services: {', '.join(server.services)}")
    
    if not server.enabled:
        logger.warning(f"Server {server_id} is disabled in config")
        return False
    
    try:
        success = await ssh.test_connection(server_id)
        
        if success:
            logger.success(f"Connection to {server_id} successful!")
            
            logger.info("Fetching system info...")
            info = await ssh.get_system_info(server_id)
            
            logger.info(f"  Hostname: {info.get('hostname', 'unknown')}")
            logger.info(f"  Init system: {info.get('init_system', 'unknown')}")
            logger.info(f"  Uptime: {info.get('uptime', 'unknown')}")
            logger.info(f"  Load: {info.get('load', 'unknown')}")
            logger.info(f"  Memory: {info.get('memory', 'unknown')}")
            logger.info(f"  Disk: {info.get('disk', 'unknown')}")
            
            for service in server.services:
                logger.info(f"Checking service: {service}")
                service_config = config.load_service_config(service)
                
                detection = service_config.get("detection", {}).get("commands", [])
                for det in detection:
                    result = await ssh.execute(server_id, det["check"], timeout=10.0)
                    if result.success and "found" in result.stdout:
                        service_name = det["service_name"]
                        process_name = det.get("process_name", service_name)
                        
                        logger.success(f"  Found: {det['name']}")
                        logger.info(f"    Service name: {service_name}")
                        logger.info(f"    Process name: {process_name}")
                        
                        status = await ssh.check_service_status(
                            server_id, 
                            service_name,
                            process_name
                        )
                        
                        state = "running" if status.running else "stopped"
                        logger.info(f"    Status: {state}")
                        logger.info(f"    Enabled: {status.enabled}")
                        if status.pid:
                            logger.info(f"    PID: {status.pid}")
                        
                        file_paths = service_config.get("file_paths", {}).get(det["name"], {})
                        
                        if file_paths.get("config"):
                            config_file = await ssh.find_existing_file(
                                server_id, 
                                file_paths["config"]
                            )
                            if config_file:
                                logger.info(f"    Config: {config_file}")
                        
                        if file_paths.get("leases"):
                            leases_file = await ssh.find_existing_file(
                                server_id, 
                                file_paths["leases"]
                            )
                            if leases_file:
                                logger.info(f"    Leases: {leases_file}")
                        
                        break
                else:
                    logger.warning(f"  Service {service} not detected")
            
            return True
        else:
            logger.error(f"Connection to {server_id} failed")
            return False
            
    except Exception as e:
        logger.error(f"Connection error: {e}")
        return False
    finally:
        await ssh.close()


async def test_all_servers() -> dict:
    """Test connection to all enabled servers."""
    config = get_config()
    results = {}
    
    servers = config.get_enabled_servers()
    
    if not servers:
        logger.warning("No enabled servers found in configuration")
        return results
    
    logger.info(f"Testing {len(servers)} enabled server(s)")
    logger.info("-" * 50)
    
    for server in servers:
        results[server.id] = await test_single_server(server.id)
        logger.info("-" * 50)
    
    return results


async def main():
    """Main entry point."""
    setup_logging()
    
    logger.info("MCP Server Monitor - SSH Connection Test")
    logger.info("=" * 50)
    
    if not SECRETS_FILE.exists():
        logger.error(f"Secrets file not found: {SECRETS_FILE}")
        logger.info("Please copy secrets.example.yaml to secrets.yaml and configure it")
        sys.exit(1)
    
    if len(sys.argv) > 1:
        server_id = sys.argv[1]
        success = await test_single_server(server_id)
        sys.exit(0 if success else 1)
    else:
        results = await test_all_servers()
        
        logger.info("=" * 50)
        logger.info("Summary:")
        
        success_count = sum(1 for r in results.values() if r)
        total_count = len(results)
        
        for server_id, success in results.items():
            status = "OK" if success else "FAILED"
            logger.info(f"  {server_id}: {status}")
        
        logger.info(f"Total: {success_count}/{total_count} servers connected")
        
        sys.exit(0 if success_count == total_count else 1)


if __name__ == "__main__":
    asyncio.run(main())
