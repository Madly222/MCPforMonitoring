[← Фоновый мониторинг](03-monitoring.md) · **4 / 8** · [Карта](README.md) · [Дальше: GPON / ONU →](05-onu.md)

# ⌨️ Терминал и AI-команды

Блок **Terminal Interpretation** на вкладке **Servers**. Один ввод — два режима: выбор в выпадающем списке слева решает, кто выполнит команду.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["⌨️ Терминал"]):::root

    ROOT --> AI["🧠 Режим Interpret<br/>сервер не выбран"]:::group
    AI --> A1["Пишете обычным языком:<br/>«рестартни dhcp на dhcp-93»<br/>«ошибки dns за сегодня»"]:::admin
    AI --> A2["Сервер сам находится<br/>по имени или по сервису"]:::auto
    AI --> A3["Частые команды — без Claude<br/>0 токенов"]:::auto

    ROOT --> RAW["🖥️ Прямой режим<br/>сервер выбран"]:::group
    RAW --> R1["Любая shell-команда<br/>как в обычном SSH"]:::admin
    RAW --> R2["☑️ sudo одной галочкой"]:::admin
    RAW --> R3["stdout · stderr · exit code"]:::admin

    ROOT --> OUT["📋 Результат"]:::group
    OUT --> O1["Окно Output"]:::admin
    OUT --> O2["Command History<br/>✅ / ❌ по каждой команде"]:::admin

    ROOT --> CTRL["🛡️ Контроль"]:::group
    CTRL --> K1["Только admin и superadmin"]:::admin
    CTRL --> K2["Каждая команда —<br/>в журнал аудита"]:::auto
    CTRL --> K3["Тайм-аут команды<br/>20 с по умолчанию, 5–600"]:::super

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef super fill:#fde2e2,stroke:#dc2626,color:#7f1d1d
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

## Как фраза превращается в команду (режим Interpret)

Сначала пробуются бесплатные способы, Claude — только если они не сработали.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    IN["💬 Фраза оператора"]:::admin --> T{"1. Шаблон?<br/>status · logs · errors<br/>restart · start · stop"}
    T -- да --> RUN["▶️ Выполнить на сервере"]:::auto
    T -- нет --> C{"2. Уже решали<br/>такую фразу?"}
    C -- да --> RUN
    C -- нет --> CL["3. 🤖 Спросить Claude"]:::auto
    CL -- "уверенность > 0.7" --> SAVE["💾 Запомнить в кэш"]:::auto --> RUN
    CL -- "не уверен / API недоступен" --> KW["4. Разбор по ключевым словам"]:::auto --> RUN

    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

| Шаг | Стоимость | Пояснение |
|-----|-----------|-----------|
| 1. Шаблон | 0 токенов | Команда собирается под профиль сервера (systemd / SysVinit) |
| 2. Кэш | 0 токенов | Ответ Claude на ту же фразу для того же типа сервера |
| 3. Claude | токены | Только для новых, нестандартных запросов |
| 4. Ключевые слова | 0 токенов | Запасной вариант, если Claude не уверен или недоступен |

## Где это в коде

| Что | Файл |
|-----|------|
| Разбор фраз: шаблоны + кэш | `src/core/command_resolver.py` |
| Обращение к Claude | `src/core/claude_client.py` |
| Эндпоинты `/api/execute`, `/api/console/exec` | `src/web/api.py` |
| Кнопка Execute, история | `web/js/app.js` |

---
[← Фоновый мониторинг](03-monitoring.md) · [Карта](README.md) · [Дальше: GPON / ONU →](05-onu.md)
