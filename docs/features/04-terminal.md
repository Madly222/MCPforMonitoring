[← Background monitoring](03-monitoring.md) · **4 / 8** · [Map](README.md) · [Next: GPON / ONU →](05-onu.md)

# ⌨️ Terminal and AI commands

The **Terminal Interpretation** block on the **Servers** tab. One input, two modes: the drop-down on the left decides who runs the command.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["⌨️ Terminal"]):::root

    ROOT --> AI["🧠 Interpret mode<br/>no server selected"]:::group
    AI --> A1["Type in plain language:<br/>'restart dhcp on dhcp-01'<br/>'dns errors for today'"]:::admin
    AI --> A2["The server is found<br/>by name or by service"]:::auto
    AI --> A3["Common commands skip Claude:<br/>0 tokens"]:::auto
    AI --> A4["Risky commands wait for<br/>your confirmation"]:::admin

    ROOT --> RAW["🖥️ Direct mode<br/>server selected"]:::group
    RAW --> R1["Any shell command,<br/>as in a normal SSH session"]:::admin
    RAW --> R2["☑️ sudo with one checkbox"]:::admin
    RAW --> R3["stdout · stderr · exit code"]:::admin

    ROOT --> OUT["📋 Result"]:::group
    OUT --> O1["Output window"]:::admin
    OUT --> O2["Command History<br/>✅ / ❌ per command"]:::admin

    ROOT --> CTRL["🛡️ Control"]:::group
    CTRL --> K1["admin and superadmin only"]:::admin
    CTRL --> K2["Every command and every<br/>confirmation goes to the audit log"]:::auto
    CTRL --> K3["Command timeout<br/>20 s by default, 5–600"]:::super

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef super fill:#fde2e2,stroke:#dc2626,color:#7f1d1d
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

## How a phrase becomes a command (Interpret mode)

The free ways are tried first; Claude is asked only when they do not work. Whatever command comes out goes through the risk policy before it runs.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    IN["💬 Operator's phrase"]:::admin --> T{"1. Template?<br/>status · logs · errors<br/>restart · start · stop"}
    T -- yes --> POL
    T -- no --> C{"2. Resolved this<br/>phrase before?"}
    C -- yes --> POL
    C -- no --> CL["3. 🤖 Ask Claude"]:::auto
    CL --> SAVE["💾 Save to the cache"]:::auto --> POL
    CL -- "no answer / API down" --> KW["4. Keyword fallback"]:::auto
    POL{"🛡️ Risk policy"} -- "read-only or<br/>allowed restart" --> RUN["▶️ Run on the server"]:::auto
    POL -- "anything else" --> ASK["Dialog: exact command,<br/>risk and reason"]:::admin -- confirmed --> RUN

    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

| Step | Cost | Notes |
|------|------|-------|
| 1. Template | 0 tokens | The command is built for the server's profile (systemd / SysVinit) |
| 2. Cache | 0 tokens | Claude's earlier answer to the same phrase for the same kind of server |
| 3. Claude | tokens | Only for new, unusual requests |
| 4. Keywords | 0 tokens | Fallback when Claude has no answer or is unavailable |

Risk levels come from `config/safe_actions.yaml`: read-only commands are risk 0, restarts of listed services risk 1, `stop` risk 2, anything unrecognised risk 3. Only risk 0 and allowed restarts run without the dialog; a confirmation is valid for the same user for 5 minutes.

## Where it is in the code

| What | File |
|------|------|
| Phrase parsing: templates + cache | `src/core/command_resolver.py` |
| Calls to Claude | `src/core/claude_client.py` |
| Risk classification, pending confirmations | `src/actions/policy.py`, `src/actions/pending.py` |
| `/api/execute`, `/api/execute/confirm`, `/api/console/exec` | `src/web/routes/commands.py` |
| Execute button, confirmation dialog, history | `web/js/app.js` |

---
[← Background monitoring](03-monitoring.md) · [Map](README.md) · [Next: GPON / ONU →](05-onu.md)
