[← GPON / ONU](05-onu.md) · **6 / 8** · [Карта](README.md) · [Дальше: Отключения света и воды →](07-outages.md)

# 🗂️ NetBox

Вкладка **NetBox** — панель сама заполняет NetBox данными с реального оборудования, чтобы не переносить их руками.
Все действия — для **admin** и **superadmin**.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["🗂️ NetBox"]):::root

    ROOT --> ONE["🔍 Single Device"]:::group
    ONE --> SW["🔀 Свитч Cisco"]:::group
    SW --> SW1["Порты, описания,<br/>VLAN access / trunk / native"]:::admin
    SW --> SW2["Соседи по CDP"]:::admin
    SW --> SW3["Предпросмотр → Apply:<br/>интерфейсы, VLAN, кабели"]:::admin
    ONE --> RT["🌐 Роутер Cisco"]:::group
    RT --> RT1["Интерфейсы, IP,<br/>маршруты, CDP"]:::admin
    RT --> RT2["Apply:<br/>интерфейсы, IP, кабели"]:::admin
    ONE --> CR["Вход по SSH или RADIUS"]:::admin

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

## Как работают синхронизации

Две кнопки работают **по цепочке**: сначала MAC попадают в NetBox, потом по ним находится порт абонента.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    DB[("🗄️ phpDHCPAdmin<br/>MySQL")]:::src -- "🔄 Sync MAC" --> IP["NetBox: IP-адрес<br/>+ поле MAC"]:::nb
    IP -- "🔗 Sync Ports" --> SCAN["Таблицы MAC<br/>со всего оборудования<br/>Cisco · TP-Link · ZTE OLT"]:::src
    SCAN --> LEAF{"Порт, где этот MAC<br/>и мало других MAC?"}
    LEAF -- "да — порт абонента" --> OK["✅ IP привязан<br/>к интерфейсу в NetBox"]:::nb
    LEAF -- "много MAC — аплинк" --> SKIP["⏭️ Пропустить"]:::src
    OK -.-> MISS["Интерфейса нет в NetBox?<br/>→ только в отчёт,<br/>сам не создаётся"]:::src

    classDef src fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef nb  fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
```

| Кнопка | Откуда | Куда | Зачем |
|--------|--------|------|-------|
| 🔍 Scan → Apply | свитч / роутер по SSH | интерфейсы, VLAN, IP, кабели | NetBox отражает реальную коммутацию |
| 🚀 Run All | список IP | то же самое пачкой | обойти весь узел за раз |
| 🔄 Sync MAC | база phpDHCPAdmin | поле MAC у IP-адреса | знать, какое устройство за каким IP |
| 🔗 Sync Ports | MAC-таблицы оборудования | привязка IP к интерфейсу | видеть, в каком порту сидит абонент |

## Где это в коде

| Что | Файл |
|-----|------|
| Эндпоинты `/api/netbox/*` | `src/web/api_netbox.py` |
| SSH к Cisco (в т.ч. старые IOS) | `services/netbox-autofill/ssh_connector.py` |
| Запись в NetBox | `services/netbox-autofill/netbox_client.py`, `orchestrator.py` |
| Sync MAC / Sync Ports | `src/monitoring/dhcp_mac_sync.py`, `src/monitoring/mac_port_sync.py` |
| Вкладка NetBox | `web/js/netbox.js` |

---
[← GPON / ONU](05-onu.md) · [Карта](README.md) · [Дальше: Отключения света и воды →](07-outages.md)
