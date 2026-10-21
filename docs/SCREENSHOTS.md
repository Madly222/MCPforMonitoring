# Screenshot gallery

Every major screen of NetOps Control Plane, grouped like the [feature map](features/README.md).
All data is made up: servers, OLTs, subscribers, MAC and serial numbers are fictional, and IP addresses
come from the documentation ranges 192.0.2.0/24, 198.51.100.0/24 and 203.0.113.0/24.

- [1. Access and roles](#1-access-and-roles)
- [2. Servers and services](#2-servers-and-services)
- [3. Terminal and AI commands](#3-terminal-and-ai-commands)
- [4. GPON / ONU](#4-gpon--onu)
- [5. NetBox](#5-netbox)
- [6. Power and water outages](#6-power-and-water-outages)
- [7. Superadmin console](#7-superadmin-console)

## 1. Access and roles

Feature tree: [01-access](features/01-access.md)

**Sign-in page.**

![Login](screenshots/gallery/01-login.png)

**Operator view.** Same dashboard, but no Settings section and no service-restart button in the header.

![Operator dashboard](screenshots/gallery/02-operator-dashboard.png)

**Operator server details.** Read-only: no Restart / Stop controls for services.

![Operator server details](screenshots/gallery/03-operator-server-details.png)

**Change password**, available to every role.

![Change password](screenshots/gallery/04-change-password.png)

## 2. Servers and services

Feature tree: [02-servers](features/02-servers.md)

**Dashboard.** Service state per server; an unreachable host shows the SSH error and a Retry button.

![Servers](screenshots/01-servers.png)

**Server details.** OS, hardware, network, firewall and per-service controls (admin and superadmin).

![Server details](screenshots/03-server-details.png)

**Service action confirmation.** Every state-changing action is confirmed and written to the audit log.

![Restart a service](screenshots/gallery/06-service-restart-confirm.png)

**Restarting the monitor itself** (superadmin only).

![Restart the monitor](screenshots/gallery/07-restart-monitor-confirm.png)

**Incidents.** Errors found in the server logs. Known ones carry a diagnosis and a fix plan, each command with its risk and the policy's verdict, and an admin can apply it; unknown ones go to Claude when an API key is set. Feature tree: [03-monitoring](features/03-monitoring.md).

![Incidents](screenshots/08-incidents.png)

## 3. Terminal and AI commands

Feature tree: [04-terminal](features/04-terminal.md)

**Interpret mode.** A plain-language request is turned into a shell command, run over SSH and summarised by Claude.

![AI console](screenshots/02-ai-console.png)

**Confirmation of a risky command.** A command the risk policy does not let run on its own comes back with the exact command line, its risk and the reason, and runs only if the same admin confirms it.

![Confirm a risky command](screenshots/09-confirm-command.png)

**Direct SSH console.** Pick a server, optionally run with sudo.

![SSH console](screenshots/gallery/05-ssh-console.png)

## 4. GPON / ONU

Feature tree: [05-onu](features/05-onu.md)

**OLT overview.** Online / low signal / offline and registration state per OLT.

![OLTs](screenshots/04-olts.png)

**ONU list.** Rx/Tx optical levels, offline reasons, registration on the OLT.

![ONU list](screenshots/05-onus.png)

**Filter: low signal.**

![Low signal filter](screenshots/gallery/09-onu-low-signal.png)

**Search** by client, port, MAC or serial number.

![ONU search](screenshots/gallery/10-onu-search.png)

## 5. NetBox

Feature trees: [06-netbox](features/06-netbox.md), [06a MAC sync](features/06a-netbox-mac-sync.md), [06b CDP](features/06b-netbox-cdp.md)

**Switch scan.** Ports, VLANs and CDP neighbours, ready to push to NetBox.

![Switch scan](screenshots/06-netbox.png)

**Router scan.** Model, IOS version, interfaces with addresses and state.

![Router scan](screenshots/gallery/11-netbox-router.png)

**MAC sync.** DHCP leases matched to NetBox interfaces.

![MAC sync](screenshots/gallery/12-netbox-sync-mac.png)

**Batch mode.** Several switches in one run; problems such as a missing VLAN are reported per device.

![Batch mode](screenshots/gallery/13-netbox-batch.png)

## 6. Power and water outages

Feature tree: [07-outages](features/07-outages.md)

**Planned outage found.** The ⚡ indicator in the header turns red; clicking it lists the matching notices.

![Power outage alert](screenshots/gallery/08-power-outage-alert.png)

**Monitored addresses, match pattern and check schedule.**

![Outage settings](screenshots/gallery/17-settings.png)

**E-mail notification channels.**

![Notifications](screenshots/gallery/18-notifications.png)

## 7. Superadmin console

Feature tree: [08-admin](features/08-admin.md)

**Users and roles.**

![Users](screenshots/gallery/14-users.png)

**Servers configuration.** Add and edit monitored servers without touching files.

![Servers configuration](screenshots/gallery/15-servers-config.png)

**OLT devices.**

![OLT configuration](screenshots/gallery/16-olts-config.png)

**`.env` editor.** Secrets are never sent back to the browser; a blank field keeps the stored value.

![.env editor](screenshots/gallery/19-env-editor.png)

**Audit log.** Who did what, from where, and whether it succeeded.

![Audit log](screenshots/07-audit.png)
