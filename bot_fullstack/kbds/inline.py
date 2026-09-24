"""Inline-клавиатуры помощника.

Имена полей и значения callback — латиница: в них лежат ключи карточки
(goal, interests, ...) и идентификаторы событий (F001), а не русские подписи,
чтобы кнопка гарантированно влезала в лимит Telegram 64 байта.
"""
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from assistant.engine import ROLE_LABELS, SEGMENTS, role_of_segment
from common.edit_fields import EDIT_FIELDS
from utils.cards import title_of

PAGE_SIZE = 5


class EditCB(CallbackData, prefix='edit'):
    key: str


class ClientCB(CallbackData, prefix='cli'):
    client_id: str


class PageCB(CallbackData, prefix='pg'):
    page: int
    role: str


class DraftCB(CallbackData, prefix='drf'):
    client_id: str


class ContactCB(CallbackData, prefix='cnt'):
    client_id: str


class FilterCB(CallbackData, prefix='flt'):
    role: str


class NavCB(CallbackData, prefix='nav'):
    target: str


class MenuCB(CallbackData, prefix='mnu'):
    action: str


def register_keyboard(url: str, *, retry: bool = False) -> InlineKeyboardMarkup:
    """Ссылка на регистрацию для того, кого ещё нет в выгрузке анкет сайта."""
    builder = InlineKeyboardBuilder()
    builder.button(text='Зарегистрироваться на сайте', url=url)
    if retry:
        builder.button(text='Я уже зарегистрирован, сверить номер',
                       callback_data=MenuCB(action='phone'))
    builder.adjust(1)
    return builder.as_markup()


def edit_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for field in EDIT_FIELDS:
        builder.button(text=field.label, callback_data=EditCB(key=field.key))
    builder.button(text='Отмена', callback_data=NavCB(target='menu'))
    builder.adjust(1)
    return builder.as_markup()


def client_label(client) -> str:
    return f'{title_of(client)} · {SEGMENTS.get(client.segment, client.segment)}'


def cards_keyboard(clients: list, page: int, pages: int, role: str = 'all') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for client in clients:
        builder.button(text=client_label(client), callback_data=ClientCB(client_id=client.client_id))
    rows = builder.export()
    rows.extend(filter_rows(role))
    rows.extend(nav_rows(page, pages, role))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def filter_rows(role: str) -> list:
    """Фильтр по роли: кто человек — клиент или партнёр по бизнесу."""
    builder = InlineKeyboardBuilder()
    for key, label in ROLE_LABELS.items():
        text = f'▪ {label}' if key == role else label
        builder.button(text=text, callback_data=FilterCB(role=key))
    builder.adjust(2)
    return builder.export()


def nav_rows(page: int, pages: int, role: str = 'all') -> list:
    builder = InlineKeyboardBuilder()
    if page > 1:
        builder.button(text='← раньше', callback_data=PageCB(page=page - 1, role=role))
    builder.button(text=f'{page} / {pages}', callback_data=PageCB(page=page, role=role))
    if page < pages:
        builder.button(text='позже →', callback_data=PageCB(page=page + 1, role=role))
    return builder.export()


def contact_label(client) -> str:
    """Подпись кнопки связи; пустая строка — кнопки не будет (согласия нет)."""
    if client.do_not_contact:
        return ''
    role = role_of_segment(client.segment)
    if role == 'client':
        return 'Связаться с клиентом'
    if role == 'partner':
        return 'Связаться с партнёром по бизнесу'
    return 'Связаться'


def card_keyboard(client) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='Показать черновик наставнику', callback_data=DraftCB(client_id=client.client_id))
    label = contact_label(client)
    if label:
        # Кнопки связи нет, пока человек не согласился на общение (KB06).
        builder.button(text=label, callback_data=ContactCB(client_id=client.client_id))
    builder.button(text='← к списку', callback_data=NavCB(target='list'))
    builder.adjust(1)
    return builder.as_markup()
