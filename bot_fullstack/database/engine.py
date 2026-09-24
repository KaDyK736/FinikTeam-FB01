"""Инициализация локальной базы и загрузка учебных событий регистрации.

Доступа к сайту Faberlic нет, поэтому событием регистрации считается строка из
registration_events.json кейса: она наливается в базу при первом старте.
"""
import os

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from assistant import knowledge
from database.models import Base
from database.repository import INVALID, orm_apply_event, orm_count_clients, orm_seed_mentors
from database.site_export import MENTOR_PROFILES, mentor_profiles_from_env

# sqlite+aiosqlite:///fb01_bot.db
# postgresql+asyncpg://login:password@localhost:5432/db_name
DB_URL = os.getenv('DB_URL', 'sqlite+aiosqlite:///fb01_bot.db')

sql_engine = create_async_engine(DB_URL, echo=os.getenv('DB_ECHO') == '1')
session_maker = async_sessionmaker(bind=sql_engine, class_=AsyncSession, expire_on_commit=False)

# Наставник определяется по номеру телефона — ключ сверки тот же, что у клиента.
# Реальные номера живут только в .env: MENTOR_PHONE=+79000000000,+79000000001
MENTORS: tuple[dict, ...] = MENTOR_PROFILES + mentor_profiles_from_env(os.getenv('MENTOR_PHONE', ''))


async def create_db() -> None:
    async with sql_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def fix_mentor_table() -> None:
    """Пересоздаёт таблицу наставников старого образца.

    В первой версии доступ давался по telegram_id, теперь ключ — номер телефона.
    Привязка чата восстановится сама, когда наставник снова пришлёт свой номер,
    поэтому других данных миграция не касается.
    """
    def outdated(sync_conn) -> bool:
        names = inspect(sync_conn).get_table_names()
        if 'mentor' not in names:
            return False
        return 'phone' not in {c['name'] for c in inspect(sync_conn).get_columns('mentor')}

    async with sql_engine.begin() as conn:
        if await conn.run_sync(outdated):
            await conn.execute(text('DROP TABLE mentor'))
            print('[db] таблица наставников пересоздана: ключом стал номер телефона')
    await create_db()


async def drop_db() -> None:
    async with sql_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def load_events(session: AsyncSession) -> dict:
    """Загружает события кейса. Повторная загрузка безопасна — это проверка FB01-F012."""
    counters = {'created': 0, 'updated': 0, 'invalid': 0}
    for event in knowledge.registration_events():
        _, status, _note = await orm_apply_event(session, event)
        counters['invalid' if status == INVALID else status] += 1
    return counters


async def init_db(session: AsyncSession | None = None) -> dict:
    await create_db()
    await fix_mentor_table()
    if session is not None:
        await orm_seed_mentors(session, MENTORS)
        return await load_events(session)
    async with session_maker() as own:
        await orm_seed_mentors(own, MENTORS)
        if await orm_count_clients(own) == 0:
            counters = await load_events(own)
            print(f"[db] события регистрации: {counters}")
            return counters
    return {'skipped': True}


async def close_db() -> None:
    await sql_engine.dispose()
