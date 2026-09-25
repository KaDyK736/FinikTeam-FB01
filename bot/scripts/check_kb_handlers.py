"""Локальный прогон хендлеров свободного текста: ответы по базе и откат к меню.

Тестирует не движок, а обвязку handlers/client_private.py — те же функции,
которые вызывает Telegram. База отдельная (kb_handlers.db), рабочая fb01_bot.db
не трогается. Кнопки и меню здесь только проверяются, но не меняются.

Запуск из bot/:  python scripts/check_kb_handlers.py
"""
import asyncio
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DB_URL'] = f'sqlite+aiosqlite:///{(ROOT / "kb_handlers.db").as_posix()}'
os.environ.setdefault('MENTOR_PHONE', '+79990000099')

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv(ROOT / '.env')

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from assistant import answers  # noqa: E402
from database.engine import close_db, init_db, session_maker  # noqa: E402
from database.repository import orm_get_client  # noqa: E402
from handlers.client_private import save_question, unexpected_text  # noqa: E402


class FakeUser:
    id = 5000000002


class FakeMessage:
    """То, что реально нужно хендлеру: текст, автор и запись ответов."""

    def __init__(self, text: str, chat_id: int = 1):
        self.text = text
        self.chat = type('Chat', (), {'id': chat_id})()
        self.from_user = FakeUser()
        self.reply_markup = None
        self.answers: list[str] = []

    async def answer(self, text: str, reply_markup=None):
        self.answers.append(text)
        self.reply_markup = reply_markup or self.reply_markup


def make_state(chat_id: int) -> FSMContext:
    key = StorageKey(bot_id=1, chat_id=chat_id, user_id=chat_id)
    return FSMContext(MemoryStorage(), key)


def buttons(markup) -> list[str]:
    if markup is None:
        return []
    return [btn.text for row in markup.keyboard for btn in row]


async def run_case(session, client, text: str, state_machine=None) -> None:
    message = FakeMessage(text)
    state = state_machine or make_state(1)
    if state_machine is None:
        await save_question(message, state, session, client)
    else:
        await unexpected_text(message, state, session, client)
    answered = not message.answers[0].startswith(answers.OUT_OF_KB[:40])
    print(f'\n{text!r}')
    print(f'  ответ по базе знаний: {"да" if answered else "нет — вопрос наставнику"}')
    print(f'  кнопки после ответа: {buttons(message.reply_markup) or "без клавиатуры"}')
    for line in ' '.join(message.answers).splitlines():
        print(f'  | {line[:110]}')


async def main() -> None:
    await init_db()
    print(f'USE_LLM = {os.getenv("USE_LLM")} | MODEL = {os.getenv("LLM_MODEL")}')
    async with session_maker() as session:
        client = await orm_get_client(session, 'F002')
        assert client is not None, 'карточка F002 не загружена'

        print('\n=== кнопка «Вопрос наставнику» (состояние Question.text) ===')
        for text in ('как правильно ухаживать за кожей лица?', 'сколько реально можно получать за месяц?',
                     'расскажи про луну'):
            await run_case(session, client, text)

        print('\n=== свободный текст вне вопроса (StateFilter(None)) ===')
        free_state = make_state(2)
        for text in ('привет, как дела?', 'а можно оформить заказ за меня?'):
            await run_case(session, client, text, state_machine=free_state)
            await free_state.clear()

    await close_db()
    print('\n(проверка ответов по базе: assistant/answers.py; база — kb_handlers.db)')


asyncio.run(main())
