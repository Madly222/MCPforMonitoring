[← MAC sync](06a-netbox-mac-sync.md) · **6b** · [Map](README.md) · [Next: Power and water outages →](07-outages.md)

# 🔗 NetBox: CDP and auto-fill from switches and routers

**Single Device** mode (and **Batch Mode**) on the **NetBox** tab. The panel signs in to a Cisco device over SSH, reads the port settings and the **CDP** neighbours, and carries them over to NetBox: port modes, VLANs, descriptions, IPs and **cables between devices**.

**CDP** (Cisco Discovery Protocol): every Cisco device tells its neighbours its name and port. So a switch knows "on my Gi0/1 sits SW122, on its port Gi1/31". The panel lays the cables in NetBox from exactly this data.

## Two steps

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    A["🔍 Scan<br/>reads the device"]:::admin --> B["📋 Port table<br/>with checkboxes"]:::admin
    B --> C["✅ Apply<br/>writes to NetBox<br/>only the ticked ports"]:::admin
    D["🚀 Batch Mode"]:::admin -. "Scan + Apply at once,<br/>all ports, no table" .-> C

    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
```

---

## 🔀 Switch: what Scan reads

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["🔍 Switch scan"]):::root

    ROOT --> CON["🔌 Connection"]:::group
    CON --> C1["The device is looked up<br/>in NetBox by IP"]:::auto
    CON --> C2["SSH, old IOS<br/>supported"]:::auto
    CON --> C3["The name comes from<br/>the CLI prompt"]:::auto

    ROOT --> PORTS["📡 Ports"]:::group
    PORTS --> P1["show interfaces status:<br/>connected only"]:::auto
    PORTS --> P2["show running-config interface:<br/>description, access / trunk"]:::auto
    PORTS --> P3["VLANs: access, native,<br/>allowed, ranges expanded"]:::auto

    ROOT --> CDP["🔗 CDP"]:::group
    CDP --> D1["show cdp neighbors detail"]:::auto
    CDP --> D2["Neighbour name without the domain<br/>+ its port + platform"]:::auto

    ROOT --> MATCH["🧩 Matching against NetBox"]:::group
    MATCH --> M1["Own interface:<br/>by name variants"]:::auto
    MATCH --> M2["Is there already a cable"]:::auto
    MATCH --> M3["The neighbour and its interface"]:::auto

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

### How the neighbour is found in NetBox

The name from CDP and the name in NetBox often differ (for example `CIS-NX3K-SW36-N.TST` versus `CIS-NX3K-SW36-ECB`). So the neighbour is looked up in three attempts:

1. **the exact name** (domain already stripped);
2. **by switch number** `SWnn`; if several devices match, the model narrows it down (`NX3K`, `4948`, `2950`…);
3. **by name prefix**, trimming parts from the end until exactly one match is left.

The port name is also tried in different spellings: `Gi0/1` ↔ `GigabitEthernet0/1`, `[Gi]1/46`, `Fa1/0/1` ↔ `Fa1/01`, `Eth1/N` and so on.

## 🔀 Switch: what Apply writes

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["✅ Switch apply"]):::root

    ROOT --> S1["1️⃣ Management"]:::group
    S1 --> A1["Vlan200 interface,<br/>if VLAN 200 exists in NetBox"]:::admin
    S1 --> A2["Device IP /24<br/>on Vlan200"]:::admin

    ROOT --> S2["2️⃣ Each ticked port"]:::group
    S2 --> B1["trunk → tagged<br/>+ VLAN list"]:::admin
    S2 --> B2["access → access<br/>+ untagged VLAN"]:::admin
    S2 --> B3["Port description"]:::admin
    S2 --> B4["Port missing in NetBox:<br/>skipped, not created"]:::auto

    ROOT --> S3["3️⃣ Cable from CDP"]:::group
    S3 --> C1["Both ends found:<br/>old cables on both<br/>ends are deleted"]:::admin
    S3 --> C2["A CAT6 cable is created,<br/>status connected"]:::admin
    S3 --> C3["Neighbour not found:<br/>cable skipped"]:::auto

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

### Example: from CDP to a NetBox cable

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart TB
    CLI["🖥️ SW36 says over CDP:<br/>'on Gi0/1 my neighbour is<br/>CIS-4948-SW122.corp.local,<br/>its port Gi1/31'"]:::auto
    CLI --> N1["NetBox: SW36 / Gi0/1 ✅"]:::nb
    CLI --> N2["NetBox: SW122 / Gi1/31 ✅"]:::nb
    N1 --> CAB["🔗 CAT6 cable<br/>SW36 Gi0/1 ↔ SW122 Gi1/31"]:::nb
    N2 --> CAB

    classDef auto fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef nb   fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
```

---

## 🌐 Router: Scan and Apply

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["🌐 Cisco router"]):::root

    ROOT --> SCAN["🔍 Scan reads"]:::group
    SCAN --> R1["show ip interface brief:<br/>interfaces, IPs, status"]:::auto
    SCAN --> R2["Interface descriptions,<br/>ip mtu on tunnels"]:::auto
    SCAN --> R3["show ip route connected:<br/>display only"]:::auto
    SCAN --> R4["show cdp neighbors detail"]:::auto
    SCAN --> R5["show version: model,<br/>serial, IOS, uptime"]:::auto

    ROOT --> DEV["🖥️ Device in NetBox"]:::group
    DEV --> D1["Looked up by name,<br/>then by IP"]:::admin
    DEV --> D2["Not found:<br/>created with model and serial"]:::admin

    ROOT --> APPLY["✅ Apply writes"]:::group
    APPLY --> A1["Interface: created<br/>if missing"]:::admin
    APPLY --> A2["Description and MTU"]:::admin
    APPLY --> A3["IP /24: recreated<br/>on that interface"]:::admin
    APPLY --> A4["Cables from CDP:<br/>as for a switch"]:::admin

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

## Switch versus router

| | 🔀 Switch | 🌐 Router |
|---|---|---|
| Ports taken | `connected` only | everything in `show ip interface brief` |
| Device missing in NetBox | Scan warns, Apply writes nothing | a new device is created |
| Interface missing in NetBox | the port is skipped | the interface is created |
| VLANs | mode and VLANs are written | not written |
| IPs | only the management IP on Vlan200 | the IP of every interface |
| Cables from CDP | yes, CAT6 | yes, CAT6 |
| Batch Mode | yes | no |

## ⚠️ What to know before Apply

| Behaviour | Why it matters |
|-----------|----------------|
| **Scan already changes NetBox:** if the device name in NetBox differs from the CLI hostname, the device is renamed during the scan, before Apply | Scan is not read-only, which is why it needs admin |
| **Cables are overwritten:** before a new cable is created, the old cables on **both** ends are deleted | manual cable edits on those ports are lost |
| **The cable type is always CAT6**, even for fibre | the type has to be fixed by hand |
| **The mask is always /24:** both for the switch's Vlan200 and for router IPs | IPs in other masks are recorded wrongly |
| **Router IPs are recreated:** existing records with that address are deleted and created again | the IP's custom fields are lost, including the `MAC` from [Sync MAC](06a-netbox-mac-sync.md) |
| **The `SWnn` neighbour lookup is fuzzy:** with several similar names the wrong device can be picked | check the port table before Apply |
| **Batch Mode applies every port without a preview** | prefer Single Device for unfamiliar devices |

## Where it is in the code

| What | File |
|------|------|
| SSH to Cisco, CLI and CDP parsing | `services/netbox-autofill/ssh_connector.py` |
| Switch Scan and Apply | `services/netbox-autofill/orchestrator.py` |
| Device and interface lookup, cables | `services/netbox-autofill/netbox_client.py` |
| Router Scan and Apply, Batch | `src/web/api_netbox.py` |
| NetBox tab | `web/js/netbox.js` |

---
[← MAC sync](06a-netbox-mac-sync.md) · [Map](README.md) · [Next: Power and water outages →](07-outages.md)
