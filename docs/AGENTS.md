# AGENTS.md — Project Onboarding Map

> Purpose: let a developer **or an AI assistant** become productive on this
> codebase in minutes, without re-deriving the architecture from scratch.
> If you are an AI joining in a fresh chat, read this file first, then
> `README.md`, then the specific module you're touching.

---

## 1. What this project is (one paragraph)

A FastAPI service that monitors a fleet of Linux servers over SSH, detects log
errors against a YAML knowledge base, runs natural-language operator commands
through the Claude API (with a keyword fallback), manages DHCP/DNS/RADIUS
services, monitors GPON ONUs over SNMP, and runs a set of scheduled automation
jobs (utility-outage alerts, invoice generation/delivery, NetBox MAC sync).
Single ASGI process on **port 4455** + optional systemd timers.

---

## 2. Entry points & how to run

| What | Command |
|------|---------|
| Run the app | `python -m src.main` (or `./scripts/run.sh`) |
| ASGI target | `src.web.app:app` (Uvicorn, started from `main.py`) |
| App factory | `create_app()` in `src/web/app.py` |
| Background monitors | started in the FastAPI `lifespan` handler in `app.py` |

`main.py` → sets up logging → `check_configuration()` → `uvicorn.run("src.web.app:app", host, port)`.
Host/port come from `secrets.yaml > mcp_server`.

---

## 3. ⚠️ Gotchas — read before changing anything

1. **Two secret layers, not one.**
   - `secrets.yaml` → infrastructure (servers, SSH, Claude, web users, OLTs). Loaded via Pydantic in `src/core/config.py`.
   - `.env` → automation (SMTP, FTP, billing DB, NetBox token). Loaded via `python-dotenv` **inside individual monitoring modules**, not centrally.
   - Both are gitignored. Templates: `secrets.example.yaml`, `.env.example`.

2. **`requirements.txt` historically drifted from real imports.** The corrected file includes `aiohttp`, `python-dotenv`, `paramiko`, `netmiko`, `pynetbox`, `requests`, `scp`, `openpyxl`, `fpdf2`. If you add a dependency, add it there too.

3. **Only DHCP / DNS / RADIUS have real handler classes.** Postfix, Dovecot, Apache, SpamAssassin appear in config and keyword maps but fall back to generic `ssh.restart_service(...)`. Don't assume a `PostfixService` exists.

4. **System binaries are runtime deps.** `snmpwalk` (ONU), `mysql` client (billing), `ssh`. Code shells out to them. Missing binary = silent feature failure, not an import error.

5. **Config objects are singletons.** Access via `get_*()` accessors; never instantiate loaders directly. `ConfigLoader` caches secrets/settings — call `get_config().reload()` to invalidate.

6. **CORS is wide open (`*`).** Intentional for LAN use; tighten before exposing.

7. **`*.bak` files exist** (e.g. `email_invoice_sender.py.bak`). Ignore them; they're not imported.

8. **Invoicing is a temporary feature.** `invoice_generator.py`, `posta_generator.py`, `email_invoice_sender.py` and the endpoints `/api/invoice/generate` and `/api/invoice/send-emails` are provisional and will be removed. Don't extend them or depend on them.

---

## 4. Module reference

### Core (`src/core/`)
| File | Role | Key symbols |
|------|------|-------------|
| `config.py` | All config models + loader (Pydantic over YAML). Defines paths (`PROJECT_ROOT`, `SECRETS_FILE`, `KEYS_DIR`, …). | `ConfigLoader`, `get_config()`, `SecretsConfig`, `ServerConfig`, `OLTConfig`, `SettingsConfig` |
| `ssh_manager.py` | Async SSH connection pool; command exec, sudo, service control, log tailing, init-system detection. | `SSHManager`, `get_ssh_manager()`, `CommandResult`, `InitSystem` |
| `claude_client.py` | Claude API: `interpret_command()` (NL→intent), `analyze_error()`. Caching + rate limiting. | `ClaudeClient`, `get_claude_client()`, `CommandInterpretation`, `AnalysisResult` |
| `system_info.py` | Collects OS/hardware/network/security/services report from a host. | `SystemInfoCollector`, `ServerReport`, `report_to_dict()` |

### Services (`src/services/`)
| File | Role |
|------|------|
| `base.py` | `BaseService` ABC: status/restart/start/stop/reload/health/diagnostics/log access. All handlers extend it. |
| `dhcp.py` | isc-dhcp-server / kea-dhcp4 / dnsmasq; lease parsing, health. |
| `dns.py` | bind9 / dnsmasq / unbound / PowerDNS; zones, `query()` diagnostic. |
| `radius.py` | FreeRADIUS; version, config, health. |

### Monitoring & automation (`src/monitoring/`)
| File | Role | Reads |
|------|------|-------|
| `log_watcher.py` | SSH `tail -F`, emits `LogEvent`s. | servers |
| `error_detector.py` | Match events to patterns, dedup, decide auto-fix. | `knowledge_base/` |
| `health_checker.py` | Periodic per-service health reports. | settings |
| `updates_checker.py` | Daily update availability (24h cache). | settings |
| `onu_monitor.py` | ZTE C320 ONU via CLI `snmpwalk` + SSH for MAC. | `secrets.yaml` OLTs |
| `electric_monitor.py` | Premier Energy outage scrape + email. | `.env`, `config/electric_addresses.txt` |
| `acc_monitor.py` | acc.md water outage scrape + email. | `.env` |
| `invoice_generator.py` ⚠️ | SSH to billing → run PHP → fetch XLS → email (Paynet). **Temporary, to be removed.** | `.env`, `config/invoice_clienti_email.txt` |
| `posta_generator.py` ⚠️ | Billing DB → XLSX → FTP to posta.md. **Temporary, to be removed.** | `.env`, `config/postamoldovei_clienti.txt` |
| `email_invoice_sender.py` ⚠️ | Billing DB → PDF (fpdf2) → email (WHMCS). **Temporary, to be removed.** | `.env` |
| `dhcp_mac_sync.py` | phpDHCPAdmin MySQL → NetBox MAC sync. | `.env` |

### Web (`src/web/`)
| File | Role |
|------|------|
| `app.py` | FastAPI factory, CORS, router mounting, static files, lifespan (starts/stops monitors). |
| `api.py` | Main REST API (~1.4k lines): status, servers, actions, `/execute`, monitoring, updates, ONU, utilities, invoicing. Holds the `service_handlers` map. |
| `api_netbox.py` | NetBox auto-fill endpoints (scan/apply/auto, router variants, sync-mac). |
| `auth.py` | bcrypt auth, session store, `get_current_user`, `require_admin`, login/logout. |

### Standalone service (`services/netbox-autofill/`)
Cisco switch → NetBox automation (separate from `src/`). `orchestrator.py` ties `ssh_connector.py` (netmiko, legacy ciphers) to `netbox_client.py` (pynetbox/REST). Uses `SSH_USERNAME`/`SSH_PASSWORD` from `.env`.

### Frontend (`web/`)
Plain HTML/CSS/JS, no build. `index.html` (dashboard), `netbox.html`, `login.html`; `js/app.js`, `js/api.js`, `js/onu.js`, `js/login.js`.

---

## 5. The `/api/execute` command pipeline (most important flow)

```
POST /api/execute  (auth: admin)
  └─ claude.interpret_command(text, server_ids)
       ├─ confidence > 0.7 → execute_interpreted_command(...) → handler/SSH
       └─ else / API error → keyword fallback:
            "status"  → system info / per-server status
            "restart" → resolve service+server → handler.restart() or ssh.restart_service()
            "logs"/"errors" → error_detector.get_recent_errors()
            "health"/"check" → health_checker.get_all_reports()
```
When adding command capabilities, update **both** the Claude path (`execute_interpreted_command`) and the keyword fallback so behavior is consistent when the API is down.

---

## 6. Config files cheat-sheet

| File | Purpose |
|------|---------|
| `secrets.yaml` | servers, SSH/sudo, Claude key, web users, email, OLTs |
| `.env` | automation: SMTP, FTP, billing DB, NetBox, recipients |
| `config/settings.yaml` | intervals, error processing, cache/rate-limit, logging |
| `config/safe_actions.yaml` | auto-remediation risk policy (levels 0–3) |
| `config/services/*.yaml` | per-service detection commands |
| `config/electric_addresses.txt` | power-outage watch list |
| `config/*_clienti*.txt` | invoice recipient lists |
| `knowledge_base/known_errors.yaml` | regex error patterns + diagnoses |
| `knowledge_base/ignore_patterns.yaml` | log noise filters |

---

## 7. Common tasks → where to go

| Task | Start here |
|------|-----------|
| Add a monitored server | `secrets.yaml > servers[]` |
| Add a new service type | `src/services/<name>.py` + `config/services/<name>.yaml` + `service_handlers` in `api.py` |
| Add an error pattern | `knowledge_base/known_errors.yaml` |
| Change an interval/threshold | `config/settings.yaml` |
| Add an API endpoint | `src/web/api.py` (or `api_netbox.py`) |
| Change auth/roles | `src/web/auth.py` |
| Add an env-driven automation job | new module in `src/monitoring/` + keys in `.env(.example)` + (optional) systemd timer in `scripts/` |
| Add a config field | add to the Pydantic model in `src/core/config.py` |

---

## 8. Runtime / gitignored paths (not in repo)
`venv/`, `keys/`, `sessions/`, `logs/`, `invoices_logs/`, `secrets.yaml`, `.env`, `__pycache__/`.
The app creates `logs/` and expects `keys/` to hold SSH private keys (chmod 600).

---

## 9. Versions & defaults
- App version: `1.0.0` (set in `main.py` / `app.py`).
- Default Claude model: `claude-sonnet-4-20250514` (in `secrets.yaml > claude.model`).
- Default web port: `4455`.
- Python: `3.10+`.
