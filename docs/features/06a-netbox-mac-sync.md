[← NetBox overview](06-netbox.md) · **6a** · [Map](README.md) · [Next: CDP and auto-fill →](06b-netbox-cdp.md)

# 🔄 NetBox: MAC and port sync

Two buttons on the **NetBox** tab that work **as a chain** (both need admin):

1. **🔄 Sync MAC** takes "IP ↔ MAC" pairs from phpDHCPAdmin and writes the MAC into NetBox.
2. **🔗 Sync Ports** uses those MACs to find which port of which device the subscriber is on, and assigns their IP to that interface in NetBox.

Order matters: without step 1 the IPs in NetBox have no MAC, and step 2 has nothing to look for.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart TB
    DB[("🗄️ phpDHCPAdmin<br/>MySQL")]:::src -- "1. 🔄 Sync MAC" --> IP["NetBox: IP address<br/>+ MAC field"]:::nb
    IP -- "2. 🔗 Sync Ports" --> NET["🔀 Switches · 📡 OLTs<br/>MAC tables"]:::src
    NET --> ASSIGN["NetBox: IP assigned<br/>to the subscriber port"]:::nb

    classDef src fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef nb  fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
```

---

## 1. 🔄 Sync MAC: phpDHCPAdmin → NetBox

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["🔄 Sync MAC"]):::root

    ROOT --> SRC["📥 Source"]:::group
    SRC --> S1["SSH to the DHCP server"]:::auto
    SRC --> S2["phpDHCPAdmin MySQL,<br/>table conf_hosts:<br/>ip-address + mac-address"]:::auto

    ROOT --> CLEAN["🧹 Cleaning"]:::group
    CLEAN --> C1["MAC normalised to<br/>AA:BB:CC:DD:EE:FF"]:::auto
    CLEAN --> C2["Malformed IPs and MACs<br/>are dropped"]:::auto

    ROOT --> FIND["🔍 Lookup in NetBox"]:::group
    FIND --> F1["The IP is looked up<br/>exactly first, then by search"]:::auto

    ROOT --> WRITE["✍️ What it writes"]:::group
    WRITE --> W1["Only the MAC field<br/>of the IP address"]:::admin
    WRITE --> W2["Same MAC already there:<br/>skipped"]:::auto

    ROOT --> NOT["🚫 What it does NOT do"]:::group
    NOT --> N1["Create IPs that<br/>are not in NetBox"]:::all
    NOT --> N2["Touch any other field"]:::all

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef all   fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

### Reading the summary

After the sync a window shows four numbers:

| Number | Meaning | What to do |
|--------|---------|------------|
| **Updated** | The MAC was written or corrected | nothing |
| **Skipped** | NetBox already had the same MAC | nothing |
| **Not found** | The IP is in DHCP, but NetBox has no such IP address | add the IP to NetBox if it is needed |
| **Errors** | NetBox rejected the write | check the service log |

---

## 2. 🔗 Sync Ports: MAC → subscriber port → NetBox

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["🔗 Sync Ports"]):::root

    ROOT --> WHO["🗺️ Devices it visits"]:::group
    WHO --> D1["📡 OLTs from the panel settings"]:::auto
    WHO --> D2["NetBox devices with an IP<br/>in the management network"]:::auto
    WHO --> D3["NetBox devices<br/>with a primary IP"]:::auto
    WHO --> D4["Extra list in<br/>config/scan_devices.txt"]:::auto

    ROOT --> VEND["🏷️ Vendor and command"]:::group
    VEND --> V1["Cisco IOS · Cisco SG<br/>TP-Link · D-Link<br/>show mac address-table"]:::auto
    VEND --> V2["MikroTik<br/>/interface bridge host print"]:::auto
    VEND --> V3["ZTE C320<br/>show mac gpon olt 1/1/1…16"]:::auto
    VEND --> V4["Unknown vendor:<br/>device skipped"]:::auto

    ROOT --> CRED["🔑 Credentials"]:::group
    CRED --> K1["RADIUS first,<br/>then SSH, from the tab's fields"]:::admin
    CRED --> K2["Fields empty:<br/>taken from .env"]:::auto

    ROOT --> LEAF["🎯 Finding the subscriber port"]:::group
    LEAF --> L1["A port with ≤ 3 MACs<br/>is a subscriber port"]:::auto
    LEAF --> L2["Many MACs:<br/>an uplink, skipped"]:::auto
    LEAF --> L3["On a tie<br/>gpon-onu wins"]:::auto

    ROOT --> WR["✍️ What it writes"]:::group
    WR --> R1["The IP is assigned<br/>to the device interface"]:::admin
    WR --> R2["The IP's MAC field<br/>is kept"]:::auto
    WR --> R3["No such interface:<br/>report only"]:::auto

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

### How the "subscriber port" is chosen

A subscriber's MAC is visible on many devices: their access switch, the aggregation, the core.
What tells these places apart is **how many MACs there are on the port**. An uplink has hundreds; a subscriber port has one or two (a router, a TV box).

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    MAC["💻 Subscriber MAC<br/>AA:BB:CC:11:22:33"]:::auto
    MAC --> P1["Core · Te1/1<br/>412 MACs"]:::skip
    MAC --> P2["Aggregation · Gi0/24<br/>57 MACs"]:::skip
    MAC --> P3["Access SW36 · Fa0/7<br/>2 MACs"]:::win
    P1 --> X1["❌ uplink"]:::skip
    P2 --> X2["❌ uplink"]:::skip
    P3 --> OK["✅ subscriber port:<br/>IP → SW36 / Fa0/7"]:::win

    classDef auto fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef skip fill:#f3f4f6,stroke:#9ca3af,color:#6b7280
    classDef win  fill:#dcfce7,stroke:#16a34a,color:#14532d
```

The threshold of 3 MACs is set in `.env` (`MAC_LEAF_THRESHOLD`). If two ports qualify equally, the one with fewer MACs wins, and on a full tie `gpon-onu` wins (it is certainly an end ONU).

### Reading the summary

A short summary appears in the window, the full one in the log:

| Status | Meaning | What to do |
|--------|---------|------------|
| **assigned** | The IP was assigned to a new interface | nothing |
| **already_ok** | The IP was already on the right interface | nothing |
| **no_leaf · unseen** | The MAC was not found on any polled device | the subscriber is off, or their switch is not polled |
| **no_leaf · trunk** | The MAC is only seen on ports with more than 3 MACs | an unmanaged switch behind the subscriber, or the threshold is too low |
| **iface_missing** | The port was found, but NetBox has no such interface | add the interface in NetBox |
| **dev_missing** | NetBox has no device with that name | check the device name in NetBox |
| **failed / skipped** | The device could not be polled: unreachable, wrong password, unknown vendor | the list with reasons is at the end of the log |

### Credentials

The NetBox tab has two pairs of fields: **RADIUS Login/Pass** and **SSH Login/Pass**.
For each device RADIUS is tried first, then SSH if authentication fails. If the device is simply unreachable, the second option is not tried.
If all fields are empty, `SSH_USERNAME` / `SSH_PASSWORD` from `.env` are used (`TPLINK_SSH_*` for TP-Link).

### Settings in `.env`

| Setting | Default | Purpose |
|---------|:-:|---------|
| `MAC_LEAF_THRESHOLD` | `3` | how many MACs a port may have and still count as a subscriber port |
| `MAC_MGMT_PREFIX` | none (set it in `.env`) | which network to take devices to poll from |
| `MAC_CREATE_MISSING_IFACE` | `false` | `true` creates a missing interface (description `auto: MAC sync`) instead of reporting it |
| `MAC_SCAN_DEVICES_FILE` | `config/scan_devices.txt` | extra devices: `ip,vendor[,name]` per line |
| `MAC_OLT_MAX_PORT` | `16` | how many GPON ports of an OLT to poll |
| `DHCP_SSH_*`, `DHCP_MYSQL_*` | none | access to phpDHCPAdmin for Sync MAC |

All of these can be changed in **Admin → Settings → .env** (the panel needs a restart).

## Where it is in the code

| What | File |
|------|------|
| Sync MAC | `src/monitoring/dhcp_mac_sync.py` |
| Sync Ports | `src/monitoring/mac_port_sync.py` |
| NetBox access | `services/netbox-autofill/netbox_client.py` |
| `/api/netbox/sync-mac`, `/sync-interfaces` endpoints | `src/web/api_netbox.py` |

---
[← NetBox overview](06-netbox.md) · [Map](README.md) · [Next: CDP and auto-fill →](06b-netbox-cdp.md)
