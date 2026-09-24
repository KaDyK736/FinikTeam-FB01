"""Inline-клавиатуры помощника.

Имена полей и значения callback — латиница: в них лежат ключи карточки
(goal, interests, ...) и идентификаторы событий (F001), а не русские подписи,
чтобы кнопка гарантированно влезала в лимит Telegram 64 байта.
"""
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from assistant.engine import SEGMENTS
from common.edit_fields import EDIT_FIELDS

PAGE_SIZE = 5


class EditCB(CallbackData, prefix='edit'):
    key: str


class ClientCB(CallbackData, prefix='cli'):
    client_id: str


class PageCB(CallbackData, prefix='pg'):
    page: int


class DraftCB(CallbackData, prefix='drf'):
    client_id: str


class NavCB(CallbackData, prefix='nav'):
    target: str


def edit_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for field in EDIT_FIELDS:
        builder.button(text=field.label, callback_data=EditCB(key=field.key))
    builder.button(text='Отмена', callback_data=NavCB(target='menu'))
    builder.adjust(1)
    return builder.as_markup()


def client_label(client) -> str:
    return f'{client.client_id} · {SEGMENTS.get(client.segment, client.segment)}'


def cards_keyboard(clients: list, page: int, pages: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for client in clients:
        builder.button(text=client_label(client), callback_data=ClientCB(client_id=client.client_id))
    rows = builder.export()
    rows.extend(nav_rows(page, pages))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def nav_rows(page: int, pages: int) -> list:
    builder = InlineKeyboardBuilder()
    if page > 1:
        builder.button(text='← раньше', callback_data=PageCB(page=page - 1))
    builder.button(text=f'{page} / {pages}', callback_data=PageCB(page=page))
    if page < pages:
        builder.button(text='позже →', callback_data=PageCB(page=page + 1))
    return builder.export()


def card_keyboard(client_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='Показать черновик наставнику', callback_data=DraftCB(client_id=client_id))
    builder.button(text='← к списку', callback_data=NavCB(target='list'))
    builder.adjust(1)
    return builder.as_markup()
