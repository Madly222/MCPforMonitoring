[← GPON / ONU](05-onu.md) · **6 / 8** · [Карта](README.md) · [Дальше: Синхронизация MAC →](06a-netbox-mac-sync.md)

# 🗂️ NetBox

Вкладка **NetBox** — панель сама заполняет NetBox данными с реального оборудования, чтобы не переносить их руками.
Все действия — для **admin** и **superadmin**.

Это обзорная страница. Подробности вынесены в две отдельные:

| Подробно | Что внутри |
|----------|-----------|
| [🔄 Синхронизация MAC и портов](06a-netbox-mac-sync.md) | откуда берутся MAC, как находится порт абонента, что значит каждый статус в отчёте, настройки |
| [🔗 CDP и автозаполнение](06b-netbox-cdp.md) | какие команды выполняются на Cisco, как ищется сосед по CDP, что именно пишется в NetBox, о чём помнить перед Apply |

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["🗂️ NetBox"]):::root

    ROOT --> SW["🔀 Single Device: свитч Cisco"]:::group
    SW --> SW0["Вход по SSH или RADIUS"]:::admin
    SW --> SW1["Порты, описания,<br/>VLAN access / trunk / native"]:::admin
    SW --> SW2["Соседи по CDP"]:::admin
    SW --> SW3["Предпросмотр → Apply:<br/>интерфейсы, VLAN, кабели"]:::admin

    ROOT --> RT["🌐 Single Device: роутер Cisco"]:::group
    RT --> RT1["Интерфейсы, IP,<br/>маршруты, CDP"]:::admin
    RT --> RT2["Apply:<br/>интерфейсы, IP, кабели"]:::admin

    ROOT --> BATCH["🚀 Batch Mode"]:::group
    BATCH --> B1["Список IP —<br/>по одному в строке"]:::admin
    BATCH --> B2["Run All:<br/>скан + запись по каждому"]:::admin

    ROOT --> SYNC["🔄 Синхронизации"]:::group
    SYNC --> Y1["Sync MAC<br/>phpDHCPAdmin → NetBox"]:::admin
    SYNC --> Y2["Sync Ports<br/>MAC → порт абонента → NetBox"]:::admin

    ROOT --> HB["🚦 Индикатор NetBox API<br/>в шапке"]:::all

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef all   fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
```

| Кнопка | Откуда | Куда | Зачем | Подробно |
|--------|--------|------|-------|:-:|
| 🔍 Scan → Apply | свитч / роутер по SSH + CDP | интерфейсы, VLAN, IP, кабели | NetBox отражает реальную коммутацию | [6b](06b-netbox-cdp.md) |
| 🚀 Run All | список IP свитчей | то же самое пачкой, без просмотра | обойти весь узел за раз | [6b](06b-netbox-cdp.md) |
| 🔄 Sync MAC | база phpDHCPAdmin | поле MAC у IP-адреса | знать, какое устройство за каким IP | [6a](06a-netbox-mac-sync.md) |
| 🔗 Sync Ports | MAC-таблицы Cisco, TP-Link, D-Link, MikroTik, ZTE OLT | привязка IP к интерфейсу | видеть, в каком порту сидит абонент | [6a](06a-netbox-mac-sync.md) |

## Где это в коде

| Что | Файл |
|-----|------|
| Эндпоинты `/api/netbox/*` | `src/web/api_netbox.py` |
| SSH к Cisco (в т.ч. старые IOS) | `services/netbox-autofill/ssh_connector.py` |
| Запись в NetBox | `services/netbox-autofill/netbox_client.py`, `orchestrator.py` |
| Sync MAC / Sync Ports | `src/monitoring/dhcp_mac_sync.py`, `src/monitoring/mac_port_sync.py` |
| Вкладка NetBox | `web/js/netbox.js` |

---
[← GPON / ONU](05-onu.md) · [Карта](README.md) · [Дальше: Синхронизация MAC →](06a-netbox-mac-sync.md)
