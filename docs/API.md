# REST API Reference

Base URL: `http://<host>:4455`. All endpoints below are under `/api`.
Interactive Swagger UI is served at `/docs` when the app is running.

## Authentication & roles

Authentication is **session-cookie** based. Log in via `/api/auth/login`; the
returned cookie authorizes subsequent requests.

- Most read endpoints require any authenticated user.
- Command/action endpoints require the **`admin`** role
  (`/api/execute`, `/api/updates/refresh`).
- `operator` is read-only.

Dependencies in code: `get_current_user` (any user) and `require_admin`.

---

## Common models

```jsonc
// CommandRequest
{ "command": "restart dhcp on dhcp-primary" }

// CommandResponse
{
  "success": true,
  "interpretation": "Restarting dhcp on dhcp-primary",
  "commands_executed": [ { "command": "...", "output": "..." } ],
  "result": "dhcp restarted successfully",
  "error": null,
  "source": "claude"          // "claude" | "local"
}

// ActionRequest
{ "server_id": "dhcp-primary", "service_type": "dhcp", "action": "restart" }

// ActionResponse
{ "success": true, "message": "...", "output": "..." }
```

---

## Authentication

### POST `/api/auth/login`
Body: `{ "username": "...", "password": "..." }`
Response: `{ "success", "message", "username", "role" }` and sets a session
cookie.

### POST `/api/auth/logout`
Clears the session.

### GET `/api/auth/me`
Returns `{ "username", "role" }` for the current session.

### GET `/api/auth/check`
Lightweight auth probe.

---

## Status & servers

### GET `/api/status`
Overall fleet status — connectivity and service summary across all enabled
servers.

### GET `/api/servers`
List configured servers with basic state.

### GET `/api/servers/{server_id}`
Server detail including detected services and their status.

### GET `/api/servers/{server_id}/info`
Full `ServerReport`: OS, hardware (CPU/RAM/disk), network interfaces, security
posture, and running services.

### POST `/api/servers/{server_id}/action`  · *admin*
Body: `ActionRequest`. Performs a service action (`restart`, `start`, `stop`,
`reload`) via the appropriate handler. Response: `ActionResponse`.

### GET `/api/servers/{server_id}/services/{service_type}/diagnostics/{diagnostic_name}`
Run a named diagnostic for a service (e.g. DNS `query`, DHCP lease checks).
Available diagnostics depend on the service handler.

---

## Commands & monitoring

### POST `/api/execute`  · *admin*
Body: `CommandRequest`. Interprets a natural-language command via Claude; if
confidence ≤ 0.7 or the API fails, falls back to keyword parsing
(`status` / `restart` / `logs` / `health`). Response: `CommandResponse`
(`source` indicates `claude` or `local`).

### POST `/api/service/restart`
Restart a service (simplified entry point).

### GET `/api/monitoring/status`
State of the monitoring subsystem (watcher, health checker, updates checker).

### GET `/api/monitoring/errors`
Recently detected errors (from the log-watch + error-detector pipeline).
Supports a time window.

### GET `/api/monitoring/health`
Latest per-server health reports.

### GET `/api/health`
App liveness probe (no auth-sensitive data).

---

## Updates

### GET `/api/updates/status`
Cached system-update availability across servers (refreshed ~daily).

### POST `/api/updates/refresh`  · *admin*
Force a refresh of update information.

### POST `/api/servers/{server_id}/updates/check`
Check available updates for a single server.

---

## ONU / GPON

### GET `/api/onu/status`
Aggregated ONU status across all enabled OLTs.

### GET `/api/onu/olts`
List configured OLTs.

### GET `/api/onu/olt/{olt_id}`
ONUs on a specific OLT (name, type, status, signal level, MAC).

### POST `/api/onu/olt/{olt_id}/poll`
Poll an OLT immediately rather than waiting for the next interval.

---

## Utilities (outage monitors)

### GET `/api/electric/status`
Latest Premier Energy outage check result.

### POST `/api/electric/check`
Run an electricity-outage check now.

### GET `/api/acc/status`
Latest acc.md water-outage check result.

### POST `/api/acc/check`
Run a water-outage check now.

---

## Invoicing

> ⚠️ **Temporary feature — scheduled for removal.** Both endpoints below and
> their underlying modules are provisional and will be removed from the project
> in a future cleanup. Documented here only to reflect current behavior.

Three independent channels (see
[ARCHITECTURE.md §3.5](ARCHITECTURE.md#35-invoicing--three-independent-channels)).

### POST `/api/invoice/generate`
Runs the **Paynet** channel (`invoice_generator`: SSH → PHP → XLS → email) and
the **Posta Moldovei** channel (`posta_generator`: DB → XLSX → FTP).

### POST `/api/invoice/send-emails`
Runs the **WHMCS** channel (`email_invoice_sender`: queries unpaid invoices for
named clients, generates PDFs via WHMCS, emails them).

---

## NetBox auto-fill

Under `/api/netbox`. All require an authenticated user.

### GET `/api/netbox/health`
NetBox connectivity check.

### POST `/api/netbox/scan`
Body (`ScanRequest`): `{ "connection_type": "ssh", "device_type": "switch",
"host": "...", "username": "...", "password": "..." }`. Scans a device and
returns proposed port/interface changes.

### POST `/api/netbox/apply`
Body (`ApplyRequest`): `{ "host": "...", "selected_ports": ["..."] }`. Applies
the selected changes to NetBox.

### POST `/api/netbox/auto`
One-shot scan + apply.

### POST `/api/netbox/scan-router` · POST `/api/netbox/apply-router`
Router-oriented variants of scan/apply.

### POST `/api/netbox/sync-mac`
Triggers the phpDHCPAdmin (MySQL) → NetBox MAC synchronization.

---

## Notes

- Request/response shapes for some endpoints are dynamic dicts rather than fixed
  Pydantic models; the typed models are `CommandRequest/Response`,
  `ActionRequest/Response`, `ScanRequest`, `ApplyRequest`, and the auth models.
- For exact, always-current schemas, use the live `/docs` (Swagger) endpoint.
- Errors are returned as standard FastAPI JSON error responses with appropriate
  HTTP status codes (401 unauthenticated, 403 insufficient role, 404 unknown
  server/service, 5xx execution failures).

---

## Admin & superadmin endpoints (added)

All under `/api/admin`, **superadmin only** (`require_superadmin`). See AGENTS.md §5.

### Users
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/users` | List users (no hashes) + valid roles |
| POST | `/api/admin/users` | Create `{username,password,role}` |
| DELETE | `/api/admin/users/{username}` | Delete (not self / last superadmin) |
| PUT | `/api/admin/users/{username}/password` | Change password |
| PUT | `/api/admin/users/{username}/role` | Change role |

### Audit
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/audit` | Recent entries; filters `limit,username,action,since` |

### Settings (live, no restart)
| Method | Path | Description |
|--------|------|-------------|
| GET/PUT | `/api/admin/config/notifications/{electric\|acc}` | SMTP server/port/user/password/TLS/from/to/enabled (secrets masked on read) |
| GET/PUT | `/api/admin/config/acc-pattern` | Water (acc.md) regex |
| GET/PUT | `/api/admin/config/electric-addresses` | Electric watch list |

### Servers & OLTs (apply after restart)
| Method | Path | Description |
|--------|------|-------------|
| GET / POST | `/api/admin/config/servers` | List / add server (secrets masked on read, preserved on blank) |
| PUT / DELETE | `/api/admin/config/servers/{id}` | Edit / delete |
| GET / POST | `/api/admin/config/olts` | List / add OLT |
| PUT / DELETE | `/api/admin/config/olts/{id}` | Edit / delete |
| POST | `/api/admin/config/reload` | Reload config from disk |

## Console & diagnostics (added)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/console/exec` | admin | Raw SSH command `{server_id,command,sudo}` → `{stdout,stderr,exit_code}` (audited) |
| GET | `/api/claude/health` | any user | Minimal Claude ping → `{ok,model,error?}` |

## Permission changes (added)
- `/api/service/restart` → **superadmin only**.
- `/api/invoice/generate`, `/api/invoice/send-emails` → **operator only**.

## Audited actions
`login`, `login_failed`, `logout`, `command`, `service_action`, `app_restart`,
`console_exec`, `user_add/delete/role_change/password_change`,
`server_add/edit/delete`, `olt_add/edit/delete`,
`settings_notifications/acc_pattern/electric_addresses`, `config_reload`.
