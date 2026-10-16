[← NetBox: обзор](06-netbox.md) · **6a** · [Карта](README.md) · [Дальше: CDP и автозаполнение →](06b-netbox-cdp.md)

# 🔄 NetBox: синхронизация MAC и портов

Две кнопки на вкладке **NetBox**, которые работают **по цепочке**:

1. **🔄 Sync MAC** — берёт пары «IP ↔ MAC» из phpDHCPAdmin и записывает MAC в NetBox.
2. **🔗 Sync Ports** — по этим MAC находит, в каком порту какого устройства сидит абонент, и привязывает его IP к этому интерфейсу в NetBox.

Порядок важен: без шага 1 у IP в NetBox нет MAC, и шагу 2 нечего искать.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart TB
    DB[("🗄️ phpDHCPAdmin<br/>MySQL")]:::src -- "1. 🔄 Sync MAC" --> IP["NetBox: IP-адрес<br/>+ поле MAC"]:::nb
    IP -- "2. 🔗 Sync Ports" --> NET["🔀 Свитчи · 📡 OLT<br/>MAC-таблицы"]:::src
    NET --> ASSIGN["NetBox: IP привязан<br/>к порту абонента"]:::nb

    classDef src fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef nb  fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
```

---

## 1. 🔄 Sync MAC — phpDHCPAdmin → NetBox

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["🔄 Sync MAC"]):::root

    ROOT --> SRC["📥 Откуда берёт"]:::group
    SRC --> S1["SSH на DHCP-сервер"]:::auto
    SRC --> S2["MySQL phpDHCPAdmin,<br/>таблица conf_hosts:<br/>ip-address + mac-address"]:::auto

    ROOT --> CLEAN["🧹 Чистка"]:::group
    CLEAN --> C1["MAC приводится к виду<br/>AA:BB:CC:DD:EE:FF"]:::auto
    CLEAN --> C2["Битые IP и MAC<br/>отбрасываются"]:::auto

    ROOT --> FIND["🔍 Поиск в NetBox"]:::group
    FIND --> F1["IP-адрес ищется<br/>сначала точно, потом поиском"]:::auto

    ROOT --> WRITE["✍️ Что записывает"]:::group
    WRITE --> W1["Только поле MAC<br/>у IP-адреса"]:::admin
    WRITE --> W2["Если MAC уже такой же —<br/>пропуск"]:::auto

    ROOT --> NOT["🚫 Чего НЕ делает"]:::group
    NOT --> N1["Не создаёт IP,<br/>которых нет в NetBox"]:::all
    NOT --> N2["Не трогает другие поля"]:::all

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef all   fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

### Как читать итог

После синхронизации появляется окно с четырьмя числами:

| Число | Что значит | Что делать |
|-------|-----------|-----------|
| **Updated** | MAC записан или исправлен | ничего |
| **Skipped** | в NetBox уже стоял тот же MAC | ничего |
| **Not found** | IP есть в DHCP, но в NetBox такого IP-адреса нет | завести IP в NetBox, если он нужен |
| **Errors** | NetBox не принял запись | смотреть лог сервиса |

---

## 2. 🔗 Sync Ports — MAC → порт абонента → NetBox

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["🔗 Sync Ports"]):::root

    ROOT --> WHO["🗺️ Какие устройства обходит"]:::group
    WHO --> D1["📡 OLT из настроек панели"]:::auto
    WHO --> D2["Устройства NetBox с IP<br/>в mgmt-сети 198.51.100.0/24"]:::auto
    WHO --> D3["Устройства NetBox<br/>с primary IP"]:::auto
    WHO --> D4["Доп. список<br/>config/scan_devices.txt"]:::auto

    ROOT --> VEND["🏷️ Вендор и команда"]:::group
    VEND --> V1["Cisco IOS · Cisco SG<br/>TP-Link · D-Link<br/>show mac address-table"]:::auto
    VEND --> V2["MikroTik<br/>/interface bridge host print"]:::auto
    VEND --> V3["ZTE C320<br/>show mac gpon olt 1/1/1…16"]:::auto
    VEND --> V4["Вендор не опознан —<br/>устройство пропускается"]:::auto

    ROOT --> CRED["🔑 Учётные данные"]:::group
    CRED --> K1["Сначала RADIUS,<br/>потом SSH — из полей вкладки"]:::admin
    CRED --> K2["Поля пустые —<br/>берутся из .env"]:::auto

    ROOT --> LEAF["🎯 Поиск порта абонента"]:::group
    LEAF --> L1["Порт, где ≤ 3 MAC —<br/>абонентский"]:::auto
    LEAF --> L2["Где MAC много —<br/>аплинк, пропуск"]:::auto
    LEAF --> L3["При равенстве<br/>выигрывает gpon-onu"]:::auto

    ROOT --> WR["✍️ Что записывает"]:::group
    WR --> R1["IP привязывается<br/>к интерфейсу устройства"]:::admin
    WR --> R2["Поле MAC у IP<br/>сохраняется"]:::auto
    WR --> R3["Интерфейса нет —<br/>только в отчёт"]:::auto

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

### Как определяется «порт абонента»

Один и тот же MAC абонента виден на многих устройствах: на его коммутаторе доступа, на агрегации, на ядре.
Различаются эти места тем, **сколько всего MAC на порту**. На аплинке их сотни, а на порту абонента один или два (роутер, ТВ-приставка).

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    MAC["💻 MAC абонента<br/>AA:BB:CC:11:22:33"]:::auto
    MAC --> P1["Ядро · Te1/1<br/>412 MAC"]:::skip
    MAC --> P2["Агрегация · Gi0/24<br/>57 MAC"]:::skip
    MAC --> P3["Доступ SW36 · Fa0/7<br/>2 MAC"]:::win
    P1 --> X1["❌ аплинк"]:::skip
    P2 --> X2["❌ аплинк"]:::skip
    P3 --> OK["✅ порт абонента:<br/>IP → SW36 / Fa0/7"]:::win

    classDef auto fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef skip fill:#f3f4f6,stroke:#9ca3af,color:#6b7280
    classDef win  fill:#dcfce7,stroke:#16a34a,color:#14532d
```

Порог в 3 MAC задаётся в `.env` (`MAC_LEAF_THRESHOLD`). Если два порта подходят одинаково, выбирается тот, где MAC меньше, а при полном равенстве — `gpon-onu` (это точно конечная ONU).

### Как читать итог

Короткий итог показывается в окне, подробный — в логе:

| Статус | Что значит | Что делать |
|--------|-----------|-----------|
| **assigned** | IP привязан к новому интерфейсу | ничего |
| **already_ok** | IP уже был на правильном интерфейсе | ничего |
| **no_leaf · unseen** | MAC не найден ни на одном опрошенном устройстве | абонент выключен, или его коммутатор не опрашивается |
| **no_leaf · trunk** | MAC виден только на портах, где больше 3 MAC | за абонентом неуправляемый свитч, или порог мал |
| **iface_missing** | порт найден, но такого интерфейса нет в NetBox | завести интерфейс в NetBox |
| **dev_missing** | устройства с таким именем нет в NetBox | проверить имя устройства в NetBox |
| **failed / skipped** | устройство не опросилось: нет доступа, неверный пароль, неизвестный вендор | список с причинами — в конце лога |

### Учётные данные

На вкладке NetBox есть две пары полей: **RADIUS Login/Pass** и **SSH Login/Pass**.
Для каждого устройства сначала пробуется RADIUS, при ошибке авторизации — SSH. Если устройство просто недоступно, второй вариант не пробуется.
Если все поля пустые, используются `SSH_USERNAME` / `SSH_PASSWORD` из `.env` (для TP-Link — `TPLINK_SSH_*`).

### Настройки в `.env`

| Параметр | По умолчанию | Зачем |
|----------|:-:|-------|
| `MAC_LEAF_THRESHOLD` | `3` | сколько MAC на порту ещё считается абонентским портом |
| `MAC_MGMT_PREFIX` | — (задать в `.env`) | из какой сети брать устройства для опроса |
| `MAC_CREATE_MISSING_IFACE` | `false` | `true` — создавать недостающий интерфейс (с описанием `auto: MAC sync`) вместо записи в отчёт |
| `MAC_SCAN_DEVICES_FILE` | `config/scan_devices.txt` | доп. устройства: `ip,вендор[,имя]` в строке |
| `MAC_OLT_MAX_PORT` | `16` | сколько GPON-портов OLT опрашивать |
| `DHCP_SSH_*`, `DHCP_MYSQL_*` | — | доступ к phpDHCPAdmin для Sync MAC |

Всё это можно поменять в **Admin → Settings → .env** (нужен перезапуск панели).

## Где это в коде

| Что | Файл |
|-----|------|
| Sync MAC | `src/monitoring/dhcp_mac_sync.py` |
| Sync Ports | `src/monitoring/mac_port_sync.py` |
| Работа с NetBox | `services/netbox-autofill/netbox_client.py` |
| Эндпоинты `/api/netbox/sync-mac`, `/sync-interfaces` | `src/web/api_netbox.py` |

---
[← NetBox: обзор](06-netbox.md) · [Карта](README.md) · [Дальше: CDP и автозаполнение →](06b-netbox-cdp.md)
