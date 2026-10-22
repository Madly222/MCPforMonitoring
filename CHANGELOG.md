# Changelog

## Unreleased

### Security
- The risk classifier let more commands run as root without confirmation:
  - shell syntax hid the command inside it: a `case` branch (`case x in x) rm -rf / ;; esac`), a `for` loop whose body follows its header without a separator (`for x do …`, `for ((;;)) do …`) and a function body (`ls() { rm -rf /; }; ls`) were read as a loop or case header. Parentheses now start a new command, and a `for` header is classified from its `do` on;
  - shlex returns operators glued to a parenthesis or separator as one token, so `(cat x)>/usr/bin/ls`, `ls;>/usr/bin/ls` and `ls|>file` hid a redirection; such runs are now cut into separate operators, and `<>` counts as a write;
  - `systemctl restart bind9 networking` (or `… reboot.target`) was checked against `allowed_services` by its first unit only; a restart or reload naming several units now always needs confirmation;
  - a reload (risk 0) was taken for read-only, so `allowed_services` was never checked for it and `systemctl reload` of any unit ran unconfirmed.
- Every case above is a regression test, and the property tests glue dangerous commands on with the same constructs.
- Dependencies with known advisories updated: aiohttp 3.14.5, starlette 1.7.0 (through FastAPI 0.142.4), asyncssh 2.24.1, paramiko 5.0.0 (with netmiko 4.8.0), python-dotenv 1.2.4, requests 2.34.2; `pip-audit` finds none left.
- CI audits `requirements.txt` and `mcp_server/requirements.txt` with `pip-audit` on every push and weekly; Dependabot proposes pip, GitHub Actions and Docker base-image updates.

### Changed
- pydantic 2.13.5, pyyaml 6.0.3 and httpx 0.28.1, as the updates above require.
- Removed dependencies nothing imports: aiosmtplib and python-multipart (both had advisories), pydantic-settings, itsdangerous and aiofiles.
- The route-role test reads routes through `fastapi.routing.iter_route_contexts`, since FastAPI now keeps included routers unexpanded in `app.routes`.
- Passwords are limited to 72 bytes, the most bcrypt reads (72 Latin or 36 Cyrillic characters), with a clear message when a new one is longer. bcrypt 4 silently ignored the rest; bcrypt 5 raises an error instead, which would have locked out users with a longer password and stopped seeding from `secrets.yaml`. Logins and seeding still compare only the first 72 bytes, as before, so passwords set earlier keep working under either version. Tested with bcrypt 4.1.2 and 5.0.0.
- Power and water outage e-mails, and the water outage entries on the dashboard, are in English like the rest of the app. An ongoing water disconnection may be e-mailed once more on the day of the upgrade, because its first line, the de-duplication key, changed.
- Leftovers of the old name: the CI image tag, the example sender name and the package author. The systemd unit keeps its name, `mcp-monitor`, so existing installs and the panel's own restart button keep working.

## 1.1.3 — 2026-10-21

### Fixed
- CI was red on 1.1.2 because of the tests, not the classifier: the property test treated `>&0` (descriptor duplication, like `2>&1`) as a file write. It now flags only redirections that can write, with `>&0`, `grep 'a>b'` and `>& file` pinned as examples.
- The SSH host-key test waits for its server to close before reusing the port.
- CI turns failing tests into run annotations, so a failure is readable without signing in to GitHub.

## 1.1.2 — 2026-10-21

### Security
- The risk classifier let several commands run as root without confirmation, which Claude-generated commands could have reached:
  - a line break or a mid-word `#` hid the rest of the command from the tokenizer (`uptime x#y; rm -rf /`), and `>& file` was taken for a descriptor duplicate although bash writes the file (found by the property tests);
  - programs on the read-only list that run code or write: `awk` (`system()`), `less`/`more`, `sed` with the `e`/`w` commands or flags, `sort -o`, `uniq IN OUT`, `named-checkzone -o`, `find -fprint*`/`-execdir`;
  - programs that change the system: `date -s`, `hostname NAME`, `hostnamectl`/`timedatectl set-*`, `ss -K`, `postqueue -f`, `dmesg -C`, `ping -f`, and `top` without `-b` hung until the timeout;
  - `VAR=value` prefixes such as `LD_PRELOAD`, `env -S` and `sudo -i`/`-s`.
- The read-only list now separates programs that are safe with any arguments from those whose arguments are checked; `sed` is allowed only with print/delete/quit and `s///`/`y///` scripts.
- New tests: every bypass above as a regression case, ordinary diagnostics that must still run unconfirmed, and Hypothesis property tests (dangerous commands glued to safe ones with 30 shell constructs, generated pipelines with a known verdict, arbitrary text). Run against the previous classifier, all four property tests fail.
- The host-status template uses `head` instead of `awk`.

## 1.1.1 — 2026-10-21

### Security
- SSH host keys of monitored servers are trusted on first use (`sessions/known_hosts`) and checked on every later connection; a changed key is refused with an explanation. `mcp_server.ssh_host_keys: off` restores the old behaviour, which accepted any key.
- `.env`, the user, session and runtime-settings stores and `known_hosts` are written owner-only (0600).
- Deployment guide: SSH keys instead of passwords, what `NOPASSWD` sudo does and does not limit, file permissions.

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
