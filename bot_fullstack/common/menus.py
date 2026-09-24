"""Общие шаги диалога: главное меню и «задай следующий вопрос».

Вынесено из хендлеров, чтобы один и тот же код показывал вопросы и в чате
с ботом, и в консольном интерфейсе, и в прогоне проверок.
"""
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from assistant import engine
from states.dialogue import Dialogue
from utils.cards import client_card_text

STOP_TEXT = ('Первичный диалог окончен: дальнейшие сообщения не приходят. '
             'Карточка сохранена, вопрос передам наставнику.')


async def show_menu(message: Message, client, prefix: str | None = None) -> None:
    from kbds.reply import client_menu

    text = client_card_text(client) if prefix is None else prefix
    await message.answer(text, reply_markup=client_menu(with_phone=not client.site_loaded))


async def ask_next(message: Message, state: FSMContext, profile: dict) -> dict:
    """Задаёт следующий недостающий вопрос либо подводит итог диалога.

    Возвращает профиль с проставленным dialogue_step.
    """
    if profile.get('do_not_contact'):
        await state.clear()
        await message.answer(STOP_TEXT)
        profile['dialogue_step'] = 'stopped'
        return profile

    for reply in engine.replies_for(profile):
        await message.answer(reply)

    question = engine.next_question(profile)
    if question is None:
        await message.answer(
            'Спасибо, для первичного диалога этого достаточно.\n'
            f'Что происходит дальше: {engine.next_action(profile)}.\n'
            'Сообщение наставнику — черновик, он ответит сам.',
        )
        await state.clear()
        profile['dialogue_step'] = 'done'
        return profile

    await state.set_state(getattr(Dialogue, question_key(question)))
    profile['dialogue_step'] = question_key(question)
    await message.answer(question)
    return profile


def question_key(question: str) -> str:
    return engine.question_key(question)
