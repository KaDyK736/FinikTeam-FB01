"""Точка входа прототипа FB01: Dispatcher, роутеры клиента и наставника, база карточек."""

import asyncio
import os

from aiogram import Bot, Dispatcher, types
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

from common.bot_cmds_list import private          # noqa: E402
from common.llm import get_base_url, get_model, get_temperature  # noqa: E402
from database.engine import create_db, drop_db, session_maker    # noqa: E402
from filters.is_mentor import mentor_ids          # noqa: E402
from handlers.client import client_router         # noqa: E402
from handlers.mentor import mentor_router         # noqa: E402
from middlewares.db import DataBaseSession        # noqa: E402

bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()

# Наставник проверяется первым: его команды не должны уходить в клиентский диалог.
dp.include_router(mentor_router)
dp.include_router(client_router)


async def on_startup(bot: Bot):
    if os.getenv("DB_RESET", "0") == "1":
        await drop_db()
    await create_db()
    print(f"Модель: {get_model()} @ {get_base_url()} (temperature={get_temperature()})")
    if not mentor_ids():
        print("MENTOR_USER_IDS пуст — режим наставника выключен, все пользователи считаются клиентами.")


async def main():
    dp.startup.register(on_startup)
    dp.update.middleware(DataBaseSession(session_pool=session_maker))

    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_my_commands(commands=private, scope=types.BotCommandScopeAllPrivateChats())
    await dp.start_polling(bot, allowed_updates=["message"])


if __name__ == "__main__":
    asyncio.run(main())
