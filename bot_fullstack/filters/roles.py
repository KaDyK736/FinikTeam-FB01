"""Фильтры доступа: наставник и администратор учебного стенда."""
import os

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from database.models import Mentor


def _tg_id(event) -> int | None:
    if isinstance(event, (Message, CallbackQuery)) and event.from_user is not None:
        return event.from_user.id
    return None


def _ids_from_env(name: str) -> set[int]:
    raw = os.getenv(name, '')
    return {int(item) for item in raw.replace(' ', '').split(',') if item.strip().isdigit()}


class IsMentor(BaseFilter):
    """Доступ к карточкам даёт только номер наставника из таблицы mentor.

    Право проверяется по базе, а не по идентификатору чата: telegram_id
    появляется в записи после того, как человек прислал свой номер.
    """
    async def __call__(self, event, db_mentor: Mentor | None = None) -> bool:
        return db_mentor is not None


class IsAdmin(BaseFilter):
    async def __call__(self, event) -> bool:
        tg_id = _tg_id(event)
        return tg_id is not None and tg_id in _ids_from_env('ADMIN_TG_ID')
