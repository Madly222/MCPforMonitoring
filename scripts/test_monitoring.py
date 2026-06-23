#!/usr/bin/env python3
"""
Monitoring Test Script.

Tests log watching and error detection capabilities.
Usage: python scripts/test_monitoring.py <server_id> [duration_seconds]
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from src.core.config import get_config
from src.core.ssh_manager import get_ssh_manager
from src.monitoring.log_watcher import LogWatcher, LogEvent
from src.monitoring.error_detector import ErrorDetector, DetectedError
from src.monitoring.health_checker import HealthChecker


def setup_logging():
    """Configure logging for test script."""
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="DEBUG"
    )


async def handle_log_event(event: LogEvent):
    """Handle log event from watcher."""
    icon = "🔴" if event.event_type.value == "error" else "🟡"
    logger.info(f"{icon} [{event.server_id}:{event.service_type}] {event.line[:100]}")


async def test_health_checker(server_id: str):
    """Test health checker."""
    logger.info("=" * 60)
    logger.info("Testing Health Checker")
    logger.info("=" * 60)
    
    checker = HealthChecker()
    
    report = await checker.check_server(server_id)
    
    logger.info(f"Server: {report.server_id} ({report.host})")
    logger.info(f"Reachable: {report.reachable}")
    logger.info(f"Result: {report.check_result.value}")
    
    if report.system_info:
        logger.info(f"Hostname: {report.system_info.get('hostname', 'N/A')}")
        logger.info(f"Load: {report.system_info.get('load', 'N/A')}")
        logger.info(f"Memory: {report.system_info.get('memory', 'N/A')}")
    
    for service in report.services:
        state_icon = "🟢" if service.get("state") == "running" else "🔴"
        logger.info(f"  {state_icon} {service.get('name', 'unknown')}: {service.get('health', 'unknown')}")
    
    if report.error:
        logger.error(f"Error: {report.error}")
    
    return report.check_result.value == "healthy"


async def test_error_detector():
    """Test error detector with sample events."""
    logger.info("=" * 60)
    logger.info("Testing Error Detector")
    logger.info("=" * 60)
    
    detector = ErrorDetector()
    
    # Test events
    test_events = [
        LogEvent(
            server_id="test-server",
            service_type="dhcp",
            log_file="/var/log/syslog",
            line="dhcpd: No free leases in pool",
            event_type=LogEvent.__class__
        ),
        LogEvent(
            server_id="test-server",
            service_type="postfix",
            log_file="/var/log/mail.log",
            line="postfix/smtp[1234]: fatal: no SASL authentication mechanisms",
            event_type=LogEvent.__class__
        ),
        LogEvent(
            server_id="test-server",
            service_type="dns",
            log_file="/var/log/syslog",
            line="named[5678]: zone example.com/IN: zone expired",
            event_type=LogEvent.__class__
        ),
    ]
    
    from src.monitoring.log_watcher import LogEventType
    
    for event in test_events:
        event.event_type = LogEventType.ERROR
        
        detected = detector.process_event(event)
        
        if detected:
            if detected.pattern:
                logger.success(f"Known error: {detected.pattern.diagnosis}")
                logger.info(f"  Auto-fix: {detected.pattern.auto_fix}")
                if detected.pattern.commands:
                    logger.info(f"  Commands: {detected.pattern.commands}")
            else:
                logger.warning(f"Unknown error: {event.line[:50]}...")
    
    stats = detector.get_error_stats()
    logger.info(f"Stats: {stats}")
    
    return True


async def test_log_watcher(server_id: str, duration: int = 30):
    """Test log watcher."""
    logger.info("=" * 60)
    logger.info(f"Testing Log Watcher (duration: {duration}s)")
    logger.info("=" * 60)
    
    ssh = get_ssh_manager()
    watcher = LogWatcher(ssh)
    detector = ErrorDetector()
    
    events_received = []
    
    async def combined_handler(event: LogEvent):
        """Handle and detect errors."""
        events_received.append(event)
        await handle_log_event(event)
        
        detected = detector.process_event(event)
        if detected and detected.pattern:
            logger.success(f"  → Matched: {detected.pattern.diagnosis[:50]}...")
    
    watcher.add_handler(combined_handler)
    
    try:
        await watcher.start()
        
        logger.info(f"Watching {len(watcher.watched_files)} log file(s)")
        for f in watcher.watched_files:
            logger.info(f"  - {f}")
        
        logger.info(f"Waiting {duration} seconds for log events...")
        logger.info("(Generate some activity on the server to see events)")
        
        await asyncio.sleep(duration)
        
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        await watcher.stop()
        await ssh.close()
    
    logger.info(f"Total events received: {len(events_received)}")
    
    return True


async def main():
    """Main entry point."""
    setup_logging()
    
    logger.info("MCP Server Monitor - Monitoring Test")
    logger.info("=" * 60)
    
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_monitoring.py <server_id> [duration_seconds]")
        print("Example: python scripts/test_monitoring.py dhcp-primary 60")
        sys.exit(1)
    
    server_id = sys.argv[1]
    duration = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    
    config = get_config()
    server = config.get_server_by_id(server_id)
    
    if not server:
        logger.error(f"Server not found: {server_id}")
        sys.exit(1)
    
    # Test error detector (no server needed)
    await test_error_detector()
    
    # Test health checker
    await test_health_checker(server_id)
    
    # Test log watcher
    await test_log_watcher(server_id, duration)
    
    logger.info("=" * 60)
    logger.info("Monitoring test complete")


if __name__ == "__main__":
    asyncio.run(main())
