[← Доступ и роли](01-access.md) · **2 / 8** · [Карта](README.md) · [Дальше: Фоновый мониторинг →](03-monitoring.md)

# 🖥️ Серверы и сервисы

Вкладка **Servers** — карточки всех серверов, которые панель обслуживает по SSH, и управление их сервисами.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["🖥️ Серверы и сервисы"]):::root

    ROOT --> CARD["🗂️ Карточка сервера"]:::group
    CARD --> C1["🟢 Онлайн / 🔴 офлайн"]:::all
    CARD --> C2["Список сервисов и их состояние"]:::all
    CARD --> C3["🔌 Переподключить SSH"]:::all
    CARD --> C4["ℹ️ Отчёт: ОС, CPU, RAM, диски, сеть"]:::all

    ROOT --> ACT["🎛️ Управление сервисом"]:::group
    ACT --> A1["▶️ start · ⏹ stop · 🔁 restart · ♻️ reload"]:::admin
    ACT --> A2["🩺 Диагностика: процесс, порт, конфиг"]:::all

    ROOT --> SVC["🧩 Поддерживаемые сервисы"]:::group
    SVC --> S1["DHCP — isc-dhcp · kea · dnsmasq"]:::all
    SVC --> S2["DNS — bind9 · dnsmasq · unbound · PowerDNS"]:::all
    SVC --> S3["RADIUS — FreeRADIUS 2.x / 3.x"]:::all
    SVC --> S4["Почта и веб — Postfix · Dovecot<br/>Apache · SpamAssassin"]:::all

    ROOT --> PROF["🧬 Профиль сервера"]:::group
    PROF --> P1["systemd или SysVinit, дистрибутив"]:::auto
    PROF --> P2["Определяется один раз и запоминается"]:::auto

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef all   fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef super fill:#fde2e2,stroke:#dc2626,color:#7f1d1d
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

## Зачем это нужно

| Ветка | Зачем |
|-------|-------|
| 🗂️ Карточка | За секунду видно, какой сервер лежит и какой сервис на нём упал |
| 🎛️ Управление | Перезапустить DHCP/DNS/RADIUS из браузера, не заходя по SSH |
| 🧩 Сервисы | Тип сервера определяется автоматически — панель сама находит конфиги, логи и файлы аренд. DHCP показывает аренды и пулы, DNS проверяет резолв тестовой зоны, почта и веб — только статус и рестарт |
| 🧬 Профиль | Одна и та же кнопка «restart» работает и на systemd, и на старом SysVinit |

> Добавить, изменить или убрать сервер можно во вкладке **Admin → Servers** — см. [👑 Консоль superadmin](08-admin.md).

## Где это в коде

| Что | Файл |
|-----|------|
| SSH-подключения, выполнение команд | `src/core/ssh_manager.py` |
| Отчёт о сервере | `src/core/system_info.py` |
| Профиль сервера (`sessions/server_profiles.json`) | `src/core/server_profile.py` |
| DHCP / DNS / RADIUS | `src/services/dhcp.py`, `dns.py`, `radius.py` + `config/services/*.yaml` |

---
[← Доступ и роли](01-access.md) · [Карта](README.md) · [Дальше: Фоновый мониторинг →](03-monitoring.md)
