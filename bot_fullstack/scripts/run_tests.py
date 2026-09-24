"""Прогон проверок кейса FB01 без токена Telegram.

Движок правил (assistant/engine.py) и загрузчик событий проверяются на учебных
данных напрямую: тот же код работает и в боте, и здесь. Результаты складываются
в results/FB01_проверки.md — там фиксируются id проверки, фактические значения и
время прогона (требование из «ПОЛЯ_И_ПОРЯДОК_ПРОВЕРКИ.txt»).

Запуск:  python scripts/run_tests.py
"""
import asyncio
import datetime
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Тестовая база всегда своя: прогон не должен трогать рабочую fb01_bot.db.
os.environ['DB_URL'] = f'sqlite+aiosqlite:///{(ROOT / "run_tests.db").as_posix()}'

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from assistant import engine, knowledge  # noqa: E402
from database.engine import MENTORS, Base, close_db, load_events, session_maker, sql_engine  # noqa: E402
from database.repository import (  # noqa: E402
    INVALID, orm_apply_event, orm_count_clients, orm_count_mentors, orm_get_client,
    orm_get_mentor, orm_get_mentor_by_phone, orm_link_phone, orm_list_clients,
    orm_mentor_for, orm_seed_mentors, profile_of,
)
from utils.validators import normalize_phone  # noqa: E402

CLIENT_TG = 5000000004  # условный чат: настоящий id в кейсе запрещён

RESULTS: list[tuple[str, bool, str]] = []
NOTES: list[str] = []


def check(name: str, ok: bool, detail: str = '') -> None:
    RESULTS.append((name, bool(ok), detail))


def run_event_tests(tests: list[dict]) -> None:
    """Проверки FB01-F001..F010: сегмент, запрет на контакт и следующий шаг."""
    for item in tests:
        client_id = item.get('client_id')
        if client_id is None:
            continue
        profile = engine.apply_answer({'segment': 'unknown'}, item['input'], 'goal')
        card = engine.build_card(profile)
        tid = item['test_id']
        check(f"{tid} сегмент = {item['expected_segment']}",
              card['segment'] == item['expected_segment'], f"факт: {card['segment']}")
        check(f"{tid} do_not_contact = {item['expected_do_not_contact']}",
              card['do_not_contact'] == item['expected_do_not_contact'],
              f"факт: {card['do_not_contact']}")
        check(f"{tid} следующий шаг",
              card['next_action'] == item['expected_next_action'],
              f"факт: {card['next_action']}")
        check(f"{tid} вывод подтверждён цитатой",
              any(entry['quote'] == item['input'] for entry in card['evidence']))
        check(f"{tid} требует подтверждения человеком", card['requires_human_approval'] is True)


def check_boundaries(tests: list[dict]) -> None:
    """Границы прототипа: ни выдуманных условий, ни обещаний, ни внешних действий."""
    forbidden = ('гарантируем доход', 'вы получите', 'скидка 50', 'акция действует', '₽', 'рублей')
    for item in tests:
        if item.get('client_id') is None:
            continue
        profile = engine.apply_answer({'segment': 'unknown'}, item['input'], 'goal')
        card = engine.build_card(profile)
        text = ' '.join(engine.replies_for(profile)) + ' ' + card['draft_message']
        check(f"{item['test_id']} нет выдуманных цифр и обещаний",
              all(word not in text.lower() for word in forbidden), text[:80])
        check(f"{item['test_id']} ответ о границах передаёт вопрос человеку",
              'наставник' in text.lower() or card['next_action'] in (
                  engine.BASE_ACTIONS['personal'], engine.BASE_ACTIONS['income'],
                  engine.BASE_ACTIONS['business'], engine.BASE_ACTIONS['unknown'],
                  engine.DUAL_GOAL_ACTION, engine.REFUSAL_ACTION), card['next_action'])


def check_unknown_paraphrase() -> None:
    """Самопроверка из описания: перефразированный запрос без явной цели."""
    profile = engine.apply_answer({'segment': 'unknown'}, 'Просто интересуюсь, что это вообще за возможности.', 'goal')
    card = engine.build_card(profile)
    check('перефраз: цель не угадывается', card['segment'] == 'unknown', f"факт: {card['segment']}")
    check('перефраз: задаём уточняющий вопрос',
          engine.next_question(profile) == engine.QUESTIONS['clarify']
          or card['next_action'] == engine.BASE_ACTIONS['unknown'],
          f"вопрос: {engine.next_question(profile)}")
    NOTES.append('Перефразированный вход: «Просто интересуюсь, что это вообще за возможности.» → '
                 f'сегмент {card["segment"]}, шаг «{card["next_action"]}».')


def check_parameter_change() -> None:
    """Самопроверка из описания: меняем входной параметр — меняются вывод и карточка."""
    profile = engine.apply_answer({'segment': 'unknown'}, 'Хочу покупать для себя.', 'goal')
    before = engine.build_card(profile)
    edited = engine.apply_answer(profile, 'Скорее развивать команду.', 'goal')
    after = engine.build_card(edited)
    check('правка цели: сегмент пересчитан',
          before['segment'] == 'personal' and after['segment'] == 'business',
          f"{before['segment']} → {after['segment']}")
    check('правка цели: следующий шаг пересчитан',
          after['next_action'] == engine.BASE_ACTIONS['business'], after['next_action'])
    check('правка цели: старая цитата осталась в истории',
          before['evidence'][0]['quote'] == 'Хочу покупать для себя.')
    NOTES.append(f'Смена параметра: «Хочу покупать для себя.» ({before["segment"]}) → '
                 f'«Скорее развивать команду.» ({after["segment"]}, шаг «{after["next_action"]}»).')


async def check_loader() -> None:
    """FB01-F011 и FB01-F012: некорректный вход и повторная загрузка события."""
    async with session_maker() as session:
        counters = await load_events(session)
        check('загрузка событий: 10 карточек', counters['created'] == 10, str(counters))

        client, status, note = await orm_apply_event(session, {'initial_message': 'Привет'})
        check('FB01-F011 карточка без client_id не создана', status == INVALID and client is None, note)
        check('FB01-F011 не смешивается с другой карточкой',
              (await orm_get_client(session, 'F001')).goal_answer ==
              'Хочу покупать для себя, интересует уход за домом.')

        before = await orm_count_clients(session)
        again = knowledge.registration_events()[0]
        client, status, _ = await orm_apply_event(session, again)
        total = await orm_count_clients(session)
        check('FB01-F012 повторная загрузка обновила запись', status == 'updated' and client.client_id == 'F001')
        check('FB01-F012 второй экземпляр не создан', total == before, f'было {before}, стало {total}')

        counters2 = await load_events(session)
        check('FB01-F012 весь файл перегружается без дублей',
              counters2['created'] == 0 and counters2['updated'] == 10
              and await orm_count_clients(session) == total, str(counters2))

        clients = await orm_list_clients(session, limit=100)
        check('сегменты всех событий совпали с ожиданиями',
              {c.client_id: c.segment for c in clients} == {
                  'F001': 'personal', 'F002': 'income', 'F003': 'business', 'F004': 'unknown',
                  'F005': 'unknown', 'F006': 'unknown', 'F007': 'unknown', 'F008': 'income',
                  'F009': 'personal', 'F010': 'business'})
        f006 = await orm_get_client(session, 'F006')
        check('F006: контакт прекращён, черновика нет',
              f006.do_not_contact and engine.build_card(profile_of(f006))['draft_message'] == '')


async def check_phone_matching() -> None:
    """Сверка телефона: номер из формы сайта находит карточку, а не заводит дубль."""
    forms = ('+79990000004', '8 (999) 000-00-04', '9990000004', '89990000004')
    parsed = {form: normalize_phone(form) for form in forms}
    check('номер распознаётся во всех написаниях',
          set(parsed.values()) == {'+79990000004'}, str(parsed))

    async with session_maker() as session:
        client, status = await orm_link_phone(session, CLIENT_TG, '8 (999) 000-00-04')
        check('телефон найден в выгрузке сайта', client is not None and status == 'from-site', str(status))
        check('подтянуты поля формы регистрации',
              client.site_city == 'Волгоград' and client.site_loaded and client.site_phone == '+79990000004',
              f'{client.site_city} / {client.site_email}')
        total = await orm_count_clients(session)

        again, status2 = await orm_link_phone(session, CLIENT_TG, '+79990000004')
        check('повторная сверка не создаёт вторую карточку',
              await orm_count_clients(session) == total and again.id == client.id and status2 == 'found',
              str(status2))

        other, status3 = await orm_link_phone(session, 9999999999, '+79990001122')
        check('неизвестный номер заводит отдельную карточку', status3 == 'created' and other.client_id == 'B9999999999')


async def check_mentor_by_phone() -> None:
    """Наставник открывается по номеру телефона, а не по MENTOR_TG_ID."""
    mentor_tg = 7770000001
    first = MENTORS[0]
    digits = first['phone']
    # то же число в другой записи: 8 (999) 000-00-09
    alt = f'8 ({digits[2:5]}) {digits[5:8]}-{digits[8:10]}-{digits[10:]}'
    async with session_maker() as session:
        await orm_seed_mentors(session, MENTORS)
        check('наставники заведены по номеру телефона',
              await orm_count_mentors(session) == len(MENTORS), f'в списке {len(MENTORS)}')
        by_phone = await orm_get_mentor_by_phone(session, alt)
        check('номер наставника распознаётся в любом написании',
              by_phone is not None and by_phone.name == first['name'],
              f"{by_phone.name if by_phone else '—'} / {alt}")
        check('до сверки номера доступа по telegram_id нет',
              await orm_get_mentor(session, mentor_tg) is None)

        clients_before = await orm_count_clients(session)
        client, status = await orm_link_phone(session, mentor_tg, alt)
        check('номер наставника не заводит карточку клиента',
              status == 'mentor' and client is None
              and await orm_count_clients(session) == clients_before, str(status))
        check('после сверки номера наставник узнаётся',
              await orm_mentor_for(session, mentor_tg) is not None)

        await orm_seed_mentors(session, MENTORS)
        again = await orm_get_mentor_by_phone(session, digits)
        check('повторная загрузка конфига не дублирует наставников',
              await orm_count_mentors(session) == len(MENTORS))
        check('привязка telegram_id после перезагрузки сохранена',
              again is not None and again.telegram_id == mentor_tg,
              str(again.telegram_id if again else None))

        # один чат может прислать номер другого наставника — прежний теряет привязку
        second = MENTORS[1]['phone']
        await orm_link_phone(session, mentor_tg, second)
        first_after = await orm_get_mentor_by_phone(session, digits)
        second_after = await orm_get_mentor_by_phone(session, second)
        check('смена номера переключает наставника, а не роняет уникальность',
              first_after is not None and first_after.telegram_id is None
              and second_after is not None and second_after.telegram_id == mentor_tg)
        await orm_link_phone(session, mentor_tg, digits)

        stranger, stranger_status = await orm_link_phone(session, 7770000002, '+79990007777')
        check('чужой номер остаётся клиентом',
              stranger_status == 'created' and stranger is not None
              and await orm_get_mentor(session, 7770000002) is None, str(stranger_status))
        await session.delete(stranger)
        await session.commit()
    NOTES.append(f'Доступ наставника проверяется по номеру {digits} из списка наставников: '
                 'карточка клиента при этом не заведена, а telegram_id подставляется '
                 'после того, как человек прислал свой номер.')


def report(tests: list[dict], path: pathlib.Path) -> None:
    passed = sum(1 for _n, ok, _d in RESULTS if ok)
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    lines = [
        '# Прогон проверок кейса FB01', '',
        f'Время: {now}', f'Проверок: {len(RESULTS)}, пройдено: {passed}, провалено: {len(RESULTS) - passed}', '',
        'Движок правил читает knowledge_base.json, segmentation_rules.json, '
        'registration_events.json и dialogues.json. Ожидаемые ответы из tests.json '
        'сравниваются снаружи, в базу знаний агента они не попадают.', '',
        '## Результаты', '',
        '| Проверка | Результат | Факт |', '| --- | --- | --- |',
    ]
    for name, ok, detail in RESULTS:
        lines.append(f'| {name} | {"PASS" if ok else "FAIL"} | {detail or "—"} |')
    lines += ['', '## Дополнительно', '']
    lines += [f'- {note}' for note in NOTES]
    lines += ['', '## Карточка примера (output_example.json) и наша для F002', '',
              '```json',
              str(engine.build_card({'client_id': 'F002',
                                     'goal_answer': tests[1]['input'],
                                     'segment': 'income',
                                     'interests': 'дополнительный доход',
                                     'available_time': 'два вечера в неделю'})),
              '```', '']
    path.parent.mkdir(exist_ok=True)
    path.write_text('\n'.join(lines), encoding='utf-8')
    width = max(len(name) for name, _ok, _d in RESULTS)
    for name, ok, detail in RESULTS:
        print(f'[{"ok" if ok else "FAIL"}] {name.ljust(width)} {detail}')
    print(f'\nПройдено {passed} из {len(RESULTS)}. Отчёт: {path.relative_to(ROOT)}')


async def main() -> int:
    tests = knowledge.tests()
    async with sql_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    run_event_tests(tests)
    check_boundaries(tests)
    check_unknown_paraphrase()
    check_parameter_change()
    await check_loader()
    await check_phone_matching()
    await check_mentor_by_phone()
    await close_db()
    (ROOT / 'run_tests.db').unlink(missing_ok=True)
    report(tests, ROOT / 'results' / 'FB01_проверки.md')
    return 0 if all(ok for _n, ok, _d in RESULTS) else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
