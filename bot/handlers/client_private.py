"""Диалог с новым клиентом: сверка телефона, вопросы первичной анкеты и
правка параметров, которых нет на форме сайта.

Хендлеры тонкие: разбор реплики, сегмент и следующий шаг считает движок
assistant/engine.py, сохранение — database/repository.py.
"""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from assistant import answers, engine
from common.edit_fields import BY_KEY, validate
from common.menus import STOP_TEXT, ask_next, show_menu
from database.repository import (
    orm_add_turn, orm_edit_field, orm_get_mentor_by_phone, orm_link_client_id,
    orm_link_phone, orm_save_answer, orm_update, profile_of,
)
from database.site_export import register_url
from kbds.inline import EditCB, MenuCB, NavCB, edit_keyboard, register_keyboard
from kbds.reply import BUSINESS_MENU, MENU, client_menu, contact_keyboard, hide_keyboard, start_keyboard
from states.dialogue import Dialogue, Editing, Question, step_of
from utils.cards import client_card_text, draft_text
from utils.validators import mask_phone, normalize_phone

client_router = Router(name='client')

WELCOME = (
    'Здравствуйте! Я помощник нового клиента: помогу определиться с целью '
    'и передам вопросы наставнику.\n\n'
    'Нажмите «Начнем» — сверю ваш номер с анкетами, которые приходят с сайта. '
    'Анкеты ещё нет? Предложу ссылку на регистрацию.'
)
GREETING = (
    'Сверю ваш номер с базой анкет с сайта — пришлите его кнопкой или текстом. '
    'Если знаете идентификатор события регистрации (например F002), напишите его. '
    'Карточку заводит сайт: если номера нет в его выгрузке, диалог не начнётся.'
)
BAD_PHONE = (
    'Не смог распознать номер. Напишите +79990000004 или 8 999 000-00-04, '
    'либо пришлите кнопкой. Идентификатор события (F002) тоже подойдёт.'
)
PHONE_NOT_FOUND = (
    'Номера {phone} среди анкет, которые приходят с сайта, нет — карточку не завожу. '
    'Пришлите номер, который указывали при регистрации, или идентификатор события '
    'регистрации (например F002).'
)
MENTOR_ACCESS = 'Список карточек — /cards, одна карточка — /card F002.'
MENTOR_GREETING = (
    'Ваш номер значится в списке наставников, поэтому карточку клиента я не завожу. '
    + MENTOR_ACCESS
)
ANSWER_STATES = StateFilter(
    Dialogue.goal, Dialogue.clarify, Dialogue.interests,
    Dialogue.available_time, Dialogue.experience,
)


@client_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(WELCOME, reply_markup=start_keyboard())


@client_router.message(F.text == MENU['start'])
async def press_start(message: Message, state: FSMContext, db_client, db_mentor):
    """Кнопка «Начнем» на экране входа делает то же, что /start, но по-русски."""
    await state.clear()
    if db_client is not None:
        await show_menu(message, db_client)
        return
    if db_mentor is not None:
        await message.answer(MENTOR_GREETING, reply_markup=hide_keyboard())
        return
    await ask_phone(message, state)


@client_router.message(Command('cancel'))
async def cmd_cancel(message: Message, state: FSMContext, db_client):
    was = await state.get_state() is not None
    await state.clear()  # откат к предыдущему значению не отменяем: история карточки сохраняется
    if db_client is not None:
        await show_menu(message, db_client, prefix='Отменил последний шаг.' if was else None)
    else:
        await message.answer('Отменил. Начать заново — /start', reply_markup=hide_keyboard())


@client_router.message(F.text == MENU['phone'], StateFilter(None))
async def ask_phone(message: Message, state: FSMContext):
    await state.set_state(Dialogue.phone)
    await message.answer(GREETING, reply_markup=contact_keyboard())


@client_router.message(Dialogue.phone, F.contact)
async def phone_from_contact(message: Message, state: FSMContext, session: AsyncSession):
    await after_phone(message, state, session, message.contact.phone_number)


@client_router.message(Dialogue.phone, F.text)
async def phone_from_text(message: Message, state: FSMContext, session: AsyncSession):
    await after_phone(message, state, session, message.text)


async def after_phone(message, state, session, raw):
    text = (raw or '').strip()
    client, status = await orm_link_phone(session, message.from_user.id, text)

    if status == 'bad-phone':
        linked, linked_status = await orm_link_client_id(session, message.from_user.id, text)
        if linked_status == 'found':
            await show_found(message, state, session, linked, 'by-id')
            return
        if engine.mentions_registration(text):
            await offer_registration(message, state)
            return
        if engine.is_farewell(text):
            await state.clear()
            await message.answer(engine.FAREWELL_REPLY, reply_markup=hide_keyboard())
            return
        await state.set_state(Dialogue.phone)
        await message.answer(BAD_PHONE, reply_markup=contact_keyboard())
        return

    if status == 'conflict':
        await state.clear()
        await message.answer(
            'Этот номер уже привязан к другому чату — вторую карточку не завожу, '
            'чтобы данные не смешались.', reply_markup=hide_keyboard(),
        )
        return

    if status == 'mentor':
        mentor = await orm_get_mentor_by_phone(session, text)
        await state.clear()
        name = mentor.name if mentor is not None else 'наставник'
        await message.answer(
            f'Привет, {name}. Ваш номер значится в списке наставников, поэтому '
            f'карточку клиента я не завожу. {MENTOR_ACCESS}',
            reply_markup=hide_keyboard(),
        )
        return

    if status == 'not-found':
        await offer_registration(message, state, mask_phone(normalize_phone(text)))
        return

    await show_found(message, state, session, client, status)


async def offer_registration(message: Message, state: FSMContext, phone: str = '') -> None:
    """Человека нет в выгрузке сайта: карточку не заводим — предлагаем регистрацию."""
    await state.set_state(Dialogue.phone)
    if phone:
        await message.answer(
            PHONE_NOT_FOUND.format(phone=phone), reply_markup=contact_keyboard(),
        )
    await message.answer(
        engine.REGISTRATION_OFFER.format(url=register_url()),
        reply_markup=register_keyboard(register_url(), retry=True),
    )


async def show_found(message, state, session, client, status):
    profile = profile_of(client)
    if status == 'by-id':
        note = f'Нашёл карточку {client.client_id} по идентификатору события регистрации.'
    else:
        note = (f'Карточка {client.client_id} найдена в базе по номеру '
                f'{mask_phone(client.site_phone)}, новую не завожу.')
    await message.answer(note)
    await ask_next(message, state, profile, previous=profile)
    await orm_update(session, client, dialogue_step=profile.get('dialogue_step'))


@client_router.message(F.text == MENU['dialog'])
async def continue_dialog(message: Message, state: FSMContext, session: AsyncSession, db_client):
    """«Начать диалог»: только следующий вопрос, а для завершённого — итог."""
    if db_client is None:
        await ask_phone(message, state)
        return
    profile = profile_of(db_client)
    profile = await ask_next(message, state, profile, previous=profile)
    await orm_update(session, db_client, dialogue_step=profile.get('dialogue_step'))


@client_router.message(F.text.in_(tuple(BUSINESS_MENU)), StateFilter(None))
async def choose_business_goal(message: Message, state: FSMContext, session: AsyncSession, db_client):
    """Бизнес-кнопки отдельным блоком: названы человеком, а движок получает цель."""
    if db_client is None:
        await ask_phone(message, state)
        return
    phrase = engine.BUSINESS_GOALS[BUSINESS_MENU[message.text]]
    before = profile_of(db_client)
    profile = await orm_save_answer(session, db_client, phrase, 'goal')
    await message.answer(
        f'Цель записана: {engine.SEGMENTS.get(profile["segment"], profile["segment"])}.\n'
        'Роль в карточке: '
        f'{engine.ROLE_LABELS[engine.role_of_segment(profile["segment"])]}.',
    )
    await ask_next(message, state, profile, previous=before)
    await orm_update(session, db_client, dialogue_step=profile.get('dialogue_step'))


@client_router.callback_query(MenuCB.filter())
async def menu_callback(call: CallbackQuery, state: FSMContext, db_client):
    """Кнопка после ссылки на регистрацию: человек вернулся и готов сверить номер."""
    if call.data and MenuCB.unpack(call.data).action == 'phone':
        await state.clear()
        await call.message.answer(GREETING, reply_markup=contact_keyboard())
    await call.answer()


@client_router.message(F.text == MENU['card'])
async def show_card(message: Message, db_client):
    if db_client is None:
        await message.answer('Сначала сверим номер: /start', reply_markup=hide_keyboard())
        return
    await message.answer(client_card_text(db_client), reply_markup=client_menu())


@client_router.message(F.text == MENU['edit'])
async def start_edit(message: Message, db_client):
    if db_client is None:
        await message.answer('Сначала сверим номер: /start', reply_markup=hide_keyboard())
        return
    await message.answer(
        'Что меняем? Эти параметры не заполняются на форме сайта — они из диалога. '
        'Из анкеты сайта в карточке остаются только номер телефона и согласие: '
        'их меняет сайт.',
        reply_markup=edit_keyboard(),
    )


@client_router.message(F.text == MENU['questions'])
async def start_question(message: Message, state: FSMContext, db_client):
    if db_client is None:
        await message.answer('Сначала сверим номер: /start', reply_markup=hide_keyboard())
        return
    await state.set_state(Question.text)
    await message.answer('Напишите вопрос своими словами. Регистрацию, оплату и операции '
                         'с кабинетом я не выполняю — подготовлю черновик для наставника.')


@client_router.message(Question.text, F.text)
async def save_question(message: Message, state: FSMContext, session: AsyncSession, db_client):
    """Вопрос из меню: отвечаем по базе знаний, чего в базе нет — наставнику."""
    await state.clear()
    if engine.analyse(message.text).refusal:
        # Отказ важнее вопроса (KB06): останавливаем диалог по-настоящему,
        # а не только словами.
        await orm_save_answer(session, db_client, message.text, 'goal')
        await message.answer(STOP_TEXT, reply_markup=hide_keyboard())
        return
    result = await answers.answer_for(message.text)
    if result.from_knowledge_base:
        await orm_add_turn(session, db_client, 'user', message.text.strip()[:200], step='question')
        await message.answer(result.text, reply_markup=client_menu())
        return
    await orm_update(session, db_client, open_question=message.text.strip()[:500])
    await message.answer(result.text)
    await message.answer(draft_text(db_client), reply_markup=client_menu())


@client_router.callback_query(EditCB.filter())
async def choose_field(call: CallbackQuery, state: FSMContext, db_client):
    if db_client is None:
        await call.answer('Сначала /start', show_alert=True)
        return
    field = BY_KEY.get(EditCB.unpack(call.data).key)
    if field is None:
        await call.answer('Такого параметра нет', show_alert=True)
        return
    await state.set_state(Editing.value)
    await state.update_data(key=field.key)
    await call.message.answer(field.question)
    await call.answer()


@client_router.callback_query(NavCB.filter())
async def nav_back(call: CallbackQuery, state: FSMContext, db_client):
    await state.clear()
    if db_client is not None:
        await show_menu(call.message, db_client)
    await call.answer()


@client_router.message(Editing.value, F.text)
async def apply_edit_value(message: Message, state: FSMContext, session: AsyncSession, db_client):
    key = (await state.get_data()).get('key')
    field = BY_KEY.get(key)
    if db_client is None or field is None:
        await state.clear()
        await message.answer('Нечего менять: сначала /start.', reply_markup=hide_keyboard())
        return
    value = validate(key, message.text)
    if value is None:
        hint = ('Выберите один из вариантов: ' + ' / '.join(field.choices)
                if field.choices else 'Напишите ответ подробнее — двумя словами минимум.')
        await message.answer(f'{field.question}\n{hint}')
        return
    profile = await orm_edit_field(session, db_client, key, value)
    await state.clear()
    await message.answer(
        f'Изменил: {field.label}.\n'
        f'Сегмент теперь: {engine.SEGMENTS.get(profile["segment"], profile["segment"])}.\n'
        f'Следующий шаг: {engine.next_action(profile)}.\n'
        'Прежнее значение осталось в истории карточки.',
    )
    await message.answer(client_card_text(db_client), reply_markup=client_menu())


@client_router.message(ANSWER_STATES, F.text)
async def answer_question(message: Message, state: FSMContext, session: AsyncSession, db_client):
    step = step_of(await state.get_state()) or 'goal'
    await state.clear()
    if engine.is_farewell(message.text):
        await close_dialogue(message, session, db_client)
        return
    before = profile_of(db_client)
    profile = await orm_save_answer(session, db_client, message.text, step)
    await ask_next(message, state, profile, previous=before)
    await orm_update(session, db_client, dialogue_step=profile.get('dialogue_step'))


@client_router.message(StateFilter(None), F.text)
async def unexpected_text(message: Message, state: FSMContext, session: AsyncSession, db_client):
    """Свободный текст вне вопроса.

    Если в реплике есть сведения о цели, интересах или флаге — она идёт в
    карточку (KB01/KB07). Нечего сказать о карточке — считаем это вопросом:
    отвечаем по базе знаний либо передаём наставнику с подсказкой про меню.
    """
    if db_client is None:
        # Человек без карточки мог написать номер сразу, не дожидаясь вопроса.
        await state.set_state(Dialogue.phone)
        await after_phone(message, state, session, message.text)
        return
    if not message.text.strip():
        await message.answer('Напишите пару слов.', reply_markup=client_menu())
        return
    if engine.is_farewell(message.text):
        await close_dialogue(message, session, db_client)
        return
    analysis = engine.analyse(message.text)
    if not (analysis.matched or analysis.refusal):
        # Ни цели, ни интереса, ни флага, ни отказа: это вопрос, а не сведения в карточку.
        result = await answers.answer_for(message.text)
        if not result.from_knowledge_base:
            await orm_update(session, db_client, open_question=message.text.strip()[:500])
        await message.answer(result.text, reply_markup=client_menu())
        return
    before = profile_of(db_client)
    profile = await orm_save_answer(session, db_client, message.text, 'goal')
    await show_menu(message, db_client, prefix='Записал в карточку.')
    await ask_next(message, state, profile, previous=before)
    await orm_update(session, db_client, dialogue_step=profile.get('dialogue_step'))


async def close_dialogue(message: Message, session: AsyncSession, client) -> None:
    """Вежливое прощание: реплику не пишем в цель, но сохраняем в историю."""
    if client is None:
        await message.answer(engine.FAREWELL_REPLY, reply_markup=hide_keyboard())
        return
    await orm_add_turn(session, client, 'user', message.text.strip()[:200], step='farewell')
    await orm_update(session, client, dialogue_step='closed')
    await message.answer(engine.FAREWELL_REPLY, reply_markup=client_menu())
