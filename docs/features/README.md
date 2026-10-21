# 🌳 NetOps Control Plane feature map

The app does a lot, so its features are split into **8 separate trees**.
This page is the top level only. Open a branch to see a detailed tree of what it does, where to find it and why it exists.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    APP(["🛰️ NetOps Control Plane<br/>web panel :4455"]):::root

    APP --> A["🔐 Access and roles"]:::group
    APP --> B["🖥️ Servers and services"]:::group
    APP --> C["📈 Background monitoring"]:::group
    APP --> D["⌨️ Terminal and AI commands"]:::group
    APP --> E["📡 GPON / ONU"]:::group
    APP --> F["🗂️ NetBox"]:::group
    APP --> G["⚡💧 Power and water outages"]:::group
    APP --> H["👑 Superadmin console"]:::group

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
```

| # | Tree | What's inside | Where in the UI |
|:-:|------|---------------|-----------------|
| 1 | [🔐 Access and roles](01-access.md) | sign-in, sessions, 3 roles, password change, audit | sign-in screen, header |
| 2 | [🖥️ Servers and services](02-servers.md) | server cards, DHCP / DNS / RADIUS, server report | **Servers** |
| 3 | [📈 Background monitoring](03-monitoring.md) | log watching, error recognition, incidents and fixes, health checks, header indicators | runs on its own; **Servers → Incidents**, header |
| 4 | [⌨️ Terminal and AI commands](04-terminal.md) | plain-language commands via Claude, risk policy and confirmation, raw SSH console | **Servers → Terminal Interpretation** |
| 5 | [📡 GPON / ONU](05-onu.md) | ZTE C320 OLTs, optical signal, ONU registration, search and filters | **ONU** |
| 6 | [🗂️ NetBox](06-netbox.md) | NetBox auto-fill from switches and routers, MAC and port sync | **NetBox** |
| 6a | ↳ [🔄 MAC and port sync](06a-netbox-mac-sync.md) | phpDHCPAdmin → MAC → subscriber port, reading the report | **NetBox → Sync MAC / Sync Ports** |
| 6b | ↳ [🔗 CDP and auto-fill](06b-netbox-cdp.md) | what is read from Cisco, how cables are built, what is written to NetBox | **NetBox → Single Device / Batch** |
| 7 | [⚡💧 Power and water outages](07-outages.md) | Premier Energy, acc.md, check schedule, e-mails | header ⚡ 💧, **Admin → Settings** |
| 8 | [👑 Superadmin console](08-admin.md) | users, servers, OLTs, settings, `.env`, audit log | **Admin** |

## 🎨 How to read the trees

In every tree the colour of a leaf shows **who can use the feature**:

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    L1["👁 Every role<br/>(operator and up)"]:::all
    L2["🛠 admin and up"]:::admin
    L3["👑 superadmin only"]:::super
    L4["⚙️ Runs automatically"]:::auto
    L5["🚧 Planned,<br/>not enabled yet"]:::plan

    classDef all   fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef super fill:#fde2e2,stroke:#dc2626,color:#7f1d1d
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef plan  fill:#f3f4f6,stroke:#9ca3af,color:#6b7280,stroke-dasharray:5 4
```

> The internals (modules, data flows) are described in [ARCHITECTURE.md](../ARCHITECTURE.md).
> These trees are the **user's** view: what the app can do and where to find it.
