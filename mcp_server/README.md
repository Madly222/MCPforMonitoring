# MCP server

A [Model Context Protocol](https://modelcontextprotocol.io) server that lets MCP clients
(Claude Desktop, Claude Code, any MCP-compatible agent) query the monitor in natural language:
*"which servers are down?"*, *"any DNS errors in the last 30 minutes?"*, *"which ONUs have weak signal?"*,
*"will a power outage hit any of our sites this week?"*.

## Design

```mermaid
flowchart LR
    C[MCP client<br/>Claude Desktop / Claude Code] -- stdio / MCP --> M[mcp_server/server.py]
    M -- HTTP + session cookie --> A[FastAPI app :4455]
    A -- SSH / SNMP / CLI --> I[Servers & OLTs]
```

- **Thin client of the REST API.** The FastAPI app stays the single owner of SSH sessions,
  monitors and caches; the MCP server only logs in and calls existing endpoints.
- **Read-only by design.** Only status/inspection tools are exposed. Actions that change
  state (restarts, console commands) stay in the web UI, behind roles and the audit log.
- **Least privilege.** Use a dedicated `operator` account; every request is attributed to it.
- **Separate virtualenv.** The `mcp` SDK needs newer `pydantic`/`httpx` than the app pins,
  so the MCP server has its own `requirements.txt` and does not touch the app's environment.

## Tools

| Tool | API endpoint | What it returns |
|---|---|---|
| `get_overall_status` | `GET /api/status` | Infrastructure summary |
| `list_servers` | `GET /api/servers` | Servers, connection state, services |
| `get_server` | `GET /api/servers/{id}` | One server's details |
| `get_server_system_info` | `GET /api/servers/{id}/info` | OS, uptime, CPU, memory, disk (via SSH) |
| `get_recent_errors` | `GET /api/monitoring/errors` | Log errors in the last N minutes |
| `get_health_reports` | `GET /api/monitoring/health` | Latest health-check reports |
| `get_onu_status` | `GET /api/onu/status` | All ONUs, status and optical levels |
| `list_olts` | `GET /api/onu/olts` | Configured OLTs |
| `get_olt_onus` | `GET /api/onu/olt/{id}` | ONUs of one OLT |
| `get_power_outages` | `GET /api/electric/status` | Planned outages affecting network sites |

## Setup

```bash
# 1. A dedicated read-only account in the monitor
python scripts/manage_users.py add mcp '<strong-password>' operator

# 2. Separate virtualenv for the MCP server
python3 -m venv mcp_server/.venv
mcp_server/.venv/bin/pip install -r mcp_server/requirements.txt

# 3. Smoke test with the MCP Inspector (needs Node.js)
MONITOR_URL=http://127.0.0.1:4455 MONITOR_USER=mcp MONITOR_PASSWORD='<strong-password>' \
  npx @modelcontextprotocol/inspector mcp_server/.venv/bin/python mcp_server/server.py
```

### Claude Desktop / Claude Code

```json
{
  "mcpServers": {
    "network-monitor": {
      "command": "/home/user/ServersMonitoringMCP/mcp_server/.venv/bin/python",
      "args": ["/home/user/ServersMonitoringMCP/mcp_server/server.py"],
      "env": {
        "MONITOR_URL": "http://127.0.0.1:4455",
        "MONITOR_USER": "mcp",
        "MONITOR_PASSWORD": "<strong-password>"
      }
    }
  }
}
```

For Claude Code: `claude mcp add network-monitor --env MONITOR_USER=mcp --env MONITOR_PASSWORD=... -- <python> mcp_server/server.py`.

| Variable | Default | Meaning |
|---|---|---|
| `MONITOR_URL` | `http://127.0.0.1:4455` | Base URL of the running monitor |
| `MONITOR_USER` / `MONITOR_PASSWORD` | — | Monitor account (role `operator` is enough) |
| `MONITOR_TIMEOUT` | `30` | HTTP timeout, seconds |
