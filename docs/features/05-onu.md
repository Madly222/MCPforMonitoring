[← Терминал и AI-команды](04-terminal.md) · **5 / 8** · [Карта](README.md) · [Дальше: NetBox →](06-netbox.md)

# 📡 GPON / ONU

Вкладка **ONU** — абонентские терминалы на OLT ZTE C320: есть ли сигнал, какой он, зарегистрирована ли ONU.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["📡 GPON / ONU"]):::root

    ROOT --> OLT["🏢 OLT ZTE C320"]:::group
    OLT --> O1["Список ONU<br/>сгруппирован по OLT"]:::all
    OLT --> O2["Фоновый опрос<br/>по расписанию"]:::auto
    OLT --> O3["📡 Poll now —<br/>опросить прямо сейчас"]:::admin

    ROOT --> SIG["💡 Оптический статус"]:::group
    SIG --> S1["🟢 online · 🔴 offline<br/>🟡 low signal"]:::all
    SIG --> S2["Мощность Rx в dBm<br/>берётся из CLI OLT"]:::auto
    SIG --> S3["Порог «слабый сигнал»<br/>по умолчанию −25 dBm"]:::auto

    ROOT --> REG["🪪 Регистрация на OLT"]:::group
    REG --> R1["registered /<br/>not registered"]:::all
    REG --> R2["Отдельно от сигнала:<br/>ONU может светить,<br/>но не быть заведённой"]:::all

    ROOT --> INFO["🏷️ Данные ONU"]:::group
    INFO --> I1["Порт · ID · серийный номер<br/>описание"]:::all
    INFO --> I2["MAC-адрес<br/>через SSH на OLT"]:::auto

    ROOT --> FIND["🔍 Работа со списком"]:::group
    FIND --> F1["Поиск по имени, порту,<br/>MAC, серийнику"]:::all
    FIND --> F2["Фильтры: All · Online · Offline<br/>Low Signal · Not registered"]:::all
    FIND --> F3["Сортировка по порту"]:::all

    ROOT --> CONF["⚙️ Настройка"]:::group
    CONF --> C1["Добавить / изменить OLT<br/>Admin → OLT Devices"]:::super
    CONF --> C2["SNMP v2c / v3 + SSH"]:::super

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef all   fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef super fill:#fde2e2,stroke:#dc2626,color:#7f1d1d
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

## Зачем разделены «сигнал» и «регистрация»

| Сигнал | Регистрация | Что это значит на практике |
|--------|-------------|----------------------------|
| 🟢 online | registered | Всё в порядке |
| 🟡 low signal | registered | Абонент работает, но линию пора проверять (грязный коннектор, изгиб) |
| 🔴 offline | registered | Нет света: ONU выключена или обрыв |
| 🟢 online | not registered | ONU светит, но не заведена на OLT — нужна регистрация |

> Фильтр **Not registered** как раз находит четвёртый случай — ONU, которые физически подключены, но не обслуживаются.

## Где это в коде

| Что | Файл |
|-----|------|
| Опрос OLT, сигнал, регистрация, MAC | `src/monitoring/onu_monitor.py` |
| Эндпоинты `/api/onu/*` | `src/web/api.py` |
| Вкладка ONU: поиск, фильтры | `web/js/onu.js` |

---
[← Терминал и AI-команды](04-terminal.md) · [Карта](README.md) · [Дальше: NetBox →](06-netbox.md)
