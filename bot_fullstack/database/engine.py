"""Инициализация локальной базы и загрузка учебных карточек кейса.

Доступа к сайту Faberlic нет, поэтому карточки F001..F010 собираются из файлов
кейса: реплики человека — из tests.json, номер телефона формы регистрации — из
выгрузки сайта (database/site_export.py). Сегмент, интересы и отказ считает
движок правил, а не переписываются из ожидаемых ответов.
"""
import os

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import case_seed
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


async def migrate_schema() -> None:
    """Пересоздаёт таблицы, которые остались от старой схемы.

    Первая версия отдавала доступ к карточкам по telegram_id и не знала статуса
    связи, поэтому sqlite просто отказался бы писать в несуществующие колонки.
    Потом из карточки убрали поля анкеты сайта (ФИО, город, e-mail, дата
    рождения, пол, телефон пригласившего) и перестали заводить карточки прямо из
    чата — в старой таблице от них остались пустые колонки.
    Таблица наставников — это конфиг, а не данные клиентов: её меняем молча, а
    снос карточек показываем явно, потому что вместе с ними уходит и история
    диалогов.
    """
    # (проверяемая таблица, колонка, что снести, ждём колонку или Избавляемся)
    fixes = (
        ('mentor', 'phone', ('mentor',), 'missing'),
        ('client', 'contact_offered_at', ('dialogue_turn', 'client'), 'missing'),
        ('client', 'site_city', ('dialogue_turn', 'client'), 'extra'),
    )

    def outdated_tables(sync_conn) -> list[str]:
        names = set(inspect(sync_conn).get_table_names())
        result: list[str] = []
        for table, column, drop, mode in fixes:
            if table not in names:
                continue
            has_column = column in {c['name'] for c in inspect(sync_conn).get_columns(table)}
            if has_column == (mode == 'extra'):
                result += [name for name in drop if name in names]
        return list(dict.fromkeys(result))

    async with sql_engine.begin() as conn:
        doomed = await conn.run_sync(outdated_tables)
        if doomed:
            for table in doomed:
                await conn.execute(text(f'DROP TABLE IF EXISTS {table}'))
            print(f'[db] пересозданы таблицы под новую схему: {", ".join(doomed)}')
    await create_db()


async def drop_db() -> None:
    async with sql_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def reset_db() -> dict:
    """Полная пересборка базы: старые карточки и история диалогов удаляются."""
    await drop_db()
    await create_db()
    async with session_maker() as session:
        await orm_seed_mentors(session, MENTORS)
        return await load_events(session)


async def load_events(session: AsyncSession) -> dict:
    """Загружает карточки кейса. Повторная загрузка безопасна — это проверка FB01-F012."""
    counters = {'created': 0, 'updated': 0, 'invalid': 0}
    for event in case_seed.events():
        _, status, _note = await orm_apply_event(session, event)
        counters['invalid' if status == INVALID else status] += 1
    return counters


async def init_db(session: AsyncSession | None = None) -> dict:
    await create_db()
    await migrate_schema()
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
