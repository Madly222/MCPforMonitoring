[← Map](README.md) · **1 / 8** · [Next: Servers and services →](02-servers.md)

# 🔐 Access and roles

Who can sign in to the panel, what they are allowed to do, and how that is enforced.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["🔐 Access and roles"]):::root

    ROOT --> LOGIN["🚪 Sign-in"]:::group
    LOGIN --> L1["Username + password<br/>bcrypt hashes, 10+ characters"]:::all
    LOGIN --> L2["Session: random token in an HttpOnly cookie,<br/>server keeps only its hash; survives restarts"]:::auto
    LOGIN --> L3["Lockout after repeated failures<br/>per username and per IP"]:::auto
    LOGIN --> L4["Sign out button"]:::all

    ROOT --> ROLES["🎭 Three roles"]:::group
    ROLES --> R1["👁 operator<br/>read-only"]:::all
    ROLES --> R2["🛠 admin<br/>+ commands, confirmations, fixes,<br/>OLT polling, NetBox writes"]:::admin
    ROLES --> R3["👑 superadmin<br/>+ admin console<br/>+ restart the panel"]:::super

    ROOT --> SELF["🙋 Self-service"]:::group
    SELF --> S1["🔑 Change your own password<br/>header button; ends your other sessions"]:::all

    ROOT --> GUARD["🛡️ Safeguards"]:::group
    GUARD --> G1["The last superadmin<br/>cannot be deleted or demoted"]:::super
    GUARD --> G2["Every privileged action<br/>goes to the audit log"]:::auto
    GUARD --> G3["Role is re-read on every request:<br/>demotion or deletion applies at once"]:::auto
    GUARD --> G4["The UI hides buttons, and the server<br/>checks the role anyway"]:::auto

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef all   fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef super fill:#fde2e2,stroke:#dc2626,color:#7f1d1d
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

## Who can do what

| Capability | 👁 operator | 🛠 admin | 👑 superadmin |
|------------|:-:|:-:|:-:|
| View servers, ONUs, incidents, indicators, reports | ✅ | ✅ | ✅ |
| Change own password | ✅ | ✅ | ✅ |
| Run an outage check "now" | ✅ | ✅ | ✅ |
| Terminal: AI commands and the raw SSH console | — | ✅ | ✅ |
| Confirm a risky command, apply a suggested fix | — | ✅ | ✅ |
| Restart / reload services on servers | — | ✅ | ✅ |
| Poll an OLT "now" | — | ✅ | ✅ |
| NetBox: scan, apply, sync MACs and ports | — | ✅ | ✅ |
| Admin console (**Admin** tab) | — | — | ✅ |
| 🔄 Restart the panel itself (`mcp-monitor`) | — | — | ✅ |

The required role of every API route is listed in `tests/test_route_roles.py`; a new route fails the tests until it is added there.

## Where it is in the code

| What | File |
|------|------|
| Sign-in, sessions, lockout, role checks | `src/web/auth.py` |
| User store (`sessions/users.json`) | `src/web/users.py` |
| Audit log (`logs/audit.jsonl`) | `src/web/audit.py` |
| User management from the command line | `scripts/manage_users.py` |

---
[← Map](README.md) · [Next: Servers and services →](02-servers.md)
