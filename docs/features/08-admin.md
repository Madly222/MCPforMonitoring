[← Отключения света и воды](07-outages.md) · **8 / 8** · [Карта](README.md)

# 👑 Консоль superadmin

Вкладка **Admin** видна только superadmin. Пять подвкладок — всё, что раньше приходилось править в файлах на сервере.
Изменения применяются **на лету**, без перезапуска (кроме `.env`).

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["👑 Admin"]):::root

    ROOT --> USR["👤 Users"]:::group
    USR --> U1["Создать / удалить"]:::super
    USR --> U2["Сменить пароль"]:::super
    USR --> U3["Сменить роль"]:::super

    ROOT --> SRV["🖥️ Servers"]:::group
    SRV --> S1["Добавить / изменить / убрать<br/>сервер и его сервисы"]:::super
    SRV --> S2["Горячая перезагрузка<br/>без рестарта панели"]:::super

    ROOT --> OLT["📡 OLT Devices"]:::group
    OLT --> O1["Добавить / изменить / убрать OLT"]:::super

    ROOT --> SET["⚙️ Settings"]:::group
    SET --> OUT["⚡💧 Отключения"]:::group
    OUT --> T1["Адреса · шаблон · время"]:::super
    SET --> NET["🔌 Связь"]:::group
    NET --> T2["Автопроверка соединений<br/>вкл/выкл + интервал"]:::super
    NET --> T3["Тайм-аут SSH-подключения"]:::super
    NET --> T4["Тайм-аут команды в терминале"]:::super
    NET --> T5["Тестовая DNS-зона<br/>для проверки резолва"]:::super
    SET --> ENV["📝 Файл .env"]:::group
    ENV --> T6["Редактор, секреты скрыты<br/>нужен перезапуск"]:::super
    SET --> RES["↩️ Сброс к secrets.yaml"]:::group
    RES --> T7["Reload Servers · OLTs · Users"]:::super

    ROOT --> AUD["📋 Log"]:::group
    AUD --> A1["Журнал аудита:<br/>кто, что, когда, с какого IP"]:::super

    ROOT --> RST["🔄 Перезапуск панели<br/>кнопка в шапке"]:::super

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef super fill:#fde2e2,stroke:#dc2626,color:#7f1d1d
```

## Откуда панель берёт настройки

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    Y["📄 secrets.yaml"]:::file -- "первый запуск" --> S[("💾 Хранилище панели<br/>sessions/*.json")]:::store
    UI["👑 Консоль Admin"]:::super -- "правки на лету" --> S
    S --> APP["🛰️ Панель работает<br/>с этими данными"]:::store
    Y -. "↩️ Reload … —<br/>сбросить правки" .-> S
    E["📄 .env<br/>почта, NetBox"]:::file --> APP
    UI -- "редактор .env" --> E

    classDef file  fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef store fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b
    classDef super fill:#fde2e2,stroke:#dc2626,color:#7f1d1d
```

> ⚠️ После первого запуска главным становится **хранилище панели**, а не `secrets.yaml`.
> Правка `secrets.yaml` ничего не изменит, пока не нажать **Reload Servers / OLTs / Users**.

## Где это в коде

| Что | Файл |
|-----|------|
| Эндпоинты `/api/admin/*` | `src/web/admin.py` |
| Хранилище настроек, серверов, OLT | `src/web/runtime_config.py` |
| Безопасная запись `.env` | `src/web/env_config.py` |
| Журнал аудита | `src/web/audit.py` |
| Вкладка Admin | `web/js/admin.js` |

---
[← Отключения света и воды](07-outages.md) · [Карта](README.md)
