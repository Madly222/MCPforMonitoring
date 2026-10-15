"""
MCP server for MCP Server Monitor.

Exposes the monitor's state to MCP clients (Claude Desktop, Claude Code, ...)
as read-only tools. It is a thin client of the running FastAPI app: it logs in
with a regular user account and calls the REST API, so the app keeps sole
ownership of SSH sessions, monitors and caches.

Run (stdio transport):
    MONITOR_URL=http://127.0.0.1:4455 MONITOR_USER=mcp MONITOR_PASSWORD=... \
        python mcp_server/server.py
"""

import json
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

MONITOR_URL = os.getenv("MONITOR_URL", "http://127.0.0.1:4455").rstrip("/")
MONITOR_USER = os.getenv("MONITOR_USER", "")
MONITOR_PASSWORD = os.getenv("MONITOR_PASSWORD", "")
TIMEOUT = float(os.getenv("MONITOR_TIMEOUT", "30"))

mcp = FastMCP("network-monitor")

_client: httpx.AsyncClient | None = None


async def _login(client: httpx.AsyncClient) -> None:
    """Authenticate and keep the session cookie in the client's jar."""
    if not MONITOR_USER or not MONITOR_PASSWORD:
        raise RuntimeError("MONITOR_USER and MONITOR_PASSWORD must be set")
    resp = await client.post(
        "/api/auth/login",
        json={"username": MONITOR_USER, "password": MONITOR_PASSWORD},
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Login to monitor failed: HTTP {resp.status_code}")


async def _get(path: str, params: dict[str, Any] | None = None) -> str:
    """GET an API path, logging in (again) when the session is missing or expired."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=MONITOR_URL, timeout=TIMEOUT)
        await _login(_client)

    resp = await _client.get(path, params=params)
    if resp.status_code == 401:
        await _login(_client)
        resp = await _client.get(path, params=params)

    if resp.status_code != 200:
        return json.dumps({"error": f"HTTP {resp.status_code}", "detail": resp.text[:500]})
    return json.dumps(resp.json(), ensure_ascii=False, indent=2)


# ==============================================================================
# TOOLS (read-only)
# ==============================================================================

@mcp.tool()
async def get_overall_status() -> str:
    """Overall status of the monitored infrastructure: servers up/down and summary counters."""
    return await _get("/api/status")


@mcp.tool()
async def list_servers() -> str:
    """List monitored servers with their connection state and services (DHCP, DNS, RADIUS, ...)."""
    return await _get("/api/servers")


@mcp.tool()
async def get_server(server_id: str) -> str:
    """Details of one monitored server, including its services and their status."""
    return await _get(f"/api/servers/{server_id}")


@mcp.tool()
async def get_server_system_info(server_id: str) -> str:
    """System information of one server (OS, uptime, CPU, memory, disk) collected over SSH."""
    return await _get(f"/api/servers/{server_id}/info")


@mcp.tool()
async def get_recent_errors(minutes: int = 60) -> str:
    """Errors detected in the servers' logs during the last `minutes` minutes."""
    return await _get("/api/monitoring/errors", {"minutes": minutes})


@mcp.tool()
async def get_health_reports() -> str:
    """Latest periodic health-check reports for all servers."""
    return await _get("/api/monitoring/health")


@mcp.tool()
async def get_onu_status() -> str:
    """Status and optical levels of all GPON ONUs across all OLTs (from the monitor's cache)."""
    return await _get("/api/onu/status")


@mcp.tool()
async def list_olts() -> str:
    """List configured GPON OLTs."""
    return await _get("/api/onu/olts")


@mcp.tool()
async def get_olt_onus(olt_id: str) -> str:
    """ONU status for a single OLT."""
    return await _get(f"/api/onu/olt/{olt_id}")


@mcp.tool()
async def get_power_outages() -> str:
    """Planned electricity outages (Premier Energy notices) that affect monitored network sites."""
    return await _get("/api/electric/status")


@mcp.tool()
async def get_pending_updates() -> str:
    """Pending package updates found on the monitored servers."""
    return await _get("/api/updates/status")


if __name__ == "__main__":
    mcp.run()
