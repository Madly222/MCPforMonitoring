# Configuration Reference

MCP Server Monitor reads configuration from several files. This document
describes every field. There are **two secret layers** plus runtime settings:

| File | Layer | Loaded by | Committed? |
|------|-------|-----------|-----------|
| `secrets.yaml` | Infrastructure secrets | `src/core/config.py` (Pydantic) | ❌ gitignored |
| `.env` | Automation secrets | `python-dotenv` (per module) | ❌ gitignored |
| `config/settings.yaml` | Runtime behavior | `src/core/config.py` | ✅ |
| `config/safe_actions.yaml` | Auto-remediation policy | error/action layer | ✅ |
| `config/services/*.yaml` | Per-service detection | service handlers | ✅ |
| `config/*.txt` | Data lists (addresses, recipients) | automation modules | ✅ (no secrets) |

Templates `secrets.example.yaml` and `.env.example` ship in the repo — copy and
edit them.

> **Why two secret files (and why `secrets.yaml` is not merged into `.env`)?**
> `.env` is a flat `KEY=value` format suited to simple scalars (SMTP host, FTP
> password, API tokens) — which is exactly what the automation modules need.
> `secrets.yaml` holds **structured** data: lists of servers with nested fields,
> a list of OLTs with SNMPv3 sub-fields, and web users with roles. That shape
> does not fit a flat `.env` without awkward `SERVER_1_HOST=…` conventions, and
> the config loader (`src/core/config.py`) parses the YAML structure via Pydantic
> models. The split is therefore intentional: structured infrastructure config →
> YAML; flat automation scalars → `.env`. If single-file consolidation is ever
> desired, the correct direction is to fold the flat values **into
> `secrets.yaml`** (YAML handles both), not to flatten YAML into `.env`.

---

## 1. `secrets.yaml`

### `servers[]`
Each entry is a host to monitor.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `id` | string | — | Unique identifier used in logs/UI/API |
| `host` | string | — | IP or hostname |
| `port` | int | `22` | SSH port |
| `user` | string | — | SSH username |
| `auth_type` | `key`\|`password` | `key` | Authentication method |
| `auth_value` | string | — | For `key`: filename in `keys/`. For `password`: the password |
| `sudo_password` | string | _none_ | Optional. If omitted with `password` auth, `auth_value` is reused; with `key` auth, passwordless sudo is assumed |
| `distro` | string | _none_ | `debian`, `ubuntu`, `centos`, `rhel`, … (selects package-manager commands) |
| `services` | list | `[]` | e.g. `[dhcp]`, `[dns]`, `[postfix, dovecot, spamfilter]` |
| `enabled` | bool | `true` | Whether to monitor this host |

Available service types: `dhcp`, `dns`, `radius` (full handlers); `postfix`,
`dovecot`, `spamfilter`, `apache` (generic restart/status only).

### `onu_monitoring`
| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `poll_interval` | int | `60` | Seconds between polls |
| `thresholds.good` | float | `-20.0` | dBm above which signal is "good" |
| `thresholds.warning` | float | `-25.0` | dBm below which signal is "critical" |
| `olts[]` | list | `[]` | OLT devices (below) |

Each `olts[]` entry:

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `id` | string | — | Unique OLT id |
| `host` | string | — | OLT IP |
| `port` | int | `161` | SNMP port |
| `community` | string | `public` | SNMP v2c community |
| `version` | `2c`\|`3` | `2c` | SNMP version |
| `vendor` | `zte`\|`huawei` | `zte` | OLT vendor |
| `enabled` | bool | `true` | |
| `ssh_username`/`ssh_password`/`ssh_port` | | | SSH for MAC retrieval |
| `username`/`auth_proto`/`auth_pass`/`priv_proto`/`priv_pass` | | | SNMPv3 only |

### `mcp_server`
| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `web_host` | string | `0.0.0.0` | Bind address |
| `web_port` | int | `4455` | Web/API port |
| `session_secret` | string | — | **Set to a random ≥32-char string** |
| `session_expire_hours` | int | `24` | Session lifetime |

### `claude`
| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `api_key` | string | — | Anthropic API key |
| `model` | string | `claude-sonnet-4-20250514` | Model id |
| `max_tokens` | int | `1024` | Per-request cap |
| `timeout_seconds` | int | `30` | Request timeout |

### `email`
Built-in notification SMTP (separate from the automation channels in `.env`).

| Field | Type | Default |
|-------|------|---------|
| `enabled` | bool | `false` |
| `smtp_host` / `smtp_port` | string / int | `""` / `587` |
| `smtp_user` / `smtp_password` | string | `""` |
| `smtp_tls` | bool | `true` |
| `from_address` | string | `""` |
| `to_addresses` | list | `[]` |

### `web_users[]`
| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `username` | string | — | |
| `password` | string | — | Plaintext on first run is auto-hashed (bcrypt) |
| `role` | `admin`\|`operator` | `operator` | `admin` can execute; `operator` is read-only |

---

## 2. `.env` (automation secrets)

Read directly by the automation modules. Full annotated template:
[`.env.example`](../.env.example). Grouped by feature:

**Electricity outage** (`electric_monitor`): `ELECTRIC_CHECK_INTERVAL`,
`ELECTRIC_EMAIL_ENABLED`, `ELECTRIC_SMTP_SERVER`, `ELECTRIC_SMTP_PORT`,
`ELECTRIC_EMAIL_FROM`, `ELECTRIC_EMAIL_TO`. Watched addresses live in
`config/electric_addresses.txt`.

**Water outage** (`acc_monitor`): `ACC_ADDRESS_PATTERN` (regex),
`ACC_CHECK_INTERVAL`, `ACC_EMAIL_ENABLED`, `ACC_SMTP_SERVER`, `ACC_SMTP_PORT`,
`ACC_SMTP_USER`, `ACC_SMTP_PASSWORD`, `ACC_SMTP_TLS`, `ACC_EMAIL_FROM`,
`ACC_EMAIL_TO`.

**Billing SSH** (Paynet/Posta) ⚠️ *temporary feature*: `INVOICE_SSH_HOST`, `INVOICE_SSH_USER`,
`INVOICE_SSH_PASSWORD`, `INVOICE_SSH_PORT`, `INVOICE_SSH_SCRIPT_DIR`,
`INVOICE_SSH_SCRIPT_CMD`.

**Invoice email**: `INVOICE_EMAIL_FROM`, `INVOICE_EMAIL_TO`, `INVOICE_EMAIL_CC`,
`INVOICE_TEST_MODE`, `INVOICE_TEST_EMAIL`; `email_invoice_sender` overrides:
`EMAIL_INVOICE_TEST_MODE`, `EMAIL_INVOICE_TEST_EMAIL`, `EMAIL_INVOICE_CC`,
`EMAIL_INVOICE_MERGE`. Recipients per client: `config/invoice_clienti_email.txt`.

**Posta FTP**: `INVOICE_FTP_HOST`, `INVOICE_FTP_USER`, `INVOICE_FTP_PASSWORD`,
`INVOICE_FTP_PATH`. Client list: `config/postamoldovei_clienti.txt`.

**Billing DB**: `BILLING_DB_USER`, `BILLING_DB_PASSWORD`, `BILLING_DB_NAME`.

**DHCP→NetBox MAC sync** (`dhcp_mac_sync`): `NETBOX_URL`, `NETBOX_TOKEN`,
`DHCP_SSH_HOST`, `DHCP_SSH_USER`, `DHCP_SSH_PASS`, `DHCP_SSH_PORT`,
`DHCP_MYSQL_USER`, `DHCP_MYSQL_PASS`, `DHCP_MYSQL_DB`.

**Cisco/NetBox auto-fill** (`services/netbox-autofill`): `SSH_USERNAME`,
`SSH_PASSWORD`.

> Many keys have code defaults (e.g. SMTP server, FTP host). Always set them
> explicitly in production rather than relying on defaults baked into the source.

---

## 3. `config/settings.yaml` (runtime behavior)

| Section | Key | Default | Meaning |
|---------|-----|---------|---------|
| `monitoring.realtime` | `enabled` | `true` | Enable SSH log tailing |
| | `reconnect_delay_seconds` | `5` | Delay before reconnect |
| | `max_reconnect_attempts` | `10` | Reconnect cap |
| `monitoring.polling` | `interval_seconds` | `300` | Fallback poll interval |
| `monitoring.health_check` | `interval_seconds` | `60` | Health check cadence |
| | `timeout_seconds` | `10` | Per-check timeout |
| `monitoring.aggregation` | `wait_seconds` | `30` | Batch wait before analysis |
| | `max_errors_per_batch` | `10` | Batch size cap |
| `error_processing` | `dedup_window_seconds` | `300` | Ignore identical errors within window |
| | `min_severity` | `warning` | Minimum severity to process |
| | `context_lines` | `50` | Context collected per error |
| `claude_optimization.cache` | `enabled` / `ttl_hours` | `true` / `24` | Response cache |
| `claude_optimization.rate_limit` | `max_requests_per_minute` / `_per_hour` | `10` / `100` | API throttling |
| `logging` | `level` | `INFO` | DEBUG/INFO/WARNING/ERROR/CRITICAL |
| | `rotation.max_size_mb` / `backup_count` | `10` / `5` | Log rotation |
| | `format` | _loguru fmt_ | Log line format |
| `web_ui` | `static_dir` | `web` | Static files dir |
| | `rate_limit.requests_per_minute` | `60` | API rate limit |
| `incidents` | `storage.format` / `directory` | `json` / `logs/incidents` | Incident storage |
| | `retention_days` | `90` | Incident retention |

If `settings.yaml` is missing or invalid, the app logs a warning and falls back
to these defaults.

---

## 4. `config/safe_actions.yaml` (auto-remediation policy)

Defines which remediation actions may run automatically, gated by **risk level**:

| Level | Meaning |
|-------|---------|
| 0 | Read-only / status |
| 1 | Low (restart service, reload config) |
| 2 | Medium (clear queues, flush cache) |
| 3 | High (modify config, delete data) — **never auto-executed** |

Sections:
- `auto_execute` — actions allowed without confirmation (`max_risk_level: 1` by
  default), each with `allowed_services`, `cooldown_seconds`,
  `max_attempts_per_hour`.
- `notify_and_execute` — notify first, then execute (`max_risk_level: 2`), gated
  by `conditions`.
- `never_auto_execute` — always require manual confirmation (config/zone/firewall
  changes, deletions, account/network/cert changes).
- `limits` — global rate caps and backoff.

---

## 5. `config/services/*.yaml`

One file per service type (`dhcp.yaml`, `dns.yaml`, `radius.yaml`). Each
declares a `detection` block: ordered candidate backends with a shell `check`
command, plus `service_name` and `process_name`. Handlers use these to detect
which backend is installed and how to control it, supporting both systemd and
SysVinit.

---

## 6. Data-list files (`config/*.txt`)

| File | Used by | Contents |
|------|---------|----------|
| `electric_addresses.txt` | `electric_monitor` | Addresses to match against Premier Energy outage notices |
| `invoice_clienti_email.txt` | `email_invoice_sender` | Client names whose unpaid invoices are emailed |
| `postamoldovei_clienti.txt` | `posta_generator` | Clients included in the Posta XLSX export |

These contain no credentials and are safe to commit.

---

## 7. Minimal viable configuration

To get the web app running with one DHCP server and AI commands:

```yaml
# secrets.yaml
servers:
  - id: dhcp-primary
    host: 192.168.1.1
    user: admin
    auth_type: key
    auth_value: dhcp-primary.key
    sudo_password: "..."
    distro: debian
    services: [dhcp]
    enabled: true

mcp_server:
  web_host: "0.0.0.0"
  web_port: 4455
  session_secret: "<random-32+-chars>"

claude:
  api_key: "sk-ant-..."

web_users:
  - username: admin
    password: "<change-me>"
    role: admin
```

`.env` is only needed once you enable the automation modules.
