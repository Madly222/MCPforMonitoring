[← Синхронизация MAC](06a-netbox-mac-sync.md) · **6b** · [Карта](README.md) · [Дальше: Отключения света и воды →](07-outages.md)

# 🔗 NetBox: CDP и автозаполнение со свитчей и роутеров

Режим **Single Device** (и **Batch Mode**) на вкладке **NetBox**. Панель заходит на Cisco по SSH, читает настройки портов и соседей по **CDP** и переносит это в NetBox: режимы портов, VLAN, описания, IP и **кабели между устройствами**.

**CDP** (Cisco Discovery Protocol) — каждое Cisco-устройство сообщает соседям своё имя и порт. Поэтому свитч знает: «на моём Gi0/1 сидит SW122, его порт Gi1/31». По этим данным панель и прокладывает кабели в NetBox.

## Работа в два шага

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    A["🔍 Scan<br/>читает с устройства"]:::admin --> B["📋 Таблица портов<br/>с галочками"]:::admin
    B --> C["✅ Apply<br/>пишет в NetBox<br/>только отмеченные порты"]:::admin
    D["🚀 Batch Mode"]:::admin -. "Scan + Apply сразу,<br/>все порты, без таблицы" .-> C

    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
```

---

## 🔀 Свитч: что читается при Scan

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["🔍 Scan свитча"]):::root

    ROOT --> CON["🔌 Подключение"]:::group
    CON --> C1["Устройство ищется в NetBox<br/>по IP"]:::auto
    CON --> C2["SSH, поддержка<br/>старых IOS"]:::auto
    CON --> C3["Имя берётся<br/>из приглашения CLI"]:::auto

    ROOT --> PORTS["📡 Порты"]:::group
    PORTS --> P1["show interfaces status —<br/>только connected"]:::auto
    PORTS --> P2["show running-config interface —<br/>описание, access / trunk"]:::auto
    PORTS --> P3["VLAN: access, native,<br/>allowed — диапазоны раскрываются"]:::auto

    ROOT --> CDP["🔗 CDP"]:::group
    CDP --> D1["show cdp neighbors detail"]:::auto
    CDP --> D2["Имя соседа без домена<br/>+ его порт + платформа"]:::auto

    ROOT --> MATCH["🧩 Сопоставление с NetBox"]:::group
    MATCH --> M1["Свой интерфейс —<br/>по вариантам имени"]:::auto
    MATCH --> M2["Есть ли уже кабель"]:::auto
    MATCH --> M3["Сосед и его интерфейс"]:::auto

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

### Как находится сосед в NetBox

Имя из CDP и имя в NetBox часто отличаются (например, `CIS-NX3K-SW36-N.TST` против `CIS-NX3K-SW36-ECB`). Поэтому сосед ищется в три попытки:

1. **точное имя** (домен уже отрезан);
2. **по номеру свитча** `SWnn`; если таких устройств несколько — уточняется по модели (`NX3K`, `4948`, `2950`…);
3. **по началу имени**, отрезая части с конца — пока не останется ровно одно совпадение.

Имя порта тоже пробуется в разных написаниях: `Gi0/1` ↔ `GigabitEthernet0/1`, `[Gi]1/46`, `Fa1/0/1` ↔ `Fa1/01`, `Eth1/N` и т. д.

## 🔀 Свитч: что пишется при Apply

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["✅ Apply свитча"]):::root

    ROOT --> S1["1️⃣ Управление"]:::group
    S1 --> A1["Интерфейс Vlan200,<br/>если VLAN 200 есть в NetBox"]:::admin
    S1 --> A2["IP устройства /24<br/>на Vlan200"]:::admin

    ROOT --> S2["2️⃣ Каждый отмеченный порт"]:::group
    S2 --> B1["trunk → tagged<br/>+ список VLAN"]:::admin
    S2 --> B2["access → access<br/>+ untagged VLAN"]:::admin
    S2 --> B3["Описание порта"]:::admin
    S2 --> B4["Порта нет в NetBox —<br/>пропуск, не создаётся"]:::auto

    ROOT --> S3["3️⃣ Кабель по CDP"]:::group
    S3 --> C1["Оба конца найдены —<br/>старые кабели на обоих<br/>концах удаляются"]:::admin
    S3 --> C2["Создаётся кабель<br/>CAT6, connected"]:::admin
    S3 --> C3["Сосед не найден —<br/>кабель пропускается"]:::auto

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

### Пример: из CDP в кабель NetBox

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart TB
    CLI["🖥️ SW36 говорит по CDP:<br/>«на Gi0/1 сосед<br/>CIS-4948-SW122.rapidlink.local,<br/>его порт Gi1/31»"]:::auto
    CLI --> N1["NetBox: SW36 / Gi0/1 ✅"]:::nb
    CLI --> N2["NetBox: SW122 / Gi1/31 ✅"]:::nb
    N1 --> CAB["🔗 Кабель CAT6<br/>SW36 Gi0/1 ↔ SW122 Gi1/31"]:::nb
    N2 --> CAB

    classDef auto fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef nb   fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
```

---

## 🌐 Роутер: Scan и Apply

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["🌐 Роутер Cisco"]):::root

    ROOT --> SCAN["🔍 Scan читает"]:::group
    SCAN --> R1["show ip interface brief —<br/>интерфейсы, IP, статус"]:::auto
    SCAN --> R2["Описания интерфейсов,<br/>ip mtu у туннелей"]:::auto
    SCAN --> R3["show ip route connected —<br/>только для просмотра"]:::auto
    SCAN --> R4["show cdp neighbors detail"]:::auto
    SCAN --> R5["show version — модель,<br/>серийник, IOS, uptime"]:::auto

    ROOT --> DEV["🖥️ Устройство в NetBox"]:::group
    DEV --> D1["Ищется по имени,<br/>потом по IP"]:::admin
    DEV --> D2["Не найдено —<br/>создаётся с моделью и серийником"]:::admin

    ROOT --> APPLY["✅ Apply пишет"]:::group
    APPLY --> A1["Интерфейс — создаётся,<br/>если его нет"]:::admin
    APPLY --> A2["Описание и MTU"]:::admin
    APPLY --> A3["IP /24 — пересоздаётся<br/>на этом интерфейсе"]:::admin
    APPLY --> A4["Кабели по CDP —<br/>как у свитча"]:::admin

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

## Свитч и роутер: в чём разница

| | 🔀 Свитч | 🌐 Роутер |
|---|---|---|
| Какие порты берутся | только `connected` | все из `show ip interface brief` |
| Нет устройства в NetBox | Scan предупреждает, Apply ничего не запишет | создаётся новое устройство |
| Нет интерфейса в NetBox | порт пропускается | интерфейс создаётся |
| VLAN | режим и VLAN пишутся | не пишутся |
| IP | только управляющий IP на Vlan200 | IP каждого интерфейса |
| Кабели по CDP | да, CAT6 | да, CAT6 |
| Batch Mode | есть | нет |

## ⚠️ Что важно знать перед Apply

| Поведение | Почему важно |
|-----------|-------------|
| **Scan уже меняет NetBox:** если имя устройства в NetBox не совпадает с hostname из CLI, устройство переименовывается сразу при сканировании, ещё до Apply | Scan — не «только чтение» |
| **Кабели перезаписываются:** перед созданием нового кабеля старые кабели на **обоих** концах удаляются | ручные правки кабелей на этих портах пропадут |
| **Тип кабеля всегда CAT6**, даже если это оптика | тип придётся поправить руками |
| **Маска всегда /24:** и для Vlan200 у свитча, и для IP у роутера | для других масок IP будет записан неверно |
| **IP роутера пересоздаётся:** существующие записи с этим адресом удаляются и создаются заново | пропадают custom-поля этого IP, в том числе `MAC` из [Sync MAC](06a-netbox-mac-sync.md) |
| **Поиск соседа по `SWnn` нечёткий:** при нескольких похожих именах может выбраться не то устройство | стоит проверить таблицу портов перед Apply |
| **Batch Mode применяет все порты без просмотра** | для незнакомых устройств лучше Single Device |

## Где это в коде

| Что | Файл |
|-----|------|
| SSH к Cisco, разбор CLI и CDP | `services/netbox-autofill/ssh_connector.py` |
| Scan и Apply свитча | `services/netbox-autofill/orchestrator.py` |
| Поиск устройств и интерфейсов, кабели | `services/netbox-autofill/netbox_client.py` |
| Scan и Apply роутера, Batch | `src/web/api_netbox.py` |
| Вкладка NetBox | `web/js/netbox.js` |

---
[← Синхронизация MAC](06a-netbox-mac-sync.md) · [Карта](README.md) · [Дальше: Отключения света и воды →](07-outages.md)
