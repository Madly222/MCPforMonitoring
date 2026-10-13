[← CDP и автозаполнение](06b-netbox-cdp.md) · **7 / 8** · [Карта](README.md) · [Дальше: Консоль superadmin →](08-admin.md)

# ⚡💧 Отключения света и воды

Панель раз в день читает сайты поставщиков и предупреждает по почте, если плановое отключение затронет наши адреса.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["⚡💧 Отключения"]):::root

    ROOT --> EL["⚡ Электричество<br/>Premier Energy"]:::group
    EL --> E1["Читает страницу<br/>плановых работ"]:::auto
    EL --> E2["Сверяет со списком адресов,<br/>учитывая номера домов"]:::auto

    ROOT --> WA["💧 Вода<br/>acc.md"]:::group
    WA --> W1["Читает страницу<br/>отключений"]:::auto
    WA --> W2["Ищет совпадение<br/>по шаблону"]:::auto

    ROOT --> TIME["⏰ Расписание"]:::group
    TIME --> T1["Раз в день, своё время<br/>для света и для воды"]:::auto
    TIME --> T2["Пропустил из-за рестарта —<br/>догонит после запуска"]:::auto

    ROOT --> MAIL["✉️ Уведомления"]:::group
    MAIL --> M1["Письмо, если есть<br/>совпадения"]:::auto
    MAIL --> M2["Одно и то же письмо<br/>дважды не уходит"]:::auto

    ROOT --> UI["🖱️ В интерфейсе"]:::group
    UI --> U1["⚡ 💧 индикаторы в шапке"]:::all
    UI --> U2["Проверить прямо сейчас"]:::all

    ROOT --> CONF["⚙️ Настройка<br/>Admin → Settings"]:::group
    CONF --> C1["Список адресов для света"]:::super
    CONF --> C2["Шаблон адреса для воды"]:::super
    CONF --> C3["Время проверки"]:::super

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef all   fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef super fill:#fde2e2,stroke:#dc2626,color:#7f1d1d
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

## Один день из жизни проверки

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    CLK["⏰ Наступило время<br/>из настроек"]:::auto --> GET["🌐 Скачать страницу<br/>поставщика"]:::auto
    GET --> MATCH{"Есть наши адреса?"}
    MATCH -- нет --> GREEN["🟢 Индикатор зелёный"]:::all
    MATCH -- да --> DUP{"Такое письмо<br/>уже отправляли?"}
    DUP -- да --> RED["🔴 Индикатор красный,<br/>письмо не дублируется"]:::all
    DUP -- нет --> SEND["✉️ Отправить письмо"]:::auto --> RED

    classDef all  fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef auto fill:#fef3c7,stroke:#d97706,color:#78350f
```

> Почтовые настройки (SMTP, получатели) лежат в `.env`. Их можно поправить во вкладке **Admin → Settings → .env** — см. [👑 Консоль superadmin](08-admin.md).
> Вместо встроенного расписания можно использовать systemd-таймеры из `scripts/`, но **не оба сразу** для одного канала.

## Где это в коде

| Что | Файл |
|-----|------|
| Свет — Premier Energy | `src/monitoring/electric_monitor.py`, адреса в `config/electric_addresses.txt` |
| Вода — acc.md | `src/monitoring/acc_monitor.py` |
| Встроенное расписание | `src/monitoring/outage_scheduler.py` |
| Настройки, меняемые на лету | `src/web/runtime_config.py` |

---
[← CDP и автозаполнение](06b-netbox-cdp.md) · [Карта](README.md) · [Дальше: Консоль superadmin →](08-admin.md)
