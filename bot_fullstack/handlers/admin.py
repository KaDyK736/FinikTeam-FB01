"""Админка учебного стенда: загрузка событий регистрации и разбор кривого входа.

Здесь живут проверки FB01-F011 (пустой объект без client_id) и FB01-F012
(повторная загрузка события не создаёт вторую карточку).
"""
import json

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from assistant import engine
from database.engine import load_events
from database.repository import INVALID, orm_apply_event, orm_count_clients, orm_list_clients
from filters.roles import IsAdmin
from states.dialogue import AdminOps
from utils.cards import mentor_card_text

admin_router = Router(name='admin')
admin_router.message.filter(IsAdmin())


@admin_router.message(Command('load'))
async def cmd_load(message: Message, session: AsyncSession):
    counters = await load_events(session)
    await message.answer(
        'События регистрации из файла кейса: '
        f"создано {counters['created']}, обновлено {counters['updated']}, "
        f"отклонено {counters['invalid']}.\n"
        'Повторная загрузка обновляет карточки по client_id — дублей не появляется.'
    )


@admin_router.message(Command('event'))
async def cmd_event(message: Message, state: FSMContext, session: AsyncSession, command: CommandObject):
    if not (command.args or '').strip():
        await state.set_state(AdminOps.event_json)
        await message.answer('Пришлите событие регистрации JSON-ом, например '
                             '{"client_id": "F001", "initial_message": "..."}')
        return
    await apply_raw_event(message, session, command.args)


@admin_router.message(AdminOps.event_json)
async def event_from_state(message: Message, state: FSMContext, session: AsyncSession):
    await state.clear()
    await apply_raw_event(message, session, message.text)


async def apply_raw_event(message: Message, session: AsyncSession, raw: str):
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        await message.answer('Это не JSON: карточку не трогал.')
        return
    await report_event(message, session, event)


async def report_event(message: Message, session: AsyncSession, event):
    client, status, note = await orm_apply_event(session, event)
    if status == INVALID:
        await message.answer(
            f'Вход некорректен: {note} Существующие карточки не изменены, '
            'данные не перенесены в чужую анкету.'
        )
        return
    await message.answer(f'Событие обработано: {status} карточка {client.client_id}.')
    await message.answer(mentor_card_text(client))


@admin_router.message(Command('stats'))
async def cmd_stats(message: Message, session: AsyncSession):
    clients = await orm_list_clients(session, limit=500)
    total = await orm_count_clients(session)
    lines = [f'Карточек в базе: {total}']
    for key, label in engine.SEGMENTS.items():
        lines.append(f'{label}: {sum(1 for c in clients if c.segment == key)}')
    lines.append(f'Просят не писать: {sum(1 for c in clients if c.do_not_contact)}')
    await message.answer('\n'.join(lines))
