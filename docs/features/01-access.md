[← Карта](README.md) · **1 / 8** · [Дальше: Серверы и сервисы →](02-servers.md)

# 🔐 Доступ и роли

Кто может войти в панель, что ему разрешено и как это контролируется.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 14, "rankSpacing": 45, "curve": "basis", "padding": 8, "wrappingWidth": 260}}}%%
flowchart LR
    ROOT(["🔐 Доступ и роли"]):::root

    ROOT --> LOGIN["🚪 Вход"]:::group
    LOGIN --> L1["Логин + пароль<br/>пароли хранятся в bcrypt"]:::all
    LOGIN --> L2["Сессия в подписанной cookie<br/>с ограниченным сроком жизни"]:::auto
    LOGIN --> L3["Выход — кнопка Sign out"]:::all

    ROOT --> ROLES["🎭 Три роли"]:::group
    ROLES --> R1["👁 operator<br/>только смотрит"]:::all
    ROLES --> R2["🛠 admin<br/>+ команды, действия, опрос OLT, NetBox"]:::admin
    ROLES --> R3["👑 superadmin<br/>+ консоль администратора<br/>+ перезапуск панели"]:::super

    ROOT --> SELF["🙋 Самообслуживание"]:::group
    SELF --> S1["🔑 Смена своего пароля<br/>кнопка в шапке"]:::all

    ROOT --> GUARD["🛡️ Защита"]:::group
    GUARD --> G1["Последнего superadmin<br/>нельзя удалить или понизить"]:::super
    GUARD --> G2["Каждое привилегированное действие<br/>пишется в журнал аудита"]:::auto
    GUARD --> G3["Интерфейс прячет лишние кнопки,<br/>а сервер всё равно проверяет роль"]:::auto

    classDef root  fill:#1f2937,stroke:#111827,color:#ffffff,font-weight:bold
    classDef group fill:#e0e7ff,stroke:#6366f1,color:#1e1b4b,font-weight:bold
    classDef all   fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef admin fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef super fill:#fde2e2,stroke:#dc2626,color:#7f1d1d
    classDef auto  fill:#fef3c7,stroke:#d97706,color:#78350f
```

## Кто что может

| Возможность | 👁 operator | 🛠 admin | 👑 superadmin |
|-------------|:-:|:-:|:-:|
| Смотреть серверы, ONU, индикаторы, отчёты | ✅ | ✅ | ✅ |
| Сменить свой пароль | ✅ | ✅ | ✅ |
| Запустить проверку отключений «сейчас» | ✅ | ✅ | ✅ |
| Терминал: AI-команды и прямая SSH-консоль | — | ✅ | ✅ |
| Рестарт / reload сервисов на серверах | — | ✅ | ✅ |
| Опрос OLT «сейчас» | — | ✅ | ✅ |
| NetBox: сканирование, применение, синхронизации | — | ✅ | ✅ |
| Консоль администратора (вкладка **Admin**) | — | — | ✅ |
| 🔄 Перезапуск самой панели (`mcp-monitor`) | — | — | ✅ |

## Где это в коде

| Что | Файл |
|-----|------|
| Вход, выход, смена пароля, проверка ролей | `src/web/auth.py` |
| Хранилище пользователей (`sessions/users.json`) | `src/web/users.py` |
| Журнал аудита (`logs/audit.jsonl`) | `src/web/audit.py` |
| Управление пользователями из консоли | `scripts/manage_users.py` |

---
[← Карта](README.md) · [Дальше: Серверы и сервисы →](02-servers.md)
