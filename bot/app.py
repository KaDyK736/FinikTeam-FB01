"""Точка входа: собирает диспетчер в порядке курса (handlers/database/kbds/...)."""
import asyncio
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

from database.engine import close_db, init_db, session_maker  # noqa: E402
from handlers.admin import admin_router  # noqa: E402
from handlers.client_private import client_router  # noqa: E402
from handlers.mentor import mentor_router  # noqa: E402
from middlewares.db import DataBaseSession  # noqa: E402
from middlewares.user import ActorFromDB  # noqa: E402

# Порядок важен: команды наставника и админки перехватываются раньше
# общего диалога клиента.
ROUTER_ORDER = (mentor_router, admin_router, client_router)


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    for router in ROUTER_ORDER:
        dp.include_router(router)
    dp.update.middleware(DataBaseSession(session_pool=session_maker))
    dp.update.middleware(ActorFromDB(session_pool=session_maker))
    return dp


async def on_startup():
    await init_db()
    print('[db] готова:', os.getenv('DB_URL', 'sqlite+aiosqlite:///fb01_bot.db'))


async def on_shutdown():
    await close_db()
    print('[bot] остановлен')


async def main():
    token = os.getenv('TOKEN') or os.getenv('BOT_TOKEN')
    if not token:
        raise SystemExit('Не задан TOKEN. Скопируйте .env.example в .env и возьмите токен у @BotFather.')

    # Прокси нужен, когда api.telegram.org недоступен напрямую (например, из вашей сети).
    # Задаётся в .env: PROXY_URL=http://127.0.0.1:порт  (для socks5 нужен пакет aiohttp_socks).
    proxy = os.getenv('PROXY_URL', '').strip()
    session = AiohttpSession(proxy=proxy) if proxy else None
    if proxy:
        print(f'[bot] трафик Telegram через прокси {proxy}')

    bot = Bot(token=token, session=session,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = create_dispatcher()
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('[bot] выключен по Ctrl+C')
