[← Access and roles](01-access.md) · **2 / 8** · [Map](README.md) · [Next: Background monitoring →](03-monitoring.md)

# 🖥️ Servers and services

The **Servers** tab: a card for every server the panel manages over SSH, and control of their services.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["🖥️ Servers and services"]):::root

    ROOT --> CARD["🗂️ Server card"]:::group
    CARD --> C1["🟢 Online / 🔴 offline<br/>with the reason"]:::all
    CARD --> C2["Services and their state"]:::all
    CARD --> C3["🔌 Reconnect SSH"]:::all
    CARD --> C4["ℹ️ Report: OS, CPU, RAM, disks, network"]:::all

    ROOT --> ACT["🎛️ Service control"]:::group
    ACT --> A1["▶️ start · ⏹ stop · 🔁 restart · ♻️ reload"]:::admin
    ACT --> A2["🩺 Diagnostics: process, port, config"]:::all

    ROOT --> SVC["🧩 Supported services"]:::group
    SVC --> S1["DHCP: isc-dhcp · kea · dnsmasq"]:::all
    SVC --> S2["DNS: bind9 · Technitium · dnsmasq<br/>unbound · PowerDNS"]:::all
    SVC --> S3["RADIUS: FreeRADIUS 2.x / 3.x"]:::all
    SVC --> S4["Mail and web: Postfix · Dovecot<br/>Apache · SpamAssassin"]:::all

    ROOT --> PROF["🧬 Server profile"]:::group
    PROF --> P1["systemd or SysVinit, distribution"]:::auto
    PROF --> P2["Detected once and remembered"]:::auto

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef all   fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef super fill:#fde2e2,stroke:#dc2626,color:#7f1d1d
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

## Why it exists

| Branch | Why |
|--------|-----|
| 🗂️ Card | See at a glance which server is down and which service failed on it, and why the connection failed |
| 🎛️ Control | Restart DHCP/DNS/RADIUS from the browser without an SSH session |
| 🧩 Services | The service variant is detected automatically, so the panel finds configs, logs and lease files on its own. DHCP shows leases and pools, DNS checks that a test zone resolves, mail and web get status and restart only |
| 🧬 Profile | The same "restart" button works on systemd and on old SysVinit hosts |

> Servers are added, changed or removed in **Admin → Servers**; see [👑 Superadmin console](08-admin.md).

## Where it is in the code

| What | File |
|------|------|
| SSH connections, command execution, quoting | `src/core/ssh_manager.py` |
| Server report | `src/core/system_info.py` |
| Server profile (`sessions/server_profiles.json`) | `src/core/server_profile.py` |
| DHCP / DNS / RADIUS | `src/services/dhcp.py`, `dns.py`, `radius.py`, registered in `src/services/registry.py`, with `config/services/*.yaml` |
| Endpoints | `src/web/routes/servers.py` |

---
[← Access and roles](01-access.md) · [Map](README.md) · [Next: Background monitoring →](03-monitoring.md)
