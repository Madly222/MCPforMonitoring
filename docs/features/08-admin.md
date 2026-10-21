[← Power and water outages](07-outages.md) · **8 / 8** · [Map](README.md)

# 👑 Superadmin console

The **Admin** tab is visible to superadmins only. Five sub-tabs cover everything that used to mean editing files on the server.
Changes apply **immediately**, without a restart (except `.env`).

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["👑 Admin"]):::root

    ROOT --> USR["👤 Users"]:::group
    USR --> U1["Create / delete<br/>(sessions end at once)"]:::super
    USR --> U2["Reset password<br/>(signs the user out)"]:::super
    USR --> U3["Change role<br/>(applies on the next request)"]:::super

    ROOT --> SRV["🖥️ Servers"]:::group
    SRV --> S1["Add / change / remove<br/>a server and its services"]:::super
    SRV --> S2["Hot reload<br/>without restarting the panel"]:::super

    ROOT --> OLT["📡 OLT Devices"]:::group
    OLT --> O1["Add / change / remove an OLT"]:::super

    ROOT --> OUT["⚙️ Settings: outages"]:::group
    OUT --> T1["⚡💧 Addresses · pattern · time"]:::super

    ROOT --> NET["⚙️ Settings: connectivity"]:::group
    NET --> T2["Automatic connection check<br/>on/off + interval"]:::super
    NET --> T3["SSH connect timeout"]:::super
    NET --> T4["Terminal command timeout"]:::super
    NET --> T5["DNS test zone<br/>for the resolution check"]:::super

    ROOT --> ENV["⚙️ Settings: files"]:::group
    ENV --> T6["📝 .env editor<br/>secrets masked, restart needed"]:::super
    ENV --> T7["↩️ Reset to secrets.yaml<br/>Servers · OLTs · Users"]:::super

    ROOT --> AUD["📋 Log"]:::group
    AUD --> A1["Audit log:<br/>who, what, when, from which IP"]:::super

    ROOT --> RST["🔄 Restart the panel<br/>header button"]:::super

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef super fill:#fde2e2,stroke:#dc2626,color:#7f1d1d
```

## Where the panel gets its settings

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    Y["📄 secrets.yaml"]:::file -- "first start" --> S[("💾 Panel store<br/>sessions/*.json")]:::store
    UI["👑 Admin console"]:::super -- "live edits" --> S
    S --> APP["🛰️ The panel runs<br/>on this data"]:::store
    Y -. "↩️ Reload …<br/>discard the edits" .-> S
    E["📄 .env<br/>mail, NetBox"]:::file --> APP
    UI -- ".env editor" --> E

    classDef file  fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef store fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b
    classDef super fill:#fde2e2,stroke:#dc2626,color:#7f1d1d
```

> ⚠️ After the first start the **panel store** is the source of truth, not `secrets.yaml`.
> Editing `secrets.yaml` changes nothing until you press **Reload Servers / OLTs / Users**.

## Where it is in the code

| What | File |
|------|------|
| `/api/admin/*` endpoints | `src/web/admin.py` |
| Store for settings, servers, OLTs | `src/web/runtime_config.py` |
| Safe `.env` writes | `src/web/env_config.py` |
| Audit log | `src/web/audit.py` |
| Admin tab | `web/js/admin.js` |

---
[← Power and water outages](07-outages.md) · [Map](README.md)
