"""Проверка кнопки «Начать диалог»: один шаг за нажатие, без повторов.

Два сценария на живых хендлерах:
  A. карточка, где диалог уже пройден и есть флаги, — кнопка обязана отдать
     только итог «для первичного диалога достаточно»;
  B. новая карточка — вопросы идут по одному, друг за другом.
База отдельная (dialog_button.db), рабочая fb01_bot.db не трогается.

Запуск из bot/:  python scripts/check_dialog_button.py
"""
import asyncio
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DB_URL'] = f'sqlite+aiosqlite:///{(ROOT / "dialog_button.db").as_posix()}'
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
from database.repository import orm_get_client, orm_update  # noqa: E402
from handlers.client_private import answer_question, continue_dialog  # noqa: E402
from states.dialogue import step_of  # noqa: E402

CLEAN = {'segment': 'unknown', 'goals': None, 'interests': None, 'available_time': None,
         'experience': None, 'flags': None, 'goal_answer': None, 'clarify_answer': None,
         'clarify_attempted': False, 'do_not_contact': False, 'open_question': None,
         'dialogue_step': None}


class FakeUser:
    id = 5000000004


class FakeMessage:
    def __init__(self, text: str, chat_id: int = 1):
        self.text = text
        self.chat = type('Chat', (), {'id': chat_id})()
        self.from_user = FakeUser()
        self.answers: list[str] = []

    async def answer(self, text: str, reply_markup=None):
        self.answers.append(text)


def make_state(chat_id: int = 1) -> FSMContext:
    return FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=chat_id, user_id=chat_id))


async def press(session, client, state) -> FakeMessage:
    message = FakeMessage('Начать диалог')
    await continue_dialog(message, state, session, client)
    await session.commit()
    return message


async def reply(session, client, state, text: str) -> FakeMessage:
    message = FakeMessage(text)
    await answer_question(message, state, session, client)
    await session.commit()
    return message


def show(message: FakeMessage) -> None:
    for line in message.answers:
        print('   | ' + line.replace('\n', '\n   | ')[:150])


ANSWERS = {
    'goal': 'Ищу дополнительный доход, могу уделять два вечера в неделю.',
    'clarify': 'Скорее подработка.',
    'interests': 'Интересует уход за лицом и бытовая химия.',
    'available_time': 'Два вечера в неделю.',
    'experience': 'Опыта нет.',
}


async def main() -> None:
    await init_db()
    print(f'USE_LLM = {os.getenv("USE_LLM")} | MODEL = {os.getenv("LLM_MODEL")}')
    async with session_maker() as session:
        print('\n=== A. карточка с пройденным диалогом и флагами ===')
        for card_id in ('F007', 'F008', 'F010'):
            client = await orm_get_client(session, card_id)
            print(f'\n{card_id}: флаги={client.flags!r}')
            message = await press(session, client, make_state())
            print(f'  сообщений на нажатие: {len(message.answers)}')
            show(message)

        print('\n=== B. новая карточка: вопросы по одному ===')
        client = await orm_get_client(session, 'F002')
        await orm_update(session, client, **CLEAN)
        state = make_state(2)
        message = await press(session, client, state)
        for turn in range(6):
            print(f'\nшаг {turn}: состояние = {await state.get_state() or "нет"}')
            show(message)
            step = step_of(await state.get_state())
            if step is None:
                break
            message = await reply(session, client, state, ANSWERS[step])
        print('\nкарточка после диалога: цель=%r интересы=%r время=%r' % (
            client.goal_answer, client.interests, client.available_time))

        print('\n=== C. завершённая карточка с флагом: повторное нажатие ===')
        client = await orm_get_client(session, 'F008')
        state = make_state(3)
        message = await press(session, client, state)
        show(message)
        if await state.get_state():
            message = await reply(session, client, state, ANSWERS[step_of(await state.get_state())])
            show(message)
        print(f'\n  диалог завершён (шаг={client.dialogue_step}), нажимаем «Начать диалог» ещё раз:')
        message = await press(session, client, state)
        print(f'  сообщений на нажатие: {len(message.answers)}')
        show(message)
    await close_db()


asyncio.run(main())
