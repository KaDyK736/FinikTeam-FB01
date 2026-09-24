"""Пересборка локальной базы из файлов кейса.

Сносит старые таблицы и наливает карточки F001..F010 заново: реплики человека из
02_Учебные_данные/tests.json и номер телефона формы регистрации из выгрузки сайта.
Настоящий номер (DEMO_PHONE или MENTOR_PHONE из .env) попадает на карточку F001,
остальные — вымышленные. Сегмент, интересы и отказ считает движок правил,
ожидаемые ответы из tests.json в базу не пишутся.

История диалогов старой базы удаляется вместе с таблицами — заранее сохраните
файл fb01_bot.db, если он нужен.

Запуск:  python scripts/rebuild_db.py
"""
import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from dotenv import find_dotenv, load_dotenv  # noqa: E402

load_dotenv(find_dotenv())

from assistant import engine  # noqa: E402
from database import case_seed  # noqa: E402
from database.engine import close_db, reset_db, session_maker  # noqa: E402
from database.repository import orm_count_mentors, orm_list_clients  # noqa: E402
from utils.validators import mask_phone  # noqa: E402

COLUMNS = ('client_id', 'роль', 'телефон', 'цель', 'связь')


async def main() -> int:
    print(f'[db] настоящий номер клиента: '
          f'{mask_phone(case_seed.my_phone()) if case_seed.my_phone() else "не задан"} '
          f'→ карточка {case_seed.DEMO_CLIENT_ID}')
    counters = await reset_db()
    async with session_maker() as session:
        clients = await orm_list_clients(session, limit=500)
        mentors = await orm_count_mentors(session)
    print(f"[db] события: создано {counters['created']}, обновлено {counters['updated']}, "
          f"отклонено {counters['invalid']}; наставников: {mentors}")
    print('\t'.join(COLUMNS))
    for client in clients:
        role = engine.ROLE_LABELS[engine.role_of_segment(client.segment)]
        contact = 'нельзя писать' if client.do_not_contact else (
            f'готов помочь {client.contact_offered_by}' if client.contact_offered_at else 'нет связи')
        print('\t'.join((
            client.client_id, role,
            mask_phone(client.site_phone), engine.SEGMENTS.get(client.segment, client.segment),
            contact,
        )))
    for role, segments in engine.ROLE_SEGMENTS.items():
        total = sum(1 for c in clients if not segments or c.segment in segments)
        print(f'фильтр «{engine.ROLE_LABELS[role]}»: {total} карточек')
    await close_db()
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
