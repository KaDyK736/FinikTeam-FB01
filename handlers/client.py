"""Диалог с новым человеком после события регистрации (кейс FB01, сценарии F001–F010)."""

from aiogram import Router, types
from aiogram.filters import Command, CommandStart
from sqlalchemy.ext.asyncio import AsyncSession

from common import knowledge
from common.card import client_role, facts_from_card, format_card, validate_card
from common.case import DialogueContext
from common.llm import LlmNotConfigured, LlmUnavailable, chat_json
from common.prompts import CARD_SYSTEM_PROMPT, build_card_prompt
from database import repository as repo
from filters.chat_types import ChatTypeFilter

client_router = Router()
client_router.message.filter(ChatTypeFilter(["private"]))

WELCOME = (
    "Я учебный ассистент первичного контакта Faberlic (кейс FB01).\n"
    "Расскажите, с какой целью вы регистрируетесь — я заполню карточку для наставника.\n\n"
    "Команды:\n"
    "/start F002 — взять карточку из учебного события регистрации\n"
    "/card — что про вас записано\n"
    "/new — начать диалог заново\n\n"
    "Черновик сообщения клиенту готовит наставник, сам бот ничего не отправляет."
)

NOT_CONTACT = (
    "Вы просили не писать — диалог закрыт, карточка сохранена со статусом «не беспокоить».\n"
    "Если передумаете: /new"
)


def build_context(client_id: str, turns: list[dict], new_message: str, previous_card: dict) -> DialogueContext:
    event = knowledge.event_by_client_id(client_id)
    first_user_turn = next((t["text"] for t in turns if t.get("role") == "user" and t.get("text")), "")
    return DialogueContext(
        client_id=client_id,
        initial_message=(event or {}).get("initial_message") or first_user_turn,
        new_message=new_message,
        history=turns[:-1],
        known_facts=facts_from_card(previous_card),
        from_dataset=event is not None,
    )


def answer_for_client(card: dict) -> str:
    """Что видит человек: короткое подтверждение и следующий вопрос бота."""
    lines = [f"Записала в карточку: {client_role(card).lower()}." if card.get("segment") != "unknown"
             else "Записала реплику, цель пока не ясна."]

    interests = card.get("interests") or []
    if interests:
        lines.append("Интересы: " + "; ".join(str(item) for item in interests))

    if card.get("escalate_to_mentor"):
        lines.append("Этот вопрос не из учебной базы знаний — передам наставнику, сама не отвечаю.")

    if card.get("do_not_contact"):
        lines.append("Больше не пишу. Наставник увидит, что вы попросили остановить контакт.")
    else:
        lines.append(f"Следующий шаг: {card.get('next_action')}")

    question = str(card.get("clarifying_question") or "").strip()
    if question:
        lines.append(question)
    return "\n\n".join(lines)


async def process_turn(session: AsyncSession, record, text: str) -> str:
    turns = repo.dialogue_of(record) + [{"role": "user", "text": text}]
    previous_card = repo.card_of(record)
    context = build_context(record.client_id, turns, text, previous_card)

    try:
        card, _ = await chat_json(CARD_SYSTEM_PROMPT, build_card_prompt(context))
    except LlmUnavailable as error:
        await repo.save(session, record, turns=turns)
        return f"Модель сейчас недоступна, карточку не меняла.\n{error}\nРеплику сохранила."
    except LlmNotConfigured as error:
        await repo.save(session, record, turns=turns)
        return f"Не настроено подключение к модели: {error}"
    except ValueError as error:
        await repo.save(session, record, turns=turns)
        return f"Результат неполный: модель не вернула читаемую карточку, ничего не записывала.\n{str(error)[:400]}"

    card["client_id"] = record.client_id
    validation = validate_card(card, context.client_turn_texts())

    if not validation["ok"]:
        await repo.save(session, record, turns=turns)
        return (
            "Результат неполный: карточку не записываю.\n"
            + "; ".join(validation["errors"])
            + "\nУточните, пожалуйста, свой запрос."
        )

    await repo.save(session, record, turns=turns, card=card)
    return answer_for_client(card)


@client_router.message(CommandStart())
async def start_cmd(message: types.Message, session: AsyncSession):
    client_id = (message.text.split(maxsplit=1) + [""])[1].strip()
    user = message.from_user
    display_name = " ".join(part for part in (user.first_name, user.last_name) if part)

    if client_id and knowledge.event_by_client_id(client_id) is None:
        await message.answer(
            f"Учебного события регистрации с client_id={client_id} нет. "
            f"Доступны: {', '.join(e['client_id'] for e in knowledge.registration_events())}.\n\n{WELCOME}",
        )
        return

    record = await repo.open_record(
        session,
        client_id or f"TG{user.id}",
        telegram_user_id=user.id,
        display_name=display_name,
    )

    if not client_id:
        if repo.dialogue_of(record) and not record.do_not_contact:
            await message.answer("Продолжаем. /new — начать заново.")
            return
        await message.answer(WELCOME)
        return

    event = knowledge.event_by_client_id(client_id)
    await message.answer(
        f"Взяла учебное событие {client_id}: «{event['initial_message']}»\nОбрабатываю, это несколько секунд."
    )
    await message.answer(await process_turn(session, record, event["initial_message"]))


@client_router.message(Command("new"))
async def new_cmd(message: types.Message, session: AsyncSession):
    record = await repo.by_telegram_user(session, message.from_user.id)
    if record is not None:
        await repo.reset(session, record)
    await message.answer(WELCOME)


@client_router.message(Command("card"))
async def card_cmd(message: types.Message, session: AsyncSession):
    record = await repo.by_telegram_user(session, message.from_user.id)
    if record is None or not record.card_json:
        await message.answer("Карточки пока нет — напишите, с какой целью вы пришли.")
        return
    card = repo.card_of(record)
    card["client_id"] = card.get("client_id") or record.client_id
    await message.answer(
        "Это карточка, которую увидит наставник:\n\n"
        + format_card(card, updated_at=record.updated_at)
    )


@client_router.message()
async def any_message(message: types.Message, session: AsyncSession):
    text = (message.text or message.caption or "").strip()
    if not text:
        await message.answer("Вижу только вложение — напишите, пожалуйста, словами.")
        return

    record = await repo.by_telegram_user(session, message.from_user.id)
    if record is None:
        record = await repo.open_record(
            session, f"TG{message.from_user.id}",
            telegram_user_id=message.from_user.id,
            display_name=message.from_user.full_name or "",
        )

    if record.do_not_contact:
        await message.answer(NOT_CONTACT)
        return

    await message.answer(await process_turn(session, record, text))
