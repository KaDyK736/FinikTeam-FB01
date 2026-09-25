"""Рабочее место наставника: список карточек, фильтр по роли и связь с человеком.

Автоматической переписки от лица наставника нет: черновик наставник читает и
решает сам (segmentation_rules.json, правило 5). Кнопка «связаться» — не текст
наставника, а служебное уведомление помощника о том, что наставник готов помочь;
оно ставит статус в карточку и приходит человеку, если тот согласился (KB06).
"""
import datetime
import math

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from assistant import engine
from database.repository import orm_get_client, orm_list_clients, orm_offer_contact
from filters.roles import IsMentor
from kbds.inline import (
    ClientCB, ContactCB, DraftCB, FilterCB, NavCB, PageCB, card_keyboard, cards_keyboard,
)
from utils.cards import card_of, draft_text, mentor_card_text

mentor_router = Router(name='mentor')
mentor_router.message.filter(IsMentor())
mentor_router.callback_query.filter(IsMentor())

PAGE_SIZE = 5


def now() -> str:
    return datetime.datetime.now().strftime('%d.%m.%Y %H:%M')


async def show_list(session: AsyncSession, message: Message, page: int, role: str = 'all'):
    segments = engine.ROLE_SEGMENTS.get(role) or None
    clients = await orm_list_clients(session, segments=segments, limit=500)
    pages = max(1, math.ceil(len(clients) / PAGE_SIZE))
    page = min(max(page, 1), pages)
    start = (page - 1) * PAGE_SIZE
    chunk = clients[start:start + PAGE_SIZE]
    title = engine.ROLE_LABELS.get(role, engine.ROLE_LABELS['all'])
    await message.answer(
        f'<b>Карточки новых клиентов</b> — фильтр «{title}», всего {len(clients)}, '
        f'страница {page} из {pages}.\nНомера телефонов скрыты.',
        reply_markup=cards_keyboard(chunk, page, pages, role),
    )


@mentor_router.message(Command('cards'))
async def cmd_cards(message: Message, session: AsyncSession, command: CommandObject):
    role = engine.normalize_role(command.args)
    await show_list(session, message, 1, role)


@mentor_router.message(Command('card'))
async def cmd_card(message: Message, session: AsyncSession, command: CommandObject):
    client = await orm_get_client(session, (command.args or '').strip().upper())
    if client is None:
        await message.answer('Карточка с таким идентификатором не найдена.')
        return
    await message.answer(mentor_card_text(client), reply_markup=card_keyboard(client))


@mentor_router.callback_query(ClientCB.filter())
async def cb_card(call: CallbackQuery, session: AsyncSession, callback_data: ClientCB):
    client = await orm_get_client(session, callback_data.client_id)
    if client is None:
        await call.answer('Карточка пропала', show_alert=True)
        return
    await call.message.edit_text(mentor_card_text(client), reply_markup=card_keyboard(client))
    await call.answer()


@mentor_router.callback_query(DraftCB.filter())
async def cb_draft(call: CallbackQuery, session: AsyncSession, callback_data: DraftCB):
    client = await orm_get_client(session, callback_data.client_id)
    if client is None:
        await call.answer('Карточка пропала', show_alert=True)
        return
    await call.message.answer(draft_text(client))
    await call.answer('Черновик показан — отправка только руками')


@mentor_router.callback_query(ContactCB.filter())
async def cb_contact(
    call: CallbackQuery, session: AsyncSession, callback_data: ContactCB, db_mentor,
):
    client = await orm_get_client(session, callback_data.client_id)
    if client is None:
        await call.answer('Карточка пропала', show_alert=True)
        return
    if client.do_not_contact or db_mentor is None:
        await call.answer('Человек попросил не писать ему — связи нет (KB06)', show_alert=True)
        return
    await orm_offer_contact(session, client, db_mentor, now())
    delivered = await _notify_client(call, client, db_mentor.name)
    await call.message.edit_text(mentor_card_text(client), reply_markup=card_keyboard(client))
    await call.answer(
        'Готов помочь: человеку отправлено уведомление' if delivered
        else 'Статус в карточке обновлён — его чат боту ещё не известен'
    )


@mentor_router.callback_query(FilterCB.filter())
async def cb_filter(call: CallbackQuery, session: AsyncSession, callback_data: FilterCB):
    await show_list(session, call.message, 1, callback_data.role)
    await call.answer()


@mentor_router.callback_query(PageCB.filter())
async def cb_page(call: CallbackQuery, session: AsyncSession, callback_data: PageCB):
    await show_list(session, call.message, callback_data.page, callback_data.role)
    await call.answer()


@mentor_router.callback_query(NavCB.filter())
async def cb_nav(call: CallbackQuery, session: AsyncSession, callback_data: NavCB):
    if callback_data.target == 'list':
        await show_list(session, call.message, 1)
    await call.answer()


async def _notify_client(call: CallbackQuery, client, mentor_name: str) -> bool:
    """Уведомление человеку. Без привязанного чата отправлять некуда — остаётся статус."""
    if not client.telegram_id:
        return False
    text = engine.mentor_ready_text(card_of(client), mentor_name)
    try:
        await call.message.bot.send_message(client.telegram_id, text)
    except TelegramAPIError:
        # Человек заблокировал бота или чат недоступен: статус в карточке сохраняется.
        return False
    return True
