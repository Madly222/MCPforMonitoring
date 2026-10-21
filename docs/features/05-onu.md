[← Terminal and AI commands](04-terminal.md) · **5 / 8** · [Map](README.md) · [Next: NetBox →](06-netbox.md)

# 📡 GPON / ONU

The **ONU** tab: subscriber terminals on ZTE C320 OLTs. Is there a signal, how strong is it, is the ONU registered.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["📡 GPON / ONU"]):::root

    ROOT --> OLT["🏢 ZTE C320 OLT"]:::group
    OLT --> O1["ONU list<br/>grouped by OLT"]:::all
    OLT --> O2["Background polling<br/>on a schedule"]:::auto
    OLT --> O3["📡 Poll now"]:::admin

    ROOT --> SIG["💡 Optical status"]:::group
    SIG --> S1["🟢 online · 🔴 offline<br/>🟡 low signal"]:::all
    SIG --> S2["Rx power in dBm<br/>read from the OLT CLI"]:::auto
    SIG --> S3["Low-signal threshold<br/>−25 dBm by default"]:::auto

    ROOT --> REG["🪪 Registration on the OLT"]:::group
    REG --> R1["registered /<br/>not registered"]:::all
    REG --> R2["Separate from the signal:<br/>an ONU can have light<br/>but not be provisioned"]:::all

    ROOT --> INFO["🏷️ ONU details"]:::group
    INFO --> I1["Port · ID · serial number<br/>description"]:::all
    INFO --> I2["MAC address<br/>over SSH to the OLT"]:::auto

    ROOT --> FIND["🔍 Working with the list"]:::group
    FIND --> F1["Search by name, port,<br/>MAC, serial"]:::all
    FIND --> F2["Filters: All · Online · Offline<br/>Low Signal · Not registered"]:::all
    FIND --> F3["Sorted by port"]:::all

    ROOT --> CONF["⚙️ Setup"]:::group
    CONF --> C1["Add / change an OLT<br/>Admin → OLT Devices"]:::super
    CONF --> C2["SNMP v2c / v3 + SSH"]:::super

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef all   fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef super fill:#fde2e2,stroke:#dc2626,color:#7f1d1d
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

## Why "signal" and "registration" are separate

| Signal | Registration | What it means in practice |
|--------|--------------|---------------------------|
| 🟢 online | registered | All good |
| 🟡 low signal | registered | The subscriber works, but the line needs a look (dirty connector, tight bend) |
| 🔴 offline | registered | No light: the ONU is off or the fibre is cut |
| 🟢 online | not registered | The ONU has light but is not provisioned on the OLT; it needs registering |

> The **Not registered** filter finds exactly the fourth case: ONUs that are physically connected but not served.

## Where it is in the code

| What | File |
|------|------|
| OLT polling, signal, registration, MAC | `src/monitoring/onu_monitor.py` |
| `/api/onu/*` endpoints | `src/web/routes/onu.py` |
| ONU tab: search, filters | `web/js/onu.js` |

---
[← Terminal and AI commands](04-terminal.md) · [Map](README.md) · [Next: NetBox →](06-netbox.md)
