# FinikTeam-FB01 — ИИ-помощник нового клиента Faberlic

Прототип Telegram-бота для кейса **FB01**. Бот принимает первичный контакт после
события регистрации: извлекает из реплик сведения, ведёт одну постоянную карточку
клиента и готовит материалы для наставника. Ответов клиенту бот не отправляет —
только черновики с ручным подтверждением.

## Что реализовано в этом контуре

| Блок | Файлы | Что делает |
| --- | --- | --- |
| Промпт и схема карточки | `common/prompts.py` | системный промпт, `OUTPUT_SCHEMA`, запреты, определения сегментов, правила вопросов, 7 эталонных примеров |
| Извлечение карточки | `common/llm.py`, `handlers/client.py` | вызов LLM, парсинг JSON с ретраем, дописывание истории диалога |
| Валидация | `common/card.py` | проверка схемы, обязательность дословных цитат, предупреждения, человекочитаемый вид карточки |
| Хранилище | `database/models.py`, `database/repository.py` | таблица `client_card`: одна карточка и одна постоянная история на `client_id` (SQLite) |
| Режим наставника | `handlers/mentor.py`, `filters/is_mentor.py` | `/clients`, `/card F002`, `/dialog F002`, `/unknown` — доступно id из `MENTOR_USER_IDS` |
| Проверки | `scripts/run_tests.py`, `scripts/run_paraphrases.py`, `scripts/check_llm.py` | прогон учебных кейсов F001–F010 и перефразированных входов |

Разделение ролей зафиксировано так: **машина состояний задаёт вопросы, агент извлекает
сведения**. Очередь того, что ещё спросить, агент отдаёт в `missing_information`;
`clarifying_question` — только кандидат на реплику, не покрытую заготовленным вопросом
(проверки F004/F005), и пустая строка в этом поле — норма, а не дефект.

## Запуск

Требования: Python 3.12 (проверено на 3.12.10) и LLM-эндпоинт с OpenAI-совместимым API.
Локально — Ollama.

```bash
python -m venv .venv
.venv\Scripts\activate                 # Windows; на Linux — source .venv/bin/activate
pip install -r requirements.txt

ollama pull qwen2.5:7b-instruct
set OLLAMA_CONTEXT_LENGTH=8192         # промпт ≈ 5.9k токенов, меньше не помещается
ollama serve
```

```bash
copy .env.example .env                 # заполнить BOT_TOKEN, MENTOR_USER_IDS, DB_LITE
python app.py
```

В `.env` по умолчанию указан локальный Ollama (`LLM_BASE_URL=http://localhost:11434/v1`);
на внешнем провайдере нужен `LLM_API_KEY`. Порт 11434 наружу не публикуется.
`MENTOR_USER_IDS` можно не заполнять — тогда все пользователи считаются клиентами
(`app.py` печатает об этом предупреждение).

## Проверки

```bash
python scripts/check_llm.py models         # жив ли эндпоинт и какие модели есть
python scripts/check_llm.py prompt         # собранный системный промпт целиком
python scripts/check_llm.py test F002      # карточка по учебному событию
python scripts/check_llm.py test "реплика" F007   # карточка по своей реплике

python scripts/run_tests.py                # F001–F010 из data/fb01/tests.json
python scripts/run_paraphrases.py          # 21 перефразированный вход (data/fb01/paraphrases.json)
python scripts/run_tests.py F002 F006 --show   # отдельные кейсы с полным JSON
python scripts/run_paraphrases.py F009-P1 F010-P2   # отдельные перефразы
```

На Windows перед прогонами ставьте `set PYTHONIOENCODING=utf-8`, иначе кириллица в
выводе консоли портится в cp1251. `TEST_DELAY=3` задаёт паузу между запросами (в
секундах). Результат последнего прогона лежит в `_baseline_qwen25_7b_t03.txt`.

Базовый набор кейсов и перефразы проверяют только сам агент. Проверки уровня бота —
накопление карточки через FSM, остановка контакта по телефону, доступ наставника —
требуют собранного контура и в этих скриптах не проверяются; `run_tests.py` перечисляет
их отдельной строкой.

## Данные кейса

Учебные данные — в `data/fb01/` (`registration_events.json`, `dialogues.json`,
`knowledge_base.json`, `segmentation_rules.json`, `tests.json`, `paraphrases.json`,
служебка `ПОЛЯ_И_ПОРЯДОК_ПРОВЕРКИ.txt`). Ожидаемые ответы тестов намеренно не
используются в промпте и не подмешиваются в контекст модели.
