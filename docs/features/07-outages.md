[← CDP and auto-fill](06b-netbox-cdp.md) · **7 / 8** · [Map](README.md) · [Next: Superadmin console →](08-admin.md)

# ⚡💧 Power and water outages

Once a day the panel reads the utility providers' websites and sends an e-mail if a planned outage affects our addresses.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["⚡💧 Outages"]):::root

    ROOT --> EL["⚡ Electricity<br/>Premier Energy"]:::group
    EL --> E1["Reads the planned<br/>works page"]:::auto
    EL --> E2["Matches the address list,<br/>house numbers included"]:::auto

    ROOT --> WA["💧 Water<br/>acc.md"]:::group
    WA --> W1["Reads the<br/>disconnections page"]:::auto
    WA --> W2["Looks for a match<br/>with a pattern"]:::auto

    ROOT --> TIME["⏰ Schedule"]:::group
    TIME --> T1["Once a day, with separate times<br/>for power and water"]:::auto
    TIME --> T2["Missed because of a restart?<br/>Catches up after start-up"]:::auto

    ROOT --> MAIL["✉️ Notifications"]:::group
    MAIL --> M1["E-mail when there<br/>are matches"]:::auto
    MAIL --> M2["The same e-mail<br/>is never sent twice"]:::auto

    ROOT --> UI["🖱️ In the UI"]:::group
    UI --> U1["⚡ 💧 header indicators"]:::all
    UI --> U2["Check right now"]:::all

    ROOT --> CONF["⚙️ Setup<br/>Admin → Settings"]:::group
    CONF --> C1["Address list for power"]:::super
    CONF --> C2["Address pattern for water"]:::super
    CONF --> C3["Check time"]:::super

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef all   fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef super fill:#fde2e2,stroke:#dc2626,color:#7f1d1d
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

## A day in the life of a check

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    CLK["⏰ The configured<br/>time arrives"]:::auto --> GET["🌐 Download the<br/>provider's page"]:::auto
    GET --> MATCH{"Any of our addresses?"}
    MATCH -- no --> GREEN["🟢 Indicator green"]:::all
    MATCH -- yes --> DUP{"Was this e-mail<br/>already sent?"}
    DUP -- yes --> RED["🔴 Indicator red,<br/>no duplicate e-mail"]:::all
    DUP -- no --> SEND["✉️ Send the e-mail"]:::auto --> RED

    classDef all  fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef auto fill:#fef3c7,stroke:#d97706,color:#78350f
```

> Mail settings (SMTP, recipients) live in `.env`. They can be edited in **Admin → Settings → .env**; see [👑 Superadmin console](08-admin.md).
> Instead of the built-in schedule you can use the systemd timers in `scripts/`, but **not both** for the same channel.

## Where it is in the code

| What | File |
|------|------|
| Power: Premier Energy | `src/monitoring/electric_monitor.py`, addresses in `config/electric_addresses.txt` |
| Water: acc.md | `src/monitoring/acc_monitor.py` |
| Built-in schedule | `src/monitoring/outage_scheduler.py` |
| Settings changed at runtime | `src/web/runtime_config.py` |
| `/api/electric/*`, `/api/acc/*` endpoints | `src/web/routes/utilities.py` |

---
[← CDP and auto-fill](06b-netbox-cdp.md) · [Map](README.md) · [Next: Superadmin console →](08-admin.md)
