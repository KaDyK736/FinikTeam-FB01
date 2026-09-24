from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from database.repository import orm_get_client_by_tg, orm_mentor_for


class ActorFromDB(BaseMiddleware):
    """Кладёт в data текущего клиента и наставника.

    Наставник ищется по номеру телефона: telegram_id подставляется только тот,
    что человек уже подтвердил, прислав свой номер в бота.

    Сессия берётся та же, что отдала DataBaseSession: иначе хендлер меняет
    объект из чужой сессии, и commit его не сохраняет. Свой session_pool
    остаётся запасным — для сборки диспетчера без сессионного middleware.
    """
    def __init__(self, session_pool: async_sessionmaker):
        self.session_pool = session_pool

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        data['db_client'] = None
        data['db_mentor'] = None
        from_user = data.get('event_from_user')
        if from_user is not None:
            shared: AsyncSession | None = data.get('session')
            if shared is not None:
                data['db_client'] = await orm_get_client_by_tg(shared, from_user.id)
                data['db_mentor'] = await orm_mentor_for(shared, from_user.id)
            else:
                async with self.session_pool() as own:
                    data['db_client'] = await orm_get_client_by_tg(own, from_user.id)
                    data['db_mentor'] = await orm_mentor_for(own, from_user.id)
        return await handler(event, data)
