# C4 Architecture — Faberlic AI Assistant (FB01)

Диаграммы в Mermaid (рендерятся на GitHub/GitVerse встроенно). PNG-экспорт можно получить через `mermaid-cli` в папку `docs/generated/`.

## 1. Level 1 — System Context

```mermaid
C4Context
    title Контекст системы: ИИ-помощник нового клиента Faberlic

    Person(client, "Новый клиент", "Проходит первичный диалог, отвечает свободным текстом")
    Person(mentor, "Наставник", "Получает заполненную карточку, подтверждает следующий шаг")

    System(assistant, "Faberlic AI Assistant", "Бот + LLM-извлечение + правила сегментации + БД карточек")

    System_Ext(llm, "LLM-провайдеры", "OpenRouter (free) / Mistral AI / Ollama локально")
    System_Ext(messenger, "Мессенджер", "Telegram (демо); MAX — целевой по пожеланию держателя")
    System_Ext(reg, "Сайт регистрации (заглушка)", "Учебные события из registration_events.json")

    Rel(client, assistant, "Ведёт диалог через")
    Rel(mentor, assistant, "Сверяется по номеру телефона, читает карточки")
    Rel(assistant, llm, "Отправляет ответ на извлечение структуры")
    Rel(assistant, messenger, "Приём/отправка сообщений")
    Rel(reg, assistant, "Загрузка события регистрации с client_id")
```

Границы: система не выполняет реальные регистрации, платежи и рассылки; все сообщения наставника — черновики с ручным подтверждением (`requires_human_approval = true`).

## 2. Level 2 — Containers

```mermaid
C4Container
    title Контейнеры системы

    Person(client, "Новый клиент / Наставник")
    Person(devops, "Команда (прогон тестов)")

    System_Boundary(app, "Faberlic AI Assistant (docker compose)") {
        Container(bot, "Telegram Bot (aiogram 3)", "Python", "FSM диалога, сверка телефона наставника, черновики")
        Container(ml, "ML-сервис извлечения", "Python + LLM API", "Промпт ≥300 строк, JSON-карточка, проверка полноты")
        Container(rules, "Движок правил", "Python", "segmentation_rules.json, knowledge_base.json, KB01–KB08")
        ContainerDb(db, "Локальная БД (SQLite)", "SQLite", "clients, mentors, cards, dialogue_history")
        Container(ingest, "Загрузчик событий", "Python", "registration_events.json → карточки без дублей")
        Container(tests, "Test-runner", "pytest + Docker", "Прогон tests.json, unit-тесты, таблица результатов")
    }

    System_Ext(llm, "LLM-провайдеры", "OpenRouter / Mistral / Ollama")

    Rel(client, bot, "Сообщения через мессенджер")
    Rel(bot, ml, "Унифицированный ответ", "HTTP/локальный вызов")
    Rel(ml, llm, "Запрос извлечения")
    Rel(bot, rules, "Сегмент и следующий шаг")
    Rel(bot, db, "Карточка, история, do_not_contact")
    Rel(ingest, db, "Создание/обновление карточки по client_id")
    Rel(tests, db, "Сверка результатов с tests.json")
```

## 3. Level 3 — Components (Telegram Bot + ML-сервис)

```mermaid
C4Component
    title Компоненты backend-контейнеров

    Container_Boundary(botb, "Telegram Bot (aiogram 3)") {
        Component(handlers, "Handlers", "Роутеры команд и сообщений")
        Component(fsm, "FSM-машина состояний", "Цель → интересы → время → резюме")
        Component(auth, "MentorAuth middleware", "Сверка phone с таблицей наставников")
        Component(draft, "Draft Composer", "Черновик сообщения наставнику, evidence")
    }

    Container_Boundary(mlb, "ML-сервис извлечения") {
        Component(norm, "Input Normalizer", "Унификация текста перед LLM")
        Component(prompt, "Prompt Builder (≥300 строк)", "Схема полей JSON: цель, интересы, время")
        Component(router, "LLM Provider Router", "OpenRouter → Mistral → Ollama, ретраи")
        Component(valid, "Schema Validator", "Проверка полноты; ответ «неполный» → уточнение")
    }

    ComponentDb(db, "SQLite", "clients / mentors / cards / history")

    Rel(handlers, fsm, "Текущее состояние диалога")
    Rel(fsm, norm, "Ответ клиента")
    Rel(norm, prompt, "Контекст вопроса")
    Rel(prompt, router, "Запрос к LLM")
    Rel(router, valid, "Сырой JSON")
    Rel(valid, db, "Валидные поля карточки")
    Rel(valid, fsm, "Признак неполноты → повторный вопрос")
    Rel(auth, db, "Проверка роли наставника")
    Rel(draft, db, "Чтение карточки для наставника")
```

## 4. Ключевые потоки

**Первичный диалог (F002):** загрузка события → FSM задаёт вопрос → ответ «Ищу дополнительный доход…» → нормализация → LLM-извлечение → валидация → сегмент `income` + цитата → `next_action` «вводная беседа с наставником» → карточка в БД.

**Доступ наставника:** входящее сообщение → сверка телефона с `mentors` → выдача карточки клиента (список `client_id`, полные поля, история) → любой ответ клиенту остаётся черновиком.

**Отказ (F006):** «Не пишите мне больше» → `do_not_contact = true` → диалог остановлен, следующий шаг не предлагается, повторная загрузка события отказ не снимает.
