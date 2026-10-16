# 🌳 Карта возможностей MCP Server Monitor

Приложение большое, поэтому возможности разбиты на **8 отдельных деревьев**.
Здесь — только верхний уровень. Открывайте нужную ветку, внутри каждой — подробное дерево «что, где и зачем».

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    APP(["🛰️ MCP Server Monitor<br/>веб-панель :4455"]):::root

    APP --> A["🔐 Доступ и роли"]:::group
    APP --> B["🖥️ Серверы и сервисы"]:::group
    APP --> C["📈 Фоновый мониторинг"]:::group
    APP --> D["⌨️ Терминал и AI-команды"]:::group
    APP --> E["📡 GPON / ONU"]:::group
    APP --> F["🗂️ NetBox"]:::group
    APP --> G["⚡💧 Отключения света и воды"]:::group
    APP --> H["👑 Консоль superadmin"]:::group

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
```

| # | Дерево | Что внутри | Вкладка в UI |
|:-:|--------|-----------|--------------|
| 1 | [🔐 Доступ и роли](01-access.md) | вход, сессии, 3 роли, смена пароля, аудит | экран входа, шапка |
| 2 | [🖥️ Серверы и сервисы](02-servers.md) | карточки серверов, DHCP / DNS / RADIUS, отчёт о сервере | **Servers** |
| 3 | [📈 Фоновый мониторинг](03-monitoring.md) | слежение за логами, распознавание ошибок, health-check, индикаторы в шапке | работает само, видно в шапке |
| 4 | [⌨️ Терминал и AI-команды](04-terminal.md) | команды обычным языком через Claude, прямая SSH-консоль | **Servers → Terminal Interpretation** |
| 5 | [📡 GPON / ONU](05-onu.md) | OLT ZTE C320, оптический сигнал, регистрация ONU, поиск и фильтры | **ONU** |
| 6 | [🗂️ NetBox](06-netbox.md) | автозаполнение NetBox со свитчей и роутеров, синхронизация MAC и портов | **NetBox** |
| 6a | ↳ [🔄 Синхронизация MAC и портов](06a-netbox-mac-sync.md) | phpDHCPAdmin → MAC → порт абонента, разбор отчёта | **NetBox → Sync MAC / Sync Ports** |
| 6b | ↳ [🔗 CDP и автозаполнение](06b-netbox-cdp.md) | что читается с Cisco, как строятся кабели, что пишется в NetBox | **NetBox → Single Device / Batch** |
| 7 | [⚡💧 Отключения света и воды](07-outages.md) | Premier Energy, acc.md, расписание проверок, письма | шапка ⚡ 💧, **Admin → Settings** |
| 8 | [👑 Консоль superadmin](08-admin.md) | пользователи, серверы, OLT, настройки, `.env`, журнал аудита | **Admin** |

## 🎨 Как читать деревья

Во всех деревьях цвет листа показывает, **кому доступна функция**:

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    L1["👁 Все роли<br/>(operator и выше)"]:::all
    L2["🛠 admin и выше"]:::admin
    L3["👑 Только superadmin"]:::super
    L4["⚙️ Работает автоматически"]:::auto
    L5["🚧 Запланировано,<br/>ещё не включено"]:::plan

    classDef all   fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef super fill:#fde2e2,stroke:#dc2626,color:#7f1d1d
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef plan  fill:#f3f4f6,stroke:#9ca3af,color:#6b7280,stroke-dasharray:5 4
```

> Архитектура «изнутри» (модули, потоки данных) описана отдельно — в [ARCHITECTURE.md](../ARCHITECTURE.md).
> Эти деревья — взгляд **пользователя**: что приложение умеет и где это найти.
