[← Servers and services](02-servers.md) · **3 / 8** · [Map](README.md) · [Next: Terminal and AI commands →](04-terminal.md)

# 📈 Background monitoring

What the panel does **on its own**, without anyone pressing a button: it watches logs, recognises errors, plans or applies fixes, and checks server health.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["📈 Background monitoring"]):::root

    ROOT --> LOG["📜 Log watching"]:::group
    LOG --> L1["tail -F over SSH<br/>in real time"]:::auto
    LOG --> L2["Reconnects by itself<br/>when the link drops"]:::auto

    ROOT --> ERR["🔎 Error recognition"]:::group
    ERR --> E1["Matched against known errors:<br/>diagnosis + advice"]:::auto
    ERR --> E2["Noise filter:<br/>ignore patterns"]:::auto
    ERR --> E3["Deduplicated:<br/>one error does not spam"]:::auto
    ERR --> E4["Unknown errors go to Claude<br/>for a diagnosis"]:::auto

    ROOT --> FIX["🩹 Fixes"]:::group
    FIX --> F1["Fix plan for known errors,<br/>each command with its risk"]:::all
    FIX --> F2["Apply fix button"]:::admin
    FIX --> F3["Auto mode: runs what<br/>safe_actions.yaml allows"]:::auto

    ROOT --> HEALTH["🩺 Health checks"]:::group
    HEALTH --> H1["Every 60 s<br/>on all servers and services"]:::auto
    HEALTH --> H2["healthy · degraded<br/>unhealthy · unreachable"]:::all

    ROOT --> TOP["🚦 Header indicators"]:::group
    TOP --> T1["🤖 Claude API"]:::all
    TOP --> T2["⚡ Power · 💧 Water"]:::all
    TOP --> T3["🗂️ NetBox API"]:::all
    TOP --> T4["Automatic connection check<br/>interval set in Admin"]:::auto

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef all   fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

## What happens to a log line

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    A["🖥️ Server<br/>writes to a log"]:::auto --> B["📜 Log watcher<br/>tail -F over SSH"]:::auto
    B --> C{"Noise?"}
    C -- yes --> X["🗑️ Skip"]:::all
    C -- no --> D{"Known<br/>error?"}
    D -- yes --> E["✅ Diagnosis + advice<br/>from known_errors.yaml"]:::all
    E --> P["🩹 Fix plan: each command<br/>classified by the risk policy"]:::auto
    P --> M{"auto_remediation.mode"}
    M -- suggest --> S["Shown on the Incidents card;<br/>an admin applies it"]:::admin
    M -- auto --> R["Allowed commands run,<br/>within cooldowns and limits;<br/>the rest stay suggestions"]:::auto
    D -- no --> F["⚠️ Unknown error"]:::all --> G["🤖 Claude diagnosis;<br/>its commands are shown, never run"]:::auto

    classDef all   fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

The mode is set in `config/settings.yaml > auto_remediation.mode`: `off`, `suggest` (default) or `auto`. Every automatic or applied fix is written to the audit log.

## Where it is in the code

| What | File |
|------|------|
| Log watching | `src/monitoring/log_watcher.py` |
| Error recognition | `src/monitoring/error_detector.py` |
| Error and noise knowledge base | `knowledge_base/known_errors.yaml`, `knowledge_base/ignore_patterns.yaml` |
| Fix plans, auto mode, Claude diagnosis | `src/actions/remediation.py` |
| Risk policy and limits | `src/actions/policy.py`, `config/safe_actions.yaml` |
| Health checks | `src/monitoring/health_checker.py` |
| Intervals, thresholds, mode | `config/settings.yaml` |
| Starting the background tasks | `src/web/app.py` (lifespan) |

---
[← Servers and services](02-servers.md) · [Map](README.md) · [Next: Terminal and AI commands →](04-terminal.md)
