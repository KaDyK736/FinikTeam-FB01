"""Наставник — второй пользователь бота: смотрит карточки и расшифровки, сам ничего не отправляет."""

from aiogram import Router, types
from aiogram.filters import Command, CommandObject, CommandStart
from sqlalchemy.ext.asyncio import AsyncSession

from common import knowledge
from common.card import format_card, validate_card
from database import repository as repo
from filters.chat_types import ChatTypeFilter
from filters.is_mentor import MentorFilter

mentor_router = Router()
mentor_router.message.filter(ChatTypeFilter(["private"]))
mentor_router.message.filter(MentorFilter())

MENTOR_GUIDE = (
    "Режим наставника (кейс FB01).\n"
    "/clients — все карточки, которые собрал бот\n"
    "/card F002 — карточка целиком: роль, цитаты, следующий шаг, черновик\n"
    "/dialog F002 — о чём говорили с этим человеком\n"
    "/unknown — у кого цель ещё не определена\n\n"
    "Клиенту бот не пишет: всё, что выглядит как ответ клиенту, остаётся черновиком и требует вашей проверки."
)

USAGE = "Нужен client_id, например: /card F002. Список клиентов — /clients"


async def _load(session: AsyncSession, client_id: str) -> str | None:
    record = await repo.find(session, client_id)
    if record is None:
        return f"Карточки {client_id} в базе нет. Известные: " \
               f"{', '.join(event['client_id'] for event in knowledge.registration_events())} или /clients"
    if not record.card_json:
        return f"{client_id}: диалог есть ({record.turn_count} реплик), карточка ещё не собрана."

    turns = repo.dialogue_of(record)
    card = repo.card_of(record)
    card.setdefault("client_id", client_id)
    client_texts = [turn["text"] for turn in turns if turn.get("role") == "user"]
    validation = validate_card(card, client_texts) if client_texts else validate_card(card)

    text = format_card(card, updated_at=record.updated_at, validation=validation)
    if card.get("escalate_to_mentor"):
        text += "\n\nВопрос вне учебной базы знаний — ответ за вами."
    return text


@mentor_router.message(CommandStart())
async def mentor_start(message: types.Message):
    await message.answer(MENTOR_GUIDE)


@mentor_router.message(Command("clients"))
async def mentor_clients(message: types.Message, session: AsyncSession):
    records = await repo.recent(session, limit=50)
    if not records:
        await message.answer("В базе пока нет карточек — начните диалог клиентом под другим аккаунтом.")
        return
    lines = [f"Карточек: {len(records)}"]
    for record in records:
        status = f"{record.segment} · реплик {record.turn_count} · {record.updated_at}"
        if record.do_not_contact:
            status = "не беспокоить · " + status
        lines.append(f"— {record.client_id}: {status}")
    await message.answer("\n".join(lines)[:4000])


@mentor_router.message(Command("unknown"))
async def mentor_unknown(message: types.Message, session: AsyncSession):
    records = [r for r in await repo.recent(session, limit=100) if r.segment == "unknown"]
    if not records:
        await message.answer("С неопределённой целью клиентов нет.")
        return
    await message.answer(
        "Цель не определена у: " + ", ".join(record.client_id for record in records)
        + "\nУточняющий вопрос уже задан клиенту, смотреть /card <id>."
    )


@mentor_router.message(Command("card"))
async def mentor_card(message: types.Message, session: AsyncSession, command: CommandObject):
    client_id = (command.args or "").strip()
    await message.answer((await _load(session, client_id)) if client_id else USAGE)


@mentor_router.message(Command("dialog"))
async def mentor_dialog(message: types.Message, session: AsyncSession, command: CommandObject):
    client_id = (command.args or "").strip()
    if not client_id:
        await message.answer(USAGE)
        return
    record = await repo.find(session, client_id)
    if record is None:
        await message.answer(f"Диалога {client_id} в базе нет.")
        return
    turns = repo.dialogue_of(record)
    if not turns:
        await message.answer(f"{client_id}: реплик нет.")
        return
    lines = [f"Диалог {client_id}, реплик: {len(turns)}"]
    lines += [f"{'клиент' if t.get('role') == 'user' else 'бот'}: {t.get('text')}" for t in turns]
    await message.answer("\n".join(lines)[:4000])


@mentor_router.message()
async def mentor_other(message: types.Message):
    await message.answer(MENTOR_GUIDE)
