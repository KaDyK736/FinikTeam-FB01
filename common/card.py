"""Схема карточки клиента и её проверка."""

from common.knowledge import segments

REQUIRED_FIELDS = [
    "client_id",
    "segment",
    "interests",
    "evidence",
    "missing_information",
    "do_not_contact",
    "next_action",
    "draft_message",
    "requires_human_approval",
    "clarifying_question",
    "escalate_to_mentor",
]

LIST_FIELDS = ["interests", "missing_information"]

ROLE_BY_SEGMENT = {
    "personal": "Покупатель",
    "income": "Консультант",
    "business": "Бизнес-партнёр",
    "unknown": "Роль не определена",
}

FORBIDDEN_PHRASES = [
    "гарантируем доход",
    "гарантированный доход",
    "будешь зарабатывать",
    "вы получите",
    "акция",
    "скидка",
    "бесплатная доставка",
    "вылечит",
    "исцелит",
    "паспорт",
    "номер карты",
    "смс-код",
    "пароль",
]


def client_role(card: dict) -> str:
    return ROLE_BY_SEGMENT.get(card.get("segment"), ROLE_BY_SEGMENT["unknown"])


def facts_from_card(card: dict) -> list[str]:
    """Что уже считается установленным, чтобы агент не переспрашивал и не терял цель."""
    if not card:
        return []
    facts = [f"сегмент/роль: {card.get('segment')} ({client_role(card)})"]
    facts += [f"интерес: {item}" for item in card.get("interests") or []]
    facts += [f"не хватает: {item}" for item in card.get("missing_information") or []]
    for item in card.get("evidence") or []:
        if isinstance(item, dict) and item.get("quote"):
            facts.append(f"клиент говорил: «{item['quote']}»")
    if card.get("do_not_contact"):
        facts.append("клиент просил больше не писать")
    return facts


def format_card(card: dict, *, updated_at: str = "", validation: dict | None = None) -> str:
    """Человеческий вид карточки для наставника."""
    lines = [
        f"Клиент {card.get('client_id') or 'без идентификатора'}"
        + (f" · обновлена {updated_at}" if updated_at else ""),
        f"Роль: {client_role(card)} (segment = {card.get('segment')})",
        f"Хочет не писать: {'да' if card.get('do_not_contact') else 'нет'}",
        f"Уверенность агента: {card.get('confidence') or '—'}",
    ]

    interests = card.get("interests") or []
    lines.append("Интересы: " + ("; ".join(str(i) for i in interests) if interests else "—"))

    evidence = card.get("evidence") or []
    lines.append("Опора на слова клиента:")
    lines += [f"— «{item.get('quote')}» ({item.get('source')})" for item in evidence if isinstance(item, dict)]
    if not evidence:
        lines.append("— цитат нет")

    missing = card.get("missing_information") or []
    lines.append("Не хватает: " + ("; ".join(str(m) for m in missing) if missing else "—"))
    lines.append(f"Следующий шаг: {card.get('next_action') or '—'}")

    question = str(card.get("clarifying_question") or "").strip()
    if question:
        lines.append(f"Бот спросил клиента: {question}")
    if str(card.get("draft_message") or "").strip():
        lines.append(f"Черновик наставнику: {card['draft_message']}")
    lines.append(
        "Нужна проверка человека: "
        + ("да" if card.get("requires_human_approval", True) else "нет")
        + (", нужен ответ наставника" if card.get("escalate_to_mentor") else "")
    )

    if validation:
        if validation.get("ok"):
            lines.append("Проверка схемы: пройдена")
        else:
            lines.append("Проверка схемы: " + "; ".join(validation.get("errors") or []))
        warnings = validation.get("warnings") or []
        if warnings:
            lines.append("Вопросы к формулировкам: " + "; ".join(warnings))

    return "\n".join(lines)[:4000]


def is_valid_client_id(client_id) -> bool:
    return isinstance(client_id, str) and bool(client_id.strip())


def validate_card(card: dict, client_texts: list[str] | None = None) -> dict:
    """Возвращает errors (карточку нельзя принимать) и warnings (человек проверит вывод)."""
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(card, dict):
        return {"ok": False, "errors": ["агент вернул не объект"], "warnings": []}

    for field in REQUIRED_FIELDS:
        if field not in card:
            errors.append(f"нет поля {field}")

    segment = card.get("segment")
    if segment not in segments():
        errors.append(f"segment вне словаря: {segment!r}")

    if not isinstance(card.get("do_not_contact"), bool):
        errors.append("do_not_contact должен быть логическим")

    for field in LIST_FIELDS:
        if not isinstance(card.get(field), list):
            errors.append(f"{field} должен быть списком")

    evidence = card.get("evidence")
    if not isinstance(evidence, list):
        errors.append("evidence должен быть списком")
    elif not evidence:
        errors.append("evidence пуст: вывод не подтверждён цитатой")
    else:
        quotes = " ".join(str(item.get("quote", "")) for item in evidence if isinstance(item, dict))
        if not quotes.strip():
            errors.append("в evidence нет ни одной цитаты")
        if client_texts and not any(
            str(item.get("quote", "")).strip() in text
            for item in evidence if isinstance(item, dict)
            for text in client_texts
        ):
            errors.append("цитата не встречается в репликах клиента")

    if card.get("requires_human_approval") is not True:
        errors.append("requires_human_approval обязан быть true")

    if not str(card.get("next_action") or "").strip():
        errors.append("пустой next_action")

    if card.get("do_not_contact") and str(card.get("draft_message") or "").strip():
        errors.append("при do_not_contact draft_message должен быть пустым")

    if not is_valid_client_id(card.get("client_id")):
        warnings.append("client_id не определён — карточку не сливать с другой")

    # Проверяем только то, что может уйти клиенту: черновик и вопрос. next_action — внутренняя
    # инструкция наставнику, там «не обещать дохода» — правильная формулировка, а не нарушение.
    answer = " ".join(
        str(card.get(field) or "")
        for field in ("draft_message", "clarifying_question")
    ).lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase in answer:
            warnings.append(f"подозрительная формулировка: «{phrase}»")

    # Ведущий диалога — машина состояний, поэтому пустой clarifying_question при unknown теперь норма:
    # бот задаст свой вопрос. Опасен обратный случай — нечем задавать: FSM идёт по missing_information.
    if segment == "unknown" and not card.get("do_not_contact") and not card.get("missing_information"):
        warnings.append("цель неизвестна, и missing_information пуст — спрашивать будет не о чём")

    return {"ok": not errors, "errors": errors, "warnings": warnings}
