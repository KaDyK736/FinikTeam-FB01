"""Доступ к карточкам клиентов."""

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import ClientCard


def dialogue_of(record: ClientCard) -> list[dict]:
    return json.loads(record.dialogue_json or "[]")


def card_of(record: ClientCard) -> dict:
    return json.loads(record.card_json or "{}")


async def find(session: AsyncSession, client_id: str) -> ClientCard | None:
    return await session.scalar(select(ClientCard).where(ClientCard.client_id == client_id))


async def by_telegram_user(session: AsyncSession, telegram_user_id: int) -> ClientCard | None:
    return await session.scalar(
        select(ClientCard).where(ClientCard.telegram_user_id == telegram_user_id)
        .order_by(ClientCard.updated_at.desc())
    )


async def open_record(session: AsyncSession, client_id: str, *,
                      telegram_user_id: int | None = None, display_name: str = "") -> ClientCard:
    record = await find(session, client_id)
    if record is None:
        record = ClientCard(client_id=client_id, telegram_user_id=telegram_user_id, display_name=display_name)
        session.add(record)
        await session.commit()
    elif telegram_user_id is not None:
        record.telegram_user_id = telegram_user_id
        await session.commit()
    return record


async def save(session: AsyncSession, record: ClientCard, *,
               turns: list[dict], card: dict | None = None) -> None:
    record.dialogue_json = json.dumps(turns, ensure_ascii=False)
    record.turn_count = sum(1 for turn in turns if turn.get("role") == "user")
    if card:
        record.card_json = json.dumps(card, ensure_ascii=False)
        record.segment = str(card.get("segment") or "unknown")
        record.do_not_contact = bool(card.get("do_not_contact"))
    record.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await session.commit()


async def reset(session: AsyncSession, record: ClientCard) -> None:
    await session.delete(record)
    await session.commit()


async def recent(session: AsyncSession, limit: int = 30) -> list[ClientCard]:
    result = await session.scalars(
        select(ClientCard).order_by(ClientCard.updated_at.desc()).limit(limit)
    )
    return list(result)
