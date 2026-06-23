# Architecture

This document explains how MCP Server Monitor is put together: the layers, the
runtime model, and the main data flows. For a quick module map see
[`AGENTS.md`](AGENTS.md); for the high-level picture see the
[README](../README.md).

---

## 1. Runtime model

The system is a **single ASGI process** (Uvicorn running the FastAPI app from
`src.web.app:app`) plus a set of **optional scheduled jobs** invoked by systemd
timers. There is no external message broker, database server, or task queue —
state is held in memory and on disk (YAML config, log files, learned patterns).

```
                         ┌──────────────────────────────┐
                         │  Uvicorn / FastAPI  (:4455)   │
   Browser ── HTTP ─────▶│  auth → REST API → handlers   │
                         │  lifespan → background monitors│
                         └───────────────┬───────────────┘
                                         │ asyncssh / SNMP / SMTP
                                         ▼
        ┌────────────┬────────────┬────────────┬────────────┐
        │ DHCP host  │ DNS host   │ RADIUS host│  ZTE OLT    │  …
        └────────────┴────────────┴────────────┴────────────┘

   systemd timers ──▶ scripts/check_electric.py, acc_monitor.py, …
                      (one-shot processes reading .env)
```

Two execution contexts share the same `src/` code:

1. **The web service** — long-running; serves the API and runs the in-process
   background monitors (log watcher, health checker, updates checker, ONU
   monitor) started in the FastAPI lifespan.
2. **Scheduled one-shots** — short-lived processes launched by systemd timers
   (e.g. `check_electric.py`) that import a monitoring module, do one pass, and
   exit. These read configuration from `.env`.

---

## 2. Layers

### 2.1 Configuration layer (`src/core/config.py`)
A singleton `ConfigLoader` parses YAML into Pydantic models and caches the
result. It is the single source of truth for paths and infrastructure secrets.

- `SecretsConfig` ← `secrets.yaml` (servers, OLTs, Claude, email, web users)
- `SettingsConfig` ← `config/settings.yaml` (intervals, logging, limits)
- per-service dicts ← `config/services/*.yaml`

Automation modules deliberately bypass this layer and read `.env` directly via
`python-dotenv`, keeping business credentials separate from infrastructure.

### 2.2 Core layer (`src/core/`)
- **SSH Manager** — an `asyncssh` connection pool keyed by `server_id`, with
  per-server locks, init-system detection (systemd vs SysVinit), command/sudo
  execution, file reads, and real-time `tail -F` streaming.
- **Claude Client** — wraps the Anthropic API for two tasks: interpreting
  natural-language commands into structured intents, and analyzing unknown log
  errors. Adds response caching and rate limiting.
- **System Info Collector** — gathers OS, hardware, network, security, and
  service data for a host into a `ServerReport`.

### 2.3 Service layer (`src/services/`)
`BaseService` (ABC) defines the contract every handler implements: detect,
status, start/stop/restart/reload, health checks, diagnostics, log access.
Concrete handlers: `DHCPService`, `DNSService`, `RADIUSService`. Service
detection and backend-specific commands are data-driven from
`config/services/*.yaml`.

### 2.4 Monitoring & automation layer (`src/monitoring/`)
Two kinds of components live here:

- **In-process monitors** (started by lifespan): `log_watcher`,
  `error_detector`, `health_checker`, `updates_checker`, `onu_monitor`.
- **Job modules** (invoked on demand by API or by timers): `electric_monitor`,
  `acc_monitor`, `invoice_generator`, `posta_generator`,
  `email_invoice_sender`, `dhcp_mac_sync`.

### 2.5 Web layer (`src/web/`)
FastAPI app factory, three routers (`auth`, main `api`, `api_netbox`),
session-cookie authentication, and static file serving for the dashboard.

### 2.6 Standalone service (`services/netbox-autofill/`)
A self-contained Cisco→NetBox automation used by the NetBox API endpoints.
`orchestrator.py` connects switch data (via `ssh_connector.py`, netmiko with
legacy-cipher support) to NetBox objects (via `netbox_client.py`).

---

## 3. Key data flows

### 3.1 Natural-language command
```
POST /api/execute {command}      (auth: admin)
  │
  ├─ ClaudeClient.interpret_command(text, server_ids) → CommandInterpretation
  │     confidence > 0.7 ?
  │        yes → execute_interpreted_command() → service handler / SSH
  │        no  ↓
  └─ keyword fallback in execute_command():
        "status"        → SystemInfo / per-server connectivity
        "restart"       → resolve service+server → handler.restart()
        "logs"/"errors" → error_detector.get_recent_errors()
        "health"/"check"→ health_checker.get_all_reports()
  →  CommandResponse {success, interpretation, result, source}
```
The fallback guarantees core operations keep working when the Claude API is
unreachable. **Both paths must be kept in sync** when adding capabilities.

### 3.2 Real-time error detection
```
log_watcher (SSH tail -F)  →  LogEvent
  → app.handle_log_event()  →  error_detector.process_event()
       ├─ matches ignore_patterns.yaml? → drop (noise)
       ├─ matches known_errors.yaml?     → DetectedError(pattern, diagnosis)
       │     can_auto_fix() and safe_actions.yaml permits? → (auto-fix stage)
       └─ unknown?                        → candidate for Claude analysis
```
Detected errors are retained in memory and surfaced via
`GET /api/monitoring/errors` and the dashboard.

### 3.3 Health & updates
`health_checker` polls each server/service on an interval and stores the latest
`HealthReport` per server. `updates_checker` runs roughly daily, caches results,
and exposes them via `GET /api/updates/status`. Both start in the lifespan and
stop on shutdown.

### 3.4 ONU / GPON monitoring
`onu_monitor` polls each enabled OLT (`secrets.yaml > onu_monitoring.olts`)
using CLI `snmpwalk` for ONU name/type/status/signal, and SSH for MAC
retrieval. Thresholds (`good`, `warning`) classify optical signal levels.

### 3.5 Invoicing — three independent channels
> ⚠️ **Temporary.** The invoicing feature (both the *generate* and *send-emails*
> buttons and the three modules below) is provisional and scheduled for removal
> from the project. It is documented here only to describe current behavior.

These are **not** a generate-then-send pipeline; each module is self-contained
and targets a different downstream system:

| Channel | Module | Source → Artifact → Delivery | Trigger |
|---------|--------|------------------------------|---------|
| Paynet | `invoice_generator` | SSH runs PHP on billing server → **XLS/XLSX** → **email** (and FTP helper) | `POST /api/invoice/generate` |
| Posta Moldovei | `posta_generator` | billing DB → **XLSX** → **FTP** (posta.md) | `POST /api/invoice/generate` |
| WHMCS | `email_invoice_sender` | billing DB (unpaid invoices for named clients) → **PDF** via WHMCS → **email** | `POST /api/invoice/send-emails` |

Each channel has its own SMTP helper; nothing is shared between them. The
`/api/invoice/generate` endpoint runs the Paynet and Posta channels together.

### 3.6 Utility-outage alerts
`electric_monitor` (Premier Energy) and `acc_monitor` (acc.md) scrape public
outage pages over HTTP (`aiohttp`), match configured addresses/patterns, and
send email alerts. They run both on demand (`/api/electric/check`,
`/api/acc/check`) and on a daily systemd timer.

---

## 4. Concurrency & lifecycle

- The app is fully async. SSH I/O uses `asyncssh`; HTTP scraping uses
  `aiohttp`; automation modules that use `paramiko`/`mysql`/`smtplib` run
  synchronous code and should be treated as blocking.
- Background monitors are created and started in the FastAPI **lifespan**
  context manager (`src/web/app.py`) and stopped on shutdown, after which the
  SSH pool is closed.
- Singletons are obtained through `get_*()` accessors
  (`get_config`, `get_ssh_manager`, `get_claude_client`, `get_log_watcher`,
  `get_health_checker`, `get_updates_checker`, `get_onu_monitor`,
  `get_error_detector`, `get_session_store`).

---

## 5. Persistence

There is no database for application state. Persistence is file-based:

| Data | Location |
|------|----------|
| Infrastructure secrets | `secrets.yaml` |
| Automation secrets | `.env` |
| Runtime settings | `config/settings.yaml` |
| Error patterns / filters | `knowledge_base/*.yaml` |
| Learned patterns | `knowledge_base/learned/` |
| Application logs | `logs/` (rotated, zipped) |
| Invoice artifacts/logs | `invoices_logs/` |
| Sessions | in-memory session store |

---

## 6. Extension points

- **New monitored host** → add to `secrets.yaml > servers[]`.
- **New service handler** → subclass `BaseService`, add `config/services/<name>.yaml`,
  register in the `service_handlers` map in `api.py`.
- **New error pattern** → add to `knowledge_base/known_errors.yaml`.
- **New automation job** → new module in `src/monitoring/`, keys in `.env(.example)`,
  optional systemd `.service` + `.timer` in `scripts/`.
- **New config field** → extend the relevant Pydantic model in `src/core/config.py`.
