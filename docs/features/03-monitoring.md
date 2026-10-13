[← Серверы и сервисы](02-servers.md) · **3 / 8** · [Карта](README.md) · [Дальше: Терминал и AI-команды →](04-terminal.md)

# 📈 Фоновый мониторинг

То, что панель делает **сама**, без нажатия кнопок: следит за логами, распознаёт ошибки и проверяет здоровье серверов.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["📈 Фоновый мониторинг"]):::root

    ROOT --> LOG["📜 Слежение за логами"]:::group
    LOG --> L1["tail -F логов по SSH<br/>в реальном времени"]:::auto
    LOG --> L2["Само переподключается<br/>при обрыве"]:::auto

    ROOT --> ERR["🔎 Распознавание ошибок"]:::group
    ERR --> E1["Сверка с базой известных ошибок<br/>диагноз + советы"]:::auto
    ERR --> E2["Фильтр шума —<br/>игнор-шаблоны"]:::auto
    ERR --> E3["Без дублей:<br/>одна ошибка не спамит"]:::auto

    ROOT --> HEALTH["🩺 Health-check"]:::group
    HEALTH --> H1["Каждые 60 с<br/>по всем серверам и сервисам"]:::auto
    HEALTH --> H2["healthy · degraded<br/>unhealthy · unreachable"]:::all

    ROOT --> TOP["🚦 Индикаторы в шапке"]:::group
    TOP --> T1["🤖 Claude API"]:::all
    TOP --> T2["⚡ Электричество · 💧 Вода"]:::all
    TOP --> T3["🗂️ NetBox API"]:::all
    TOP --> T4["Автопроверка соединений<br/>интервал задаётся в Admin"]:::auto

    ROOT --> NEXT["🚧 Следующие шаги"]:::group
    NEXT --> N1["Разбор неизвестных ошибок<br/>через Claude"]:::plan
    NEXT --> N2["Автоисправление<br/>по safe_actions.yaml"]:::plan

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef all   fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef plan  fill:#f3f4f6,stroke:#9ca3af,color:#6b7280,stroke-dasharray:5 4
```

## Что происходит со строкой лога

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    A["🖥️ Сервер<br/>пишет в лог"]:::auto --> B["📜 Log Watcher<br/>tail -F по SSH"]:::auto
    B --> C{"Шум?"}
    C -- да --> X["🗑️ Пропустить"]:::all
    C -- нет --> D{"Есть в базе<br/>известных ошибок?"}
    D -- да --> E["✅ Диагноз + советы<br/>из known_errors.yaml"]:::all
    D -- нет --> F["⚠️ Неизвестная ошибка<br/>в журнал"]:::all
    F -.-> G["🤖 Анализ Claude"]:::plan
    E -.-> H["🩹 Автоисправление"]:::plan

    classDef all   fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef plan  fill:#f3f4f6,stroke:#9ca3af,color:#6b7280,stroke-dasharray:5 4
```

> Пунктир — функции, для которых код уже есть (`claude_client.py`, `safe_actions.yaml`), но в цепочку они ещё не подключены.

## Где это в коде

| Что | Файл |
|-----|------|
| Слежение за логами | `src/monitoring/log_watcher.py` |
| Распознавание ошибок | `src/monitoring/error_detector.py` |
| База ошибок и шума | `knowledge_base/known_errors.yaml`, `knowledge_base/ignore_patterns.yaml` |
| Health-check | `src/monitoring/health_checker.py` |
| Интервалы и пороги | `config/settings.yaml` |
| Запуск всех фоновых задач | `src/web/app.py` (lifespan) |

---
[← Серверы и сервисы](02-servers.md) · [Карта](README.md) · [Дальше: Терминал и AI-команды →](04-terminal.md)
