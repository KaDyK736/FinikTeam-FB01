import os

from aiogram import types
from aiogram.filters import Filter


def mentor_ids() -> set[int]:
    raw = os.getenv("MENTOR_USER_IDS", "")
    parts = raw.replace(";", ",").split(",")
    return {int(part.strip()) for part in parts if part.strip().lstrip("-").isdigit()}


class MentorFilter(Filter):
    """Пускает в роутер наставника только тех, чей telegram id прописан в MENTOR_USER_IDS."""

    async def __call__(self, event: types.TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user) and user.id in mentor_ids()
