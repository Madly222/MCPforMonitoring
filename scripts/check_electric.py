#!/usr/bin/env python3
"""Cron script to check electricity disconnections."""
import sys
import asyncio
sys.path.insert(0, '/home/user/ServersMonitoringMCP')

from src.monitoring.electric_monitor import check_electric_status

async def main():
    status = await check_electric_status(force=True)
    print(f"Electric check: OK={status.ok}, matches={len(status.matches)}")

if __name__ == "__main__":
    asyncio.run(main())
