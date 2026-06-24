# AGENTS.md — Project Onboarding Map

> Purpose: let a developer **or an AI assistant** become productive on this
> codebase in minutes, without re-deriving the architecture from scratch.
> If you are an AI joining in a fresh chat, read this file first, then
> `README.md`, then the specific module you're touching.

---

## 1. What this project is (one paragraph)

A FastAPI service that monitors a fleet of Linux servers over SSH, detects log
errors against a YAML knowledge base, runs operator commands (a raw SSH console
plus a natural-language interpreter backed by Claude with a keyword fallback),
manages DHCP/DNS/RADIUS services, monitors GPON ONUs over SNMP, and runs
scheduled automation jobs (utility-outage alerts, invoice delivery, NetBox MAC
sync). It has a **superadmin web console** with three roles, an **audit log**,
and **runtime editing** of users, servers, OLTs, and outage/notification
settings. Single ASGI process on **port 4455** + optional systemd timers.

---

## 2. Entry points & how to run

| What | Command |
|------|---------|
| Run the app | `python -m src.main` (or `./scripts/run.sh`) |
| ASGI target | `src.web.app:app` (Uvicorn, started from `main.py`) |
| App factory | `create_app()` in `src/web/app.py` |
| Background monitors | started in the FastAPI `lifespan` handler in `app.py` |
| Manage users from CLI | `python scripts/manage_users.py {list,add,passwd,role,delete}` |
| Check Claude key/model | `python scripts/check_claude.py` |

`main.py` → sets up logging → `check_configuration()` → `uvicorn.run("src.web.app:app", host, port)`.
Host/port come from `secrets.yaml > mcp_server`.

---

## 3. ⚠️ Gotchas — read before changing anything

1. **Three config layers now.**
   - `secrets.yaml` → infrastructure (servers, SSH, Claude, web users, OLTs). Pydantic-loaded in `src/core/config.py`.
   - `.env` → automation defaults (SMTP, FTP, billing DB, NetBox). Read via `python-dotenv` in monitoring modules.
   - `sessions/runtime_settings.json` → **web-edited overrides** (see #2). Gitignored.

2. **Seed-and-own runtime stores.** On first run, users, servers and OLTs are
   **seeded from `secrets.yaml`** into writable stores, which then become the
   **source of truth**:
   - Users → `sessions/users.json` (`src/web/users.py`)
   - Servers & OLTs → `sessions/runtime_settings.json` (merged into
     `config.load_secrets()` by `_merge_runtime_overrides`)
   After seeding, **editing `secrets.yaml` no longer takes effect** for those —
   manage them in the web UI (or delete the relevant key/file to re-seed).
   The merge is wrapped in try/except: a corrupt store never breaks startup
   (falls back to `secrets.yaml`).

3. **Outage settings are read live.** `electric_monitor` / `acc_monitor` now read
   email/SMTP config and the water pattern from `runtime_config` on each run
   (with `.env` fallback), so web edits apply **without restart**. Server/OLT
   edits need a restart (SSH pool + monitors initialise at startup).

4. **`requirements.txt`** must include all real imports: `aiohttp`,
   `python-dotenv`, `paramiko`, `netmiko`, `pynetbox`, `requests`, `scp`,
   `openpyxl`, `fpdf2`, `bcrypt`. Add new deps there.

5. **Only DHCP / DNS / RADIUS have real handler classes.** Postfix/Dovecot/
   Apache/SpamAssassin fall back to generic `ssh.restart_service(...)`.

6. **System binaries are runtime deps.** `snmpwalk`, `mysql` client, `ssh`.
   Note: monitored hosts may be **SysVinit, not systemd** — `systemctl` may not
   exist there; use `service`/`/etc/init.d`. The init type is per-server.

7. **Config objects are singletons.** Access via `get_*()`; `get_config().reload()`
   to invalidate the cached secrets.

8. **CORS is wide open (`*`).** LAN-only assumption; tighten before exposing.

9. **Invoicing is a temporary feature** (`invoice_generator`, `posta_generator`,
   `email_invoice_sender`, `/api/invoice/*`). Scheduled for removal. The invoice
   buttons are **operator-only** by current policy.

10. **Default Claude model `claude-sonnet-4-20250514` is deprecated** (404
    not_found). Set a current model in `secrets.yaml > claude.model` (e.g.
    `claude-sonnet-4-6`); run `scripts/check_claude.py` to verify.

---

## 4. Module reference

### Core (`src/core/`)
| File | Role | Key symbols |
|------|------|-------------|
| `config.py` | Config models + loader (Pydantic over YAML). Merges runtime server/OLT overrides. | `ConfigLoader`, `get_config()`, `SecretsConfig`, `ServerConfig`, `OLTConfig`, `_merge_runtime_overrides` |
| `ssh_manager.py` | Async SSH pool; `execute`, `execute_sudo` (sets PATH), service control, log tailing, init detection. | `SSHManager`, `get_ssh_manager()`, `CommandResult` |
| `claude_client.py` | Claude API: `interpret_command`, `analyze_error`. Cache + rate limit. | `ClaudeClient`, `get_claude_client()` |
| `system_info.py` | OS/hardware/network report from a host. | `SystemInfoCollector`, `ServerReport` |

### Web (`src/web/`)
| File | Role |
|------|------|
| `app.py` | FastAPI factory, CORS, router mounting (incl. `admin_router` at `/api/admin`), lifespan. |
| `api.py` | Main REST API: status, servers, actions, `/execute`, `/console/exec` (raw SSH), `/claude/health`, monitoring, updates, ONU, utilities, invoicing. Audits commands/actions. |
| `api_netbox.py` | NetBox auto-fill endpoints. |
| `auth.py` | bcrypt auth via user store, sessions, `get_current_user`, `require_admin` (admin+superadmin), `require_superadmin`, login/logout audit. |
| **`users.py`** | Runtime user store (`sessions/users.json`), seeded from secrets. `get_user_store()`, verify/add/delete/set_role/set_password. Roles in `VALID_ROLES`. |
| **`audit.py`** | Append-only audit log (`logs/audit.jsonl`). `get_audit_logger().log(...)`, `.query(...)`. |
| **`admin.py`** | `/api/admin/*` superadmin endpoints: user CRUD, audit read, settings (notifications/pattern/addresses), server CRUD, OLT CRUD, config reload. |
| **`runtime_config.py`** | Writable runtime store: notification configs (live), ACC pattern, electric addresses, server & OLT stores (seed-and-own). |

### Services (`src/services/`)
`base.py` (`BaseService` ABC), `dhcp.py`, `dns.py`, `radius.py`. Registered in the
`service_handlers` map in `api.py`.

### Monitoring & automation (`src/monitoring/`)
`log_watcher`, `error_detector`, `health_checker`, `updates_checker`, `onu_monitor`
(in-process monitors); `electric_monitor`, `acc_monitor` (read settings live from
`runtime_config`); `invoice_generator`/`posta_generator`/`email_invoice_sender` ⚠️
(temporary), `dhcp_mac_sync`.

### Scripts (`scripts/`)
`manage_users.py` (user CLI / recovery), `check_claude.py` (Claude key/model
diagnostic), plus test scripts and systemd units.

### Frontend (`web/`)
Plain HTML/CSS/JS, no build. `index.html` (dashboard + console + 🤖 Claude health
indicator + header buttons), `netbox.html`, `login.html`. JS: `app.js`, `api.js`
(`API.admin.*`, `API.console.*`, `API.claude.*`), `onu.js`, `admin.js` (Admin tab:
Settings, Servers, OLTs, Users, Audit), `login.js`.

---

## 5. Roles & permissions

| Capability | operator | admin | superadmin |
|------------|:--------:|:-----:|:----------:|
| View dashboard / status | ✅ | ✅ | ✅ |
| Run commands (`/execute`), service actions, SSH console | | ✅ | ✅ |
| Invoice buttons (`/api/invoice/*`) | ✅ **only** | | |
| App restart (`/api/service/restart`) | | | ✅ **only** |
| Admin panel: users, audit, settings, servers, OLTs (`/api/admin/*`) | | | ✅ |

Dependencies: `require_admin` (admin+superadmin), `require_superadmin`. Invoice and
app-restart use inline exclusive checks in `api.py`. Frontend hides buttons by role
(see the script block in `index.html` and role checks in `app.js`).

---

## 6. Command flows

**Raw SSH console** (preferred for real shell access):
`POST /api/console/exec {server_id, command, sudo}` → `ssh.execute[_sudo]` →
returns `{stdout, stderr, exit_code}`. Non-sudo commands get a PATH prefix so
`systemctl`/`ss`/`ip` resolve. Audited as `console_exec`.

**Interpret mode** (`POST /api/execute`, admin):
Claude `interpret_command` → if confidence > 0.7 run it, else keyword fallback
(`status`/`restart`/`logs`|`errors`/`health`). `source` = `claude`|`local`.
> Known limitation / next task: `logs`/`errors` map to `error_detector`, not real
> server logs, and the fallback is systemd-centric. The intended design is a
> **capability-aware command resolver**: detect each server's init/distro once
> (cached), serve simple intents from a template registry (0 tokens), and use
> Claude only as a fallback that caches the resolved intent→command per server.

---

## 7. Config & data cheat-sheet

| File | Purpose | Committed? |
|------|---------|-----------|
| `secrets.yaml` | infra: servers, SSH, Claude, web users, OLTs (seed source) | ❌ |
| `.env` | automation defaults | ❌ |
| `sessions/users.json` | runtime user store (source of truth after seed) | ❌ |
| `sessions/runtime_settings.json` | notifications, ACC pattern, server & OLT overrides | ❌ |
| `config/settings.yaml` | intervals, logging, cache/rate-limit | ✅ |
| `config/safe_actions.yaml` | auto-remediation risk policy | ✅ |
| `config/services/*.yaml` | per-service detection | ✅ |
| `config/electric_addresses.txt` | electric watch list (web-editable) | ✅ |
| `logs/audit.jsonl` | audit log | ❌ |
| `knowledge_base/*.yaml` | error patterns / noise filters | ✅ |

---

## 8. Common tasks → where to go

| Task | Start here |
|------|-----------|
| Add/edit a monitored server | Web UI (Admin → Servers) → `runtime_config` + `secrets.yaml` seed |
| Add/edit an OLT | Web UI (Admin → OLTs) |
| Add a new service type | `src/services/<name>.py` + `config/services/<name>.yaml` + `service_handlers` in `api.py` |
| Add an admin endpoint | `src/web/admin.py` (superadmin) |
| Add an audited action | `get_audit_logger().log(...)` in the endpoint |
| Change roles/permissions | `src/web/auth.py` + inline checks in `api.py` + frontend visibility |
| Edit outage email/addresses/pattern | Web UI (Admin → Settings) → `runtime_config` |
| Fix Claude not working | `scripts/check_claude.py`; update `secrets.yaml > claude.model` |
| Add a config field | Pydantic model in `src/core/config.py` |

---

## 9. Runtime / gitignored paths (not in repo)
`venv/`, `keys/`, `sessions/` (users.json, runtime_settings.json), `logs/`
(audit.jsonl), `invoices_logs/`, `secrets.yaml`, `.env`, `__pycache__/`.

---

## 10. Versions & defaults
- App version `1.0.0`; web port `4455`; Python `3.10+`.
- `secrets.yaml > claude.model` — set a **current** model (the old
  `claude-sonnet-4-20250514` returns 404).
- Roles: `operator` < `admin` < `superadmin`.
