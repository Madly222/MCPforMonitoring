# Changelog

## 1.1.0 — 2026-10-21

Hardening and clean-up for publication. The project is renamed NetOps Control Plane.

### Added
- **Risk policy for commands** (`src/actions/policy.py`): every command built from a template or by Claude is classified against `config/safe_actions.yaml`. Read-only commands and restarts of listed services run at once; anything else returns to the dashboard with the exact command, its risk and the reason, and runs only after the same admin confirms it (`POST /api/execute/confirm`).
- **Remediation** of known errors (`auto_remediation.mode`: `off`, `suggest`, `auto`) within the policy's cooldowns, hourly caps and failure backoff; Claude diagnoses errors no pattern matches. Incidents card on the dashboard with an Apply fix button.
- **Demo mode** (`DEMO_MODE=1`, `docker compose up`): the real app against simulated servers, OLTs and outage feeds.
- **Docker** image and compose file; `MONITOR_DATA_DIR` and `MONITOR_SECRETS_FILE` put every runtime file in one directory.
- **CI**: ruff, pytest on Python 3.10–3.12, and a demo-container smoke test. The test suite grew from 15 to about 140 tests, including a registry of the required role of every route.
- MIT license.

### Security
- Sessions persist across restarts and are stored by hash; roles are re-read on every request; password changes and resets end other sessions; login lockout per username and IP; minimum password length 10; Secure cookie option; CORS off unless configured.
- `GET /api/acc/status` and `/api/electric/status` required no login and each call triggered a scrape of the provider sites.
- Values interpolated into remote shell commands are quoted or validated, and sudo wraps the whole command, not only the first program in a pipe.
- Removed unused password helpers that accepted plaintext passwords.
- Role checks written inside handlers (NetBox, app restart) moved into `Depends(...)` so the route registry sees them, with a test that keeps them there. Note: the 1.1.0 commit "Close access gaps…" says NetBox writes were open to operators; they were not, the handlers already refused operators with an inline check.

### Fixed
- Service detection treated `"not found"` as found, so every DNS server was detected as Technitium and status, health checks and watched logs came from the wrong variant.
- "stop/start dns" in the terminal ended in "Command not recognized"; it now goes through the risk policy.
- The default Claude model (`claude-sonnet-4-20250514`) is retired; the default is now `claude-opus-5-5`, and replies are read from text blocks instead of `content[0]`.
- The error-analysis prompt sent doubled braces to Claude.
- `Retry-After` was one second longer than the lockout.

### Changed
- `anthropic` 0.18 → 1.17 with `AsyncAnthropic`; the sync client blocked the event loop.
- `src/web/api.py` (1500 lines) split into one router per area under `src/web/routes/`; the service handler map, copied nine times, now lives in `src/services/registry.py`.
- `mcp_server.session_secret` is no longer required (it was never used).
- English messages for SSH errors and OLT polling; the feature map in `docs/features/` translated to English.

### Removed
- `requirements.lock`, a freeze of the old VM that pinned `anthropic` 0.18, which the code no longer runs on. `requirements.txt` pins every direct dependency, and the Docker image is the reproducible build.
- Empty `knowledge/`, `notifications/` and `storage/` packages, the unused `check_updates`, and `docs/server_launch.ru.md` (covered by `docs/DEPLOYMENT.md`).

## 1.0.0

The version that ran in production: SSH monitoring of DHCP, DNS and RADIUS servers, log watching against a knowledge base, natural-language commands with a template resolver and Claude fallback, GPON monitoring of ZTE OLTs, NetBox auto-fill and MAC sync, power and water outage alerts, superadmin console, audit log and a read-only MCP server.
