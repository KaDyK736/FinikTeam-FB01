"""Проверка отказа (KB06) в живых хендлерах: «Вопрос наставнику» и свободный текст.

Отказ важнее ответа по базе: бот обязан не только сказать про остановку связи,
но и записать do_not_contact. База отдельная (kb_refusal.db), рабочая не трогается.

Запуск из bot/:  python scripts/check_kb_refusal.py
"""
import asyncio
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DB_URL'] = f'sqlite+aiosqlite:///{(ROOT / "kb_refusal.db").as_posix()}'
os.environ.setdefault('MENTOR_PHONE', '+79990000099')

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv(ROOT / '.env')

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from assistant import engine  # noqa: E402
from database.engine import close_db, init_db, session_maker  # noqa: E402
from database.repository import orm_get_client  # noqa: E402
from handlers.client_private import save_question, unexpected_text  # noqa: E402
from states.dialogue import Question  # noqa: E402

REFUSAL = 'Не пишите мне больше, пожалуйста'


class FakeUser:
    id = 5000000003


class FakeMessage:
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
    return FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=chat_id, user_id=chat_id))


async def run_case(session, client, text: str, *, in_question: bool) -> None:
    message = FakeMessage(text)
    state = make_state(1 if in_question else 2)
    if in_question:
        await state.set_state(Question.text)
        await save_question(message, state, session, client)
    else:
        await unexpected_text(message, state, session, client)
    print(f'\n=== {"кнопка «Вопрос наставнику»" if in_question else "свободный текст"} ===')
    for line in message.answers:
        print(f'  | {line[:160]}')
    print('  клавиатура:', getattr(message.reply_markup, 'keyboard', None) and
          [b.text for row in message.reply_markup.keyboard for b in row] or 'убрана')
    print('  do_not_contact =', client.do_not_contact, '| open_question =', client.open_question)


async def main() -> None:
    await init_db()
    print(f'USE_LLM = {os.getenv("USE_LLM")} | MODEL = {os.getenv("LLM_MODEL")}')
    print('правила видят отказ:', engine.analyse(REFUSAL).refusal)
    async with session_maker() as session:
        client = await orm_get_client(session, 'F003')
        assert client is not None, 'карточка F003 не загружена'
        await run_case(session, client, REFUSAL, in_question=True)
        client = await orm_get_client(session, 'F004')
        await run_case(session, client, REFUSAL, in_question=False)
    await close_db()


asyncio.run(main())
