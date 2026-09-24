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
# Номера задаются до импорта database.engine и database.case_seed: иначе прогон
# зависит от того, что случайно осталось в окружении или в .env.
DEMO_PHONE = '+79001112233'   # вымышленный: настоящий номер пользователя в тестах не нужен
MENTOR_PHONE = '+7 999 000-00-99'
os.environ['DEMO_PHONE'] = DEMO_PHONE
os.environ['MENTOR_PHONE'] = MENTOR_PHONE

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from assistant import engine, knowledge  # noqa: E402
from database import case_seed  # noqa: E402
from database.engine import MENTORS, Base, close_db, load_events, session_maker, sql_engine  # noqa: E402
from database.models import Mentor  # noqa: E402
from database.repository import (  # noqa: E402
    INVALID, orm_add_turn, orm_apply_event, orm_count_clients, orm_count_mentors,
    orm_get_client, orm_get_mentor, orm_get_mentor_by_phone, orm_link_phone,
    orm_list_clients, orm_list_turns, orm_mentor_for, orm_offer_contact, orm_seed_mentors,
    orm_update, profile_of,
)
from database.site_export import register_url  # noqa: E402
from kbds.inline import contact_label, register_keyboard  # noqa: E402
from kbds.reply import (  # noqa: E402
    BUSINESS_BUTTONS, CLIENT_BUTTONS, MENU, client_menu, start_keyboard,
)
from utils.cards import client_card_text, draft_text, mentor_card_text  # noqa: E402
from utils.validators import mask_phone, normalize_phone  # noqa: E402

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
        again = case_seed.events()[0]
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

        f001 = await orm_get_client(session, 'F001')
        check('карточка F001 собрана из tests.json и номера сайта',
              f001.source == case_seed.SOURCE_LABEL and f001.site_loaded
              and f001.goal_answer == 'Хочу покупать для себя, интересует уход за домом.',
              f001.source)
        check('настоящий номер из .env лёг на карточку F001',
              f001.site_phone == DEMO_PHONE, mask_phone(f001.site_phone))
        phones = {c.client_id: c.site_phone for c in clients if c.client_id.startswith('F')}
        check('у всех десяти карточек кейса есть номер телефона',
              len(phones) == 10 and all(phones.values()), str(phones))
        check('номера телефонов не повторяются', len(set(phones.values())) == 10)
        check('номер клиента ищет карточку, а не заводит вторую',
              (await orm_link_phone(session, 6000000002, phones['F003']))[1] == 'found')


async def check_card_text_clean() -> None:
    """В тексте карточки — только смысл: без внутренних идентификаторов и путей."""
    async with session_maker() as session:
        client = await orm_get_client(session, 'F002')
        texts = (mentor_card_text(client), client_card_text(client), draft_text(client))
        noise = ('registration_events.json', 'tests.json', 'evidence_source',
                 'requires_human_approval', '{', '}', 'None', 'B' + str(CLIENT_TG))
        for name, text in zip(('наставнику', 'клиенту', 'черновик'), texts):
            check(f'текст карточки {name}: без путей к файлам и служебных ключей',
                  all(word not in text for word in noise), text[:60].replace('\n', ' '))
        check('карточка наставнику подтверждает вывод цитатой человека',
              'Ищу дополнительный доход' in mentor_card_text(client))
        removed = ('Фамилия', 'Имя', 'Отчество', 'Пол', 'E-mail', 'Населённый пункт',
                   'Дата рождения', 'Телефон пригласившего', 'Город')
        for name, text in zip(('наставнику', 'клиенту', 'черновик'), texts):
            check(f'карточка {name}: полей анкеты сайта не осталось',
                  all(word not in text for word in removed),
                  next((w for w in removed if w in text), 'чисто'))
        check('в карточке клиента его собственный номер открыт',
              '+79134862057' in client_card_text(client))
        check('наставнику номер скрыт',
              '+79134862057' not in mentor_card_text(client)
              and '***' in mentor_card_text(client), mentor_card_text(client)[-30:])


async def check_no_card_without_phone() -> None:
    """Карточка заводится только сайтом: неизвестный номер остаётся без карточки."""
    async with session_maker() as session:
        before = await orm_count_clients(session)
        client, status = await orm_link_phone(session, 6000000003, '+7 999 000-11-22')
        check('номера нет в базе — карточка не заведена',
              client is None and status == 'not-found', str(status))
        check('после неизвестного номера карточек больше не стало',
              await orm_count_clients(session) == before)
        unknown, bad_status = await orm_link_phone(session, 6000000004, 'абракадабра')
        check('нераспознанный ввод карточку не заводит',
              unknown is None and bad_status == 'bad-phone'
              and await orm_count_clients(session) == before, str(bad_status))
        note = (f"Сверка телефона заводит карточку только если номер уже есть в базе "
                f"анкет сайта: чужой номер даёт статус «{status}».")
        NOTES.append(note)


async def check_contact_button() -> None:
    """Кнопка связи: только с согласия человека, со статусом и текстом уведомления."""
    async with session_maker() as session:
        await orm_seed_mentors(session, MENTORS)
        mentor = await orm_get_mentor_by_phone(session, MENTORS[0]['phone'])
        silent = await orm_get_client(session, 'F006')
        check('без согласия связь не предлагается',
              silent.do_not_contact and contact_label(silent) == '', contact_label(silent))
        after = await orm_offer_contact(session, silent, mentor, '01.01.2026 00:00')
        check('нажатие на кнопку не меняет карточку отказавшегося',
              after.contact_offered_at is None and not after.contact_offered_by)

        client = await orm_get_client(session, 'F002')
        check('партнёру по цели подписываем кнопку по роли',
              contact_label(client) == 'Связаться с партнёром по бизнесу', contact_label(client))
        check('карточка до нажатия — в статусе ожидания',
              engine.build_card(profile_of(client))['status'] == 'awaiting_mentor')
        await orm_offer_contact(session, client, mentor, '24.09.2026 12:00')
        card = engine.build_card(profile_of(client))
        check('нажатие поставило статус «наставник готов помочь»',
              card['status'] == 'mentor_ready' and client.contact_offered_by == mentor.name,
              f"{card['status']} / {client.contact_offered_by}")
        check('история карточки пополнилась записью наставника',
              any(turn.step == 'contact_offered' and mentor.name in turn.text
                  for turn in await orm_list_turns(session, client)))
        notice = engine.mentor_ready_text(card, mentor.name)
        check('уведомление человеку — от конкретного наставника',
              mentor.name in notice and 'готов вам помочь' in notice, notice[:70])
        check('уведомление без обещаний дохода, цен и лечения',
              all(word not in notice.lower() for word in
                  ('гарант', 'рубл', 'скидк', 'вылеч', 'процент')), notice[:70])
        check('уведомление напоминает, как остановить общение', 'не пишите' in notice)
        check('статус связи виден и клиенту, и наставнику',
              'готов помочь' in mentor_card_text(client) and 'готов помочь' in client_card_text(client))
        await orm_update(session, client, contact_offered_at=None, contact_offered_by=None)


async def check_farewell() -> None:
    """Прощание вежливо закрывает диалог и не портит карточку."""
    greetings = ('Спасибо', 'спасибо большое', 'до свидания', 'Спасибо до свидания', 'Пока',
                 'всего доброго', 'всем пока', 'благодарю', 'хорошего дня',
                 'Thanks', 'thank you very much', 'goodbye', 'bye bye', 'see you later',
                 'Have a nice day!', 'take care', 'cheers')
    for phrase in greetings:
        check(f'прощание распознано: {phrase}', engine.is_farewell(phrase))
    keep = ('Пока просто смотрю, ещё не решил.', 'Хочу покупать для себя, интересует уход за домом.',
            'Спасибо, но мне нужна подработка', 'Хочу пока просто посмотреть каталог')
    for phrase in keep:
        check(f'не прощание: {phrase[:28]}', not engine.is_farewell(phrase))
    check('прощание не читается как отказ',
          not engine.analyse('Спасибо до свидания').refusal
          and not engine.analyse('goodbye').refusal)
    check('ответ на прощание вежливый и без обещаний',
          all(word not in engine.FAREWELL_REPLY.lower() for word in ('гарант', 'рубл', 'вылеч'))
          and 'завершён' in engine.FAREWELL_REPLY.lower(), engine.FAREWELL_REPLY[:40])
    async with session_maker() as session:
        client = await orm_get_client(session, 'F004')
        before = client.goal_answer
        await orm_add_turn(session, client, 'user', 'Пока', step='farewell')
        await orm_update(session, client, dialogue_step='closed')
        check('прощание не перезаписывает цель в карточке',
              client.goal_answer == before and client.dialogue_step == 'closed', before)


async def check_role_filter() -> None:
    """Фильтр карточек по цели: клиент или партнёр по бизнесу."""
    async with session_maker() as session:
        everyone = await orm_list_clients(session, limit=500)
        by_role = {
            role: await orm_list_clients(session, segments=segments or None, limit=500)
            for role, segments in engine.ROLE_SEGMENTS.items()
        }
        check('роли покрывают все карточки без потерь и дублей',
              sum(len(items) for role, items in by_role.items() if role != 'all') == len(everyone))
        check('клиенты — это покупка для себя',
              {c.client_id for c in by_role['client']} == {'F001', 'F009'},
              str(sorted(c.client_id for c in by_role['client'])))
        check('партнёры по бизнесу — доход и развитие группы',
              {c.client_id for c in by_role['partner']} == {'F002', 'F003', 'F008', 'F010'},
              str(sorted(c.client_id for c in by_role['partner'])))
        check('роль в карточке совпадает с фильтром',
              {engine.role_of(c) for c in by_role['partner']} == {'partner'})
        for raw, expected in (('', 'all'), ('клиенты', 'client'), ('партнеры', 'partner'),
                              ('бизнес', 'partner'), ('неопределившиеся', 'undefined'),
                              ('что-то не то', 'all')):
            check(f'фильтр принят: {raw or "/cards"}',
                  engine.normalize_role(raw) == expected, engine.normalize_role(raw))


def check_menus() -> None:
    """Меню: экран входа с кнопкой «Начнем» и раздельные блоки анкеты и бизнеса."""
    entry = [button.text for row in start_keyboard().keyboard for button in row]
    check('экран входа — одна кнопка «Начнем»', entry == [MENU['start']], str(entry))

    menu = client_menu(with_phone=True)
    rows = [[button.text for button in row] for row in menu.keyboard]
    labels = [text for row in rows for text in row]
    check('меню клиента: диалог, анкета, правка и вопрос наставнику',
          set(CLIENT_BUTTONS) <= set(labels), str(labels)[:120])
    check('бизнес-кнопки — часть того же меню',
          set(BUSINESS_BUTTONS) <= set(labels), str(labels)[:120])
    check('бизнес не смешивается с анкетными кнопками в одном ряду',
          all(all(text.startswith('Бизнес') for text in row)
              or not any(text.startswith('Бизнес') for text in row) for row in rows),
          str(rows)[:120])


def check_business_goal() -> None:
    """Бизнес-кнопки: формулировка цели совпадает с тем, что понимает движок."""
    for key, phrase in engine.BUSINESS_GOALS.items():
        profile = engine.apply_answer({'segment': 'unknown'}, phrase, 'goal')
        check(f'бизнес-кнопка «{key}» ведёт в цель {engine.SEGMENTS[key]}',
              profile['segment'] == key
              and engine.role_of_segment(profile['segment']) == 'partner',
              f'{profile["segment"]} ← «{phrase}»')


def check_registration_offer() -> None:
    """Человека без анкеты сайта отправляем регистрироваться: карточку не заводим."""
    url = register_url()
    check('ссылка ведёт на сайт Faberlic с номером пригласившего',
          url.startswith('https://faberlic.com/') and 'sponsornumber=' in url, url[:70])
    keyboard = register_keyboard(url, retry=True)
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    check('кнопка регистрации открывается ссылкой, а не callback',
          any(button.url == url for button in buttons), str([b.text for b in buttons])[:120])
    check('вернуться к сверке номера можно кнопкой',
          any('сверить номер' in button.text for button in buttons),
          str([b.text for b in buttons])[:120])
    offer = engine.REGISTRATION_OFFER.format(url=url)
    check('текст про регистрацию объясняет ссылку и не заводит карточку',
          'зарегистрируйтесь' in offer.lower() and url in offer, offer[:80])
    check('движок понимает слова про отсутствие анкеты',
          engine.mentions_registration('Я ещё не зарегистрирован')
          and engine.mentions_registration('анкеты на сайте не заводил')
          and not engine.mentions_registration('Хочу развивать бизнес'), '')
    NOTES.append('Если номера нет в выгрузке сайта, бот не заводит карточку, а даёт ссылку '
                 'на регистрацию и просит прислать тот же номер после анкеты.')


async def check_card_beats_mentor() -> None:
    """Номер из выгрузки сайта — клиент, даже если он же числится наставником."""
    async with session_maker() as session:
        card = await orm_get_client(session, 'F009')
        was_bound = card.telegram_id
        before = await orm_count_mentors(session)
        session.add(Mentor(name='Наставник с клиентским номером', phone=card.site_phone))
        await session.commit()

        chat = 7100000001
        client, status = await orm_link_phone(session, chat, card.site_phone)
        check('карточка сайта важнее списка наставников',
              client is not None and client.client_id == 'F009' and status == 'found',
              str(status))
        check('человек с клиентским номером не получает доступ наставника',
              await orm_mentor_for(session, chat) is None)
        mentor = await orm_get_mentor_by_phone(session, card.site_phone)
        if mentor is not None:
            await session.delete(mentor)
        card.telegram_id = was_bound   # проверяемый чат не должен остаться в базе
        await session.commit()
        check('проверочная запись наставника убрана из базы',
              await orm_count_mentors(session) == before, f'было {before}')


async def check_phone_matching() -> None:
    """Сверка телефона: номер из выгрузки сайта находит карточку, а не заводит дубль."""
    forms = ('+79990000004', '8 (999) 000-00-04', '9990000004', '89990000004')
    parsed = {form: normalize_phone(form) for form in forms}
    check('номер распознаётся во всех написаниях',
          set(parsed.values()) == {'+79990000004'}, str(parsed))

    async with session_maker() as session:
        known = await orm_get_client(session, 'F005')
        digits = known.site_phone          # +79631470258
        alt_form = f'8 ({digits[2:5]}) {digits[5:8]}-{digits[8:10]}-{digits[10:]}'
        total = await orm_count_clients(session)

        client, status = await orm_link_phone(session, CLIENT_TG, alt_form)
        check('номер из выгрузки сайта нашёл свою карточку',
              client is not None and client.client_id == 'F005' and status == 'found', str(status))
        check('карточка привязана к чату человека',
              client.telegram_id == CLIENT_TG and client.site_loaded)
        again, status2 = await orm_link_phone(session, CLIENT_TG, known.site_phone)
        check('повторная сверка не создаёт вторую карточку',
              await orm_count_clients(session) == total and again.id == client.id
              and status2 == 'found', str(status2))

        other, status3 = await orm_link_phone(session, 9999999999, known.site_phone)
        check('чужой чат по этому номеру карточку не получает и дубль не заводит',
              other is not None and other.id == known.id and status3 == 'found'
              and other.telegram_id == CLIENT_TG
              and await orm_count_clients(session) == total, str(status3))


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
        check('чужой номер не делает человека клиентом и не заводит карточку',
              stranger_status == 'not-found' and stranger is None
              and await orm_get_mentor(session, 7770000002) is None
              and await orm_count_clients(session) == clients_before, str(stranger_status))
    NOTES.append(f'Доступ наставника проверяется по номеру {digits} из списка наставников: '
                 'карточка клиента при этом не заведена, а telegram_id подставляется '
                 'после того, как человек прислал свой номер.')


def report(tests: list[dict], path: pathlib.Path) -> None:
    passed = sum(1 for _n, ok, _d in RESULTS if ok)
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    lines = [
        '# Прогон проверок кейса FB01', '',
        f'Время: {now}', f'Проверок: {len(RESULTS)}, пройдено: {passed}, провалено: {len(RESULTS) - passed}', '',
        'Движок правил читает knowledge_base.json, segmentation_rules.json и '
        'dialogues.json. Карточки базы собраны из реплик tests.json и номеров '
        'телефонов выгрузки сайта: карточка есть только у человека, чей номер '
        'пришёл с сайта. Ожидаемые ответы из tests.json сравниваются снаружи и в '
        'базу знаний агента не попадают.', '',
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
    await check_no_card_without_phone()
    await check_mentor_by_phone()
    await check_card_text_clean()
    await check_contact_button()
    await check_farewell()
    await check_role_filter()
    check_menus()
    check_business_goal()
    check_registration_offer()
    await check_card_beats_mentor()
    await close_db()
    (ROOT / 'run_tests.db').unlink(missing_ok=True)
    report(tests, ROOT / 'results' / 'FB01_проверки.md')
    return 0 if all(ok for _n, ok, _d in RESULTS) else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
