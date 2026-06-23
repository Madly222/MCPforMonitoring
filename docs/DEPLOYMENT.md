# Deployment Guide

How to run MCP Server Monitor in production on a Linux host with systemd.
For configuration details see [`CONFIGURATION.md`](CONFIGURATION.md).

This guide assumes the project lives at `/home/user/ServersMonitoringMCP` and
runs as the `user` account. Adjust paths/usernames to your environment — the
shipped unit files in `scripts/` use exactly these values.

---

## 1. Prerequisites

```bash
# System packages
sudo apt update
sudo apt install -y python3 python3-venv openssh-client snmp mysql-client

# Project + virtualenv
cd /home/user/ServersMonitoringMCP
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

| Package | Required for |
|---------|--------------|
| `openssh-client` | all SSH operations |
| `snmp` (`snmpwalk`) | ONU/GPON monitoring |
| `mysql-client` | billing/invoice DB queries |

---

## 2. Configuration

```bash
cp secrets.example.yaml secrets.yaml
cp .env.example .env
nano secrets.yaml          # servers, Claude key, web users, OLTs
nano .env                  # only if using automation modules

# SSH keys for key-auth servers
mkdir -p keys
cp /path/to/server.key keys/
chmod 600 keys/*
```

Before going live:
- Set `mcp_server.session_secret` to a random ≥32-char string.
- Change all default passwords in `web_users`.
- Restrict CORS (see [Hardening](#7-hardening)).

Smoke-test before installing the service:
```bash
source venv/bin/activate
python -m src.main          # Ctrl-C after it reports "Starting web server..."
```

---

## 3. Main service (web app)

Create the unit:

```ini
# /etc/systemd/system/mcp-monitor.service
[Unit]
Description=MCP Server Monitor
After=network.target

[Service]
Type=simple
User=user
WorkingDirectory=/home/user/ServersMonitoringMCP
Environment="PATH=/home/user/ServersMonitoringMCP/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/home/user/ServersMonitoringMCP/venv/bin/python -m src.main
Restart=always
RestartSec=5
TimeoutStopSec=10
KillMode=mixed

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mcp-monitor
sudo systemctl status mcp-monitor
```

The dashboard is then available at `http://<host>:4455`.

---

## 4. Scheduled automation (timers)

The `scripts/` directory ships ready-made one-shot `.service` units and matching
`.timer` units. Install whichever jobs you use.

| Job | Service unit | Timer | Default schedule | Runs |
|-----|--------------|-------|------------------|------|
| Water outage | `acc-monitor.service` | `acc-monitor.timer` | daily 08:00 | `scripts/acc_monitor.py` |
| Electricity outage | `electric-monitor.service` | `electric-monitor.timer` | daily 09:00 | `scripts/check_electric.py` |

Install (example for both):

```bash
sudo cp scripts/acc-monitor.service scripts/acc-monitor.timer \
        scripts/electric-monitor.service scripts/electric-monitor.timer \
        /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now acc-monitor.timer
sudo systemctl enable --now electric-monitor.timer

# Verify schedule
systemctl list-timers 'acc-monitor*' 'electric-monitor*'

# Trigger one run immediately to test
sudo systemctl start electric-monitor.service
journalctl -u electric-monitor.service -n 50 --no-pager
```

> The one-shot units are `Type=oneshot`: they run, log, and exit. The timer with
> `Persistent=true` will catch up a missed run after downtime.

### Invoicing jobs
> ⚠️ **Temporary feature — scheduled for removal.** The invoicing channels are
> provisional; the guidance below is for current operation only.

The Paynet/Posta/WHMCS invoice channels are triggered through the API
(`POST /api/invoice/generate`, `POST /api/invoice/send-emails`). To schedule
them, create analogous one-shot service + timer units that either call the
endpoint (e.g. via `curl` with an authenticated session) or import the module
function — following the same pattern as the outage monitors.

---

## 5. Logs & operations

```bash
# Web service logs (systemd + loguru file)
journalctl -u mcp-monitor -f
tail -f /home/user/ServersMonitoringMCP/logs/app.log

# Timer job logs
journalctl -u acc-monitor.service
journalctl -u electric-monitor.service

# Restart after config change
sudo systemctl restart mcp-monitor
```

Application logs rotate automatically (size-based, zipped) per
`config/settings.yaml > logging.rotation`.

---

## 6. Updating

```bash
cd /home/user/ServersMonitoringMCP
git pull
source venv/bin/activate
pip install -r requirements.txt        # in case deps changed
sudo systemctl restart mcp-monitor
```

If timer unit files changed, re-copy them and `sudo systemctl daemon-reload`.

---

## 7. Hardening

- **Reverse proxy + TLS.** Put nginx/Caddy in front and terminate HTTPS; don't
  expose `:4455` directly.
- **CORS.** The app currently allows all origins. Restrict
  `allow_origins` in `src/web/app.py` for internet-facing deployments.
- **Firewall.** Limit `:4455` to trusted networks.
- **Secrets.** `secrets.yaml`, `.env`, and `keys/` are gitignored — keep file
  permissions tight (`chmod 600` on keys; restrict the project dir).
- **Least privilege.** Give the monitoring SSH user only the sudo rights it needs
  for service control; prefer `NOPASSWD` scoped to specific commands.
- **Session secret.** Rotate `session_secret`; rotation invalidates sessions.

---

## 8. Quick reference

```bash
# Status / control
sudo systemctl {start|stop|restart|status} mcp-monitor
sudo systemctl {enable|disable} mcp-monitor

# Timers
systemctl list-timers
sudo systemctl start electric-monitor.service     # run now

# Logs
journalctl -u mcp-monitor -f
tail -f logs/app.log
```
