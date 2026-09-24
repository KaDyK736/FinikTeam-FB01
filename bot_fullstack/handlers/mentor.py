"""Рабочее место наставника: список карточек и черновик ответа.

Автоматической отправки сообщений нет ни в одном сценарии: наставник видит
текст черновика и решает сам (segmentation_rules.json, правило 5).
"""
import math

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from database.repository import orm_get_client, orm_list_clients
from filters.roles import IsMentor
from kbds.inline import ClientCB, DraftCB, NavCB, PageCB, cards_keyboard, card_keyboard
from utils.cards import draft_text, mentor_card_text

mentor_router = Router(name='mentor')
mentor_router.message.filter(IsMentor())
mentor_router.callback_query.filter(IsMentor())

PAGE_SIZE = 5


async def show_list(session: AsyncSession, message: Message, page: int, segment: str | None = None):
    clients = await orm_list_clients(session, segment=segment, limit=500)
    pages = max(1, math.ceil(len(clients) / PAGE_SIZE))
    page = min(max(page, 1), pages)
    start = (page - 1) * PAGE_SIZE
    chunk = clients[start:start + PAGE_SIZE]
    await message.answer(
        f'<b>Карточки новых клиентов</b> — {len(clients)} всего, страница {page} из {pages}.\n'
        'Номера телефонов скрыты.',
        reply_markup=cards_keyboard(chunk, page, pages),
    )


@mentor_router.message(Command('cards'))
async def cmd_cards(message: Message, session: AsyncSession, command: CommandObject):
    segment = (command.args or '').strip() or None
    await show_list(session, message, 1, segment)


@mentor_router.message(Command('card'))
async def cmd_card(message: Message, session: AsyncSession, command: CommandObject):
    client = await orm_get_client(session, (command.args or '').strip().upper())
    if client is None:
        await message.answer('Карточка с таким идентификатором не найдена.')
        return
    await message.answer(mentor_card_text(client), reply_markup=card_keyboard(client.client_id))


@mentor_router.callback_query(ClientCB.filter())
async def cb_card(call: CallbackQuery, session: AsyncSession, callback_data: ClientCB):
    client = await orm_get_client(session, callback_data.client_id)
    if client is None:
        await call.answer('Карточка пропала', show_alert=True)
        return
    await call.message.edit_text(mentor_card_text(client), reply_markup=card_keyboard(client.client_id))
    await call.answer()


@mentor_router.callback_query(DraftCB.filter())
async def cb_draft(call: CallbackQuery, session: AsyncSession, callback_data: DraftCB):
    client = await orm_get_client(session, callback_data.client_id)
    if client is None:
        await call.answer('Карточка пропала', show_alert=True)
        return
    await call.message.answer(draft_text(client))
    await call.answer('Черновик показан — отправка только руками')


@mentor_router.callback_query(PageCB.filter())
async def cb_page(call: CallbackQuery, session: AsyncSession, callback_data: PageCB):
    await show_list(session, call.message, callback_data.page)
    await call.answer()


@mentor_router.callback_query(NavCB.filter())
async def cb_nav(call: CallbackQuery, session: AsyncSession, callback_data: NavCB):
    if callback_data.target == 'list':
        await show_list(session, call.message, 1)
    await call.answer()
