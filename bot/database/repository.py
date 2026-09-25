"""Слой доступа к данным карточек нового клиента (кейс FB01).

Здесь сосредоточены три правила кейса:
- события регистрации загружаются по client_id: повторная загрузка обновляет
  запись, а не создаёт вторую;
- вход без client_id считается некорректным и не смешивается с другой карточкой;
- телефон ищет существующую карточку: номера, которого в базе нет, остаётся без
  карточки — бот её не заводит.
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from assistant import analyzer, engine
from common.edit_fields import EDIT_LABELS, apply_edit
from database.models import Client, DialogueTurn, Mentor
from utils.validators import normalize_phone

CREATED = 'created'
UPDATED = 'updated'
INVALID = 'invalid'


def evidence_source_of(client: Client) -> str:
    """Откуда взята цитата: файл кейса или реплики в чате. В текст карточки не выходит."""
    if (client.source or '').startswith('учебное'):
        return f'tests.json:{client.client_id}'
    return 'сообщения в чате'


def profile_of(client: Client) -> dict:
    """Плоский dict карточки для движка правил."""
    return {
        'client_id': client.client_id,
        'display_name': client.display_name,
        'evidence_source': evidence_source_of(client),
        'segment': client.segment,
        'goals': client.goals,
        'interests': client.interests,
        'available_time': client.available_time,
        'experience': client.experience,
        'flags': client.flags,
        'goal_answer': client.goal_answer,
        'clarify_answer': client.clarify_answer,
        'clarify_attempted': client.clarify_attempted,
        'do_not_contact': client.do_not_contact,
        'contact_offered_at': client.contact_offered_at,
        'contact_offered_by': client.contact_offered_by,
        'open_question': client.open_question,
        'dialogue_step': client.dialogue_step,
    }


async def orm_count_clients(session: AsyncSession) -> int:
    return await session.scalar(select(func.count(Client.id))) or 0


async def orm_get_client(session: AsyncSession, client_id: str) -> Client | None:
    return await session.scalar(select(Client).where(Client.client_id == client_id))


async def orm_get_client_by_tg(session: AsyncSession, telegram_id: int) -> Client | None:
    return await session.scalar(select(Client).where(Client.telegram_id == telegram_id))


async def orm_get_client_by_phone(session: AsyncSession, raw_phone: str) -> Client | None:
    phone = normalize_phone(raw_phone)
    if not phone:
        return None
    return await session.scalar(
        select(Client).where(Client.site_phone == phone).order_by(Client.id)
    )


async def orm_list_clients(
    session: AsyncSession, segment: str | None = None, limit: int = 50,
    segments: tuple[str, ...] | None = None,
) -> list[Client]:
    """Список карточек; segments — фильтр по роли (клиент либо партнёр по бизнесу)."""
    stmt = select(Client).order_by(Client.client_id).limit(limit)
    if segment:
        stmt = stmt.where(Client.segment == segment)
    elif segments:
        stmt = stmt.where(Client.segment.in_(segments))
    return list((await session.scalars(stmt)).all())


async def orm_list_turns(session: AsyncSession, client: Client) -> list[DialogueTurn]:
    stmt = select(DialogueTurn).where(DialogueTurn.client_row_id == client.id).order_by(DialogueTurn.id)
    return list((await session.scalars(stmt)).all())


async def orm_add_turn(
    session: AsyncSession, client: Client, role: str, text: str, step: str | None = None,
) -> None:
    session.add(DialogueTurn(client_row_id=client.id, role=role, text=text, step=step))
    await session.commit()


def _apply_site_form(client: Client, form: dict) -> bool:
    """Переносит в карточку данные формы сайта: номер телефона и согласие."""
    if not form:
        return False
    client.site_phone = form.get('phone') or client.site_phone
    client.consent_to_demo = bool(form.get('consent'))
    client.site_loaded = bool(client.site_phone)
    return client.site_loaded


async def orm_link_phone(session: AsyncSession, telegram_id: int, raw_phone: str):
    """Сверка телефона с базой карточек.

    Карточка появляется только из загрузки событий регистрации — то есть только
    для номера, который уже есть в базе. Сверка находит такую карточку и
    привязывает к ней чат; неизвестный номер карточку не создаёт.

    Номер из выгрузки сайта важнее списка наставников: если число стоит и в
    анкете клиента, и в MENTOR_PHONE, человек остаётся клиентом — доступ
    наставника даёт номер, которого среди анкет нет.

    Возвращает (клиент, статус):
      found     — карточка с таким телефоном есть в базе, чат привязан, дубля нет;
      mentor    — это номер наставника: карточка клиента не заводится;
      not-found — такого номера в базе нет, карточку не заводим;
      bad-phone — номер не распознан;
      conflict  — за этим номером уже закреплён другой чат.
    """
    phone = normalize_phone(raw_phone)
    if not phone:
        return None, 'bad-phone'

    by_phone = await orm_get_client_by_phone(session, phone)
    if by_phone is None:
        # Наставник опознаётся по номеру телефона, а не по идентификатору чата.
        mentor = await orm_get_mentor_by_phone(session, phone)
        if mentor is not None:
            await orm_bind_mentor_tg(session, mentor, telegram_id)
            return None, 'mentor'
        return None, 'not-found'

    chat_client = await orm_get_client_by_tg(session, telegram_id)
    if chat_client is not None and chat_client.id != by_phone.id:
        if by_phone.telegram_id not in (None, telegram_id):
            return None, 'conflict'
        # Человек сменил аккаунт или номер: переносим привязку, карточку не множим.
        chat_client.telegram_id = None
    elif by_phone.telegram_id is None:
        by_phone.telegram_id = telegram_id
    await session.commit()
    return by_phone, 'found'


async def orm_link_client_id(session: AsyncSession, telegram_id: int, client_id: str):
    """Привязка по идентификатору события регистрации (client_id из файла сайта)."""
    client = await orm_get_client(session, (client_id or '').strip().upper())
    if client is None:
        return None, 'not-found'
    previous = await orm_get_client_by_tg(session, telegram_id)
    if previous is not None and previous.id != client.id:
        previous.telegram_id = None
    client.telegram_id = telegram_id
    await session.commit()
    return client, 'found'


async def orm_apply_event(session: AsyncSession, event) -> tuple[Client | None, str, str]:
    """Загружает событие регистрации. Ответ на FB01-F011 и FB01-F012."""
    if not isinstance(event, dict):
        return None, INVALID, 'Ожидается объект события регистрации.'
    client_id = str(event.get('client_id') or '').strip()
    if not client_id:
        return None, INVALID, 'В событии нет client_id — карточка не создана и не изменена.'

    initial = str(event.get('initial_message') or '').strip()
    client = await orm_get_client(session, client_id)
    status = UPDATED if client is not None else CREATED
    if client is None:
        client = Client(client_id=client_id)
        session.add(client)

    name = str(event.get('display_name') or '').strip()
    client.registered_at = str(event.get('registered_at') or '') or client.registered_at
    client.source = str(event.get('source') or client.source or '')
    if isinstance(event.get('site_form'), dict):
        # Данные формы регистрации сайта приходят вместе с событием.
        _apply_site_form(client, event['site_form'])
    client.display_name = (name or client.display_name or '').strip()
    if 'consent_to_demo' in event and not client.site_loaded:
        client.consent_to_demo = bool(event.get('consent_to_demo'))

    if status == CREATED:
        await session.flush()  # нужен id карточки, чтобы записать первую реплику

    if status == CREATED and initial:
        await orm_add_turn(session, client, 'user', initial, step='initial')
        updated = await analyzer.apply_answer_async(profile_of(client), initial, 'goal')
        _store_profile(client, updated)
    elif status == UPDATED:
        # Явная коррекция из нового события перекрывает цель, история сохраняется.
        if initial and initial != client.goal_answer:
            await orm_add_turn(session, client, 'user', initial, step='correction')
            updated = await analyzer.apply_answer_async(profile_of(client), initial, 'goal')
            _store_profile(client, updated)

    await session.commit()
    return client, status, ''


def _store_profile(client: Client, profile: dict) -> None:
    for key in ('segment', 'goals', 'interests', 'available_time', 'experience', 'flags',
                'goal_answer', 'clarify_answer', 'dialogue_step'):
        if key in profile:
            setattr(client, key, profile[key])
    client.clarify_attempted = bool(profile.get('clarify_attempted'))
    client.do_not_contact = bool(profile.get('do_not_contact'))


async def orm_save_answer(session: AsyncSession, client: Client, text: str, step: str) -> dict:
    """Применяет ответ к карточке, сохраняет историю и возвращает новый профиль.

    Реплику разбирает правила движка плюс LLM (assistant/analyzer.py): при
    USE_LLM=1 выводы скрещиваются, при ошибке модели остаются правила.
    """
    profile = profile_of(client)
    updated = await analyzer.apply_answer_async(profile, text, step)
    _store_profile(client, updated)
    session.add(DialogueTurn(client_row_id=client.id, role='user', text=text, step=step))
    await session.commit()
    return updated


async def orm_edit_field(session: AsyncSession, client: Client, key: str, text: str) -> dict:
    """Правка параметра, которого нет на форме сайта: значение, история, пересчёт карточки."""
    profile = profile_of(client)
    label = EDIT_LABELS.get(key, key)
    before = profile.get(key) or '—'
    updated = apply_edit(profile, key, text)
    _store_profile(client, updated)
    session.add(DialogueTurn(
        client_row_id=client.id, role='edit',
        text=f'{label}: {before} → {text}', step=key,
    ))
    await session.commit()
    return updated


async def orm_count_mentors(session: AsyncSession) -> int:
    return await session.scalar(select(func.count(Mentor.id))) or 0


async def orm_seed_mentors(session: AsyncSession, mentors: tuple[dict, ...]) -> int:
    """Наставники заводятся по номеру телефона: он и есть ключ доступа к карточкам.

    Повторная загрузка не создаёт дубликат и не затирает telegram_id, который
    человек уже получил, когда впервые прислал свой номер в бот.
    """
    added = 0
    for item in mentors:
        mentor = await orm_get_mentor_by_phone(session, item['phone'])
        if mentor is None:
            session.add(Mentor(name=item['name'], phone=normalize_phone(item['phone'])))
            added += 1
    await session.commit()
    return added


async def orm_get_mentor_by_phone(session: AsyncSession, raw_phone: str) -> Mentor | None:
    phone = normalize_phone(raw_phone)
    if not phone:
        return None
    return await session.scalar(select(Mentor).where(Mentor.phone == phone))


async def orm_get_mentor(session: AsyncSession, telegram_id: int) -> Mentor | None:
    if not telegram_id:
        return None
    return await session.scalar(
        select(Mentor).where(Mentor.telegram_id == telegram_id).limit(1)
    )


async def orm_mentor_for(session: AsyncSession, telegram_id: int) -> Mentor | None:
    """Наставник этого чата: по номеру, который он уже присылал, или по номеру карточки.

    Номер наставника задаётся в .env и не светится в интерфейсе; telegram_id —
    это только следствие сверки, а не право доступа. Один и тот же номер не может
    быть и анкетой клиента, и доступом наставника: карточка сайта побеждает.
    """
    mentor = await orm_get_mentor(session, telegram_id)
    client = await orm_get_client_by_tg(session, telegram_id)
    if mentor is None and client is not None and client.site_phone:
        mentor = await orm_get_mentor_by_phone(session, client.site_phone)
    if mentor is None:
        return None
    if client is not None and client.site_phone == mentor.phone:
        return None
    return mentor


async def orm_bind_mentor_tg(session: AsyncSession, mentor: Mentor, telegram_id: int) -> Mentor:
    """Один чат закреплён за одним наставником: прежнюю привязку снимаем.

    Снятие оформляется отдельным commit — иначе sqlite проверяет уникальный
    индекс до того, как освободит номер, и переход на другого наставника падает.
    """
    previous = await orm_get_mentor(session, telegram_id)
    if previous is not None and previous.id != mentor.id:
        previous.telegram_id = None
        await session.commit()
    mentor.telegram_id = telegram_id
    await session.commit()
    return mentor


async def orm_offer_contact(
    session: AsyncSession, client: Client, mentor: Mentor, at: str,
) -> Client:
    """Отмечает, что наставник вышел на связь: статус карточки и запись в истории.

    Право на действие даёт только согласие человека: при do_not_contact карточку
    не меняем — это правило KB06.
    """
    if client.do_not_contact:
        return client
    client.contact_offered_at = at
    client.contact_offered_by = mentor.name
    session.add(DialogueTurn(
        client_row_id=client.id, role='mentor',
        text=f'{mentor.name}: сообщил, что готов помочь', step='contact_offered',
    ))
    await session.commit()
    return client


async def orm_store_profile(session: AsyncSession, client: Client, profile: dict) -> None:
    """Сохраняет профиль, уже посчитанный движком (использует консольный интерфейс)."""
    _store_profile(client, profile)
    await session.commit()


async def orm_update(session: AsyncSession, client: Client, **values) -> None:
    """Точечное обновление карточки (шаг диалога, вопрос наставнику)."""
    for key, value in values.items():
        setattr(client, key, value)
    await session.commit()
