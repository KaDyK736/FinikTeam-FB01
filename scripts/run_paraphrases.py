"""Проверка агента на перефразированных входах (синтетика команды, не данные кейса).

    python scripts/run_paraphrases.py                 # все варианты
    python scripts/run_paraphrases.py F002-P2 F009-P1 # только указанные id
    python scripts/run_paraphrases.py --show          # печатать полные карточки
    python scripts/run_paraphrases.py --model qwen2.5:7b-instruct

Каждая запись paraphrases.json — это исходная ситуация tests.json, у которой заменена
реплика клиента (порядок слов, регистр, опечатки, другой язык, чужие формулировки), а
ожидаемый вывод оставлен прежним. Так видно, держит ли промпт решение по смыслу, а не по
совпадению слов. Исходный текст подменяется и в истории, и в new_message: иначе модель
увидела бы дословную реплику из tests.json, и проверка ничего не стоила бы.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import find_dotenv, load_dotenv  # noqa: E402

load_dotenv(find_dotenv(str(ROOT / ".env")))

from common import knowledge  # noqa: E402
from common.card import FORBIDDEN_PHRASES, validate_card  # noqa: E402
from common.case import DialogueContext  # noqa: E402
from common.llm import LlmNotConfigured, LlmUnavailable, chat_json, get_base_url, get_model  # noqa: E402
from common.prompts import CARD_SYSTEM_PROMPT, build_card_prompt  # noqa: E402

DATA = ROOT / "data" / "fb01" / "paraphrases.json"

# Выдуманное условие всегда лезет в числа: процент скидки, сумма дохода, цена доставки.
NUMBERS = re.compile(r"\d+\s*(?:%|проц|руб|₽|тысяч|сот)\s*", re.IGNORECASE)

# Действие, которое бот вправе только передать человеку. Формулировка в next_action
# «подтвердить условия и оформить регистрацию» — уже обещание сделать за клиента.
# Предложение с передачей наставник в качестве исполнителя обещанием не считается.
ACTION_PROMISE = re.compile(
    r"(оформить|оформл[яю]ю|оплатить|оплач|зарегистр|спиши|подтвердит|отправлю|закажу)[а-яё]*"
    r"|(?:регистраци|заказ|оплат|анкет)",
    re.IGNORECASE,
)
HANDOFF = re.compile(r"(наставник|человек|передат|не выполн|без вас|самостоятель)", re.IGNORECASE)
# «Вы хотите оплатить» — пересказ намерения клиента, а не обещание бота: такое предложение
# из проверки выпадает, обещание в собственном голосе — нет.
CLIENT_VOICE = re.compile(
    r"(хотите|хотел[аи]? бы|просил[аи]?|собираетесь|планируете|интересуетесь|говорите)"
    r"|(?:вы|он|она) (?:хотел[аи]?|просил[аи]?)",
    re.IGNORECASE,
)


def promised_action(text: str) -> str | None:
    """Возвращает фрагмент, где действие берёт на себя бот, а не человек."""
    for sentence in re.split(r"[.;]\s+", text):
        match = ACTION_PROMISE.search(sentence)
        if match and not HANDOFF.search(sentence) and not CLIENT_VOICE.search(sentence):
            return sentence.strip()
    return None


def cases() -> list[dict]:
    return json.loads(DATA.read_text(encoding="utf-8"))


def paraphrase_context(client_id: str, text: str) -> DialogueContext:
    dialogue = knowledge.dialogue_for(client_id) or {}
    history = [
        {"role": turn["role"], "text": text if turn["role"] == "user" else turn["text"]}
        for turn in dialogue.get("messages", [])
    ]
    return DialogueContext(
        client_id=client_id,
        initial_message=text,
        new_message=text,
        history=history,
        known_facts=[],
        from_dataset=True,
    )


def check_expectations(case: dict, card: dict) -> tuple[list[str], list[str]]:
    """problems — зачёт не проставлен; wording — на усмотрение человека."""
    problems: list[str] = []
    wording: list[str] = []

    if card.get("segment") != case["expected_segment"]:
        problems.append(f"segment: {card.get('segment')} вместо {case['expected_segment']}")
    if card.get("do_not_contact") is not case["expected_do_not_contact"]:
        problems.append(f"do_not_contact: {card.get('do_not_contact')}")
    if "expected_escalate" in case and bool(card.get("escalate_to_mentor")) is not case["expected_escalate"]:
        problems.append(f"escalate_to_mentor: {card.get('escalate_to_mentor')}")
    if case.get("expected_question") and not str(card.get("clarifying_question") or "").strip():
        problems.append("нет вопроса-кандидата")
    if len(card.get("missing_information") or []) < case.get("expected_missing_min", 0):
        problems.append(f"missing_information: {card.get('missing_information')}")
    if len(card.get("interests") or []) < case.get("expected_interests_min", 0):
        problems.append(f"interests: {card.get('interests')}")
    if card.get("do_not_contact") and str(card.get("draft_message") or "").strip():
        problems.append("при do_not_contact непустой draft_message")

    outward = {
        field: str(card.get(field) or "")
        for field in ("next_action", "draft_message", "clarifying_question")
    }
    for field, text in outward.items():
        if NUMBERS.search(text):
            problems.append(f"выдуманное условие в {field}: {NUMBERS.search(text).group(0)!r}")
        if case.get("expected_no_action_promise"):
            promised = promised_action(text)
            if promised:
                problems.append(f"обещание действия в {field}: «{promised}»")
        for phrase in FORBIDDEN_PHRASES:
            if phrase in text.lower():
                wording.append(f"{field}: «{phrase}»")

    return problems, wording


async def run_one(case: dict, show: bool) -> dict:
    context = paraphrase_context(case["client_id"], case["input"])
    result = {**case, "status": "FAIL", "problems": []}

    try:
        card, answer = await chat_json(CARD_SYSTEM_PROMPT, build_card_prompt(context))
    except (LlmNotConfigured, LlmUnavailable, ValueError) as error:
        return {**result, "detail": str(error)[:600]}

    check = validate_card(card, context.client_turn_texts())
    problems, wording = check_expectations(case, card)
    if not check["ok"]:
        problems += check["errors"]

    result.update({
        "status": "PASS" if not problems else "FAIL",
        "problems": problems,
        "wording": wording,
        "warnings": check["warnings"],
        "segment": card.get("segment"),
        "do_not_contact": card.get("do_not_contact"),
        "escalate": card.get("escalate_to_mentor"),
        "interests": card.get("interests"),
        "question": str(card.get("clarifying_question") or ""),
        "next_action": str(card.get("next_action") or ""),
        "draft_message": str(card.get("draft_message") or ""),
        "evidence": [item.get("quote") for item in card.get("evidence", []) if isinstance(item, dict)],
        "tokens": f"{answer.prompt_tokens}+{answer.completion_tokens}={answer.total_tokens}",
        "card": card,
    })
    if show:
        print(json.dumps(card, ensure_ascii=False, indent=2))
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ids", nargs="*", help="id из paraphrases.json")
    parser.add_argument("--model")
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()

    if args.model:
        os.environ["LLM_MODEL"] = args.model

    wanted = [c for c in cases() if not args.ids or c["id"] in args.ids]
    print(f"endpoint: {get_base_url()}\nmodel: {get_model()}\nвариантов: {len(wanted)}\n")

    results = []
    for index, case in enumerate(wanted):
        if index:
            await asyncio.sleep(float(os.getenv("TEST_DELAY", "6")))
        started = time.monotonic()
        result = await run_one(case, args.show)
        result["seconds"] = round(time.monotonic() - started, 1)
        results.append(result)
        print(f"{case['id']}: {result['status']} ({result['seconds']}с) [{result.get('segment')}"
              f"{', dnc' if result.get('do_not_contact') else ''}"
              f"{', esc' if result.get('escalate') else ''}]", flush=True)
        print(f"    вход: {case['input']}", flush=True)
        for key in ("problems", "detail", "next_action", "draft_message", "question", "wording", "warnings", "evidence"):
            if result.get(key):
                print(f"    {key}: {result[key]}", flush=True)

    passed = len([r for r in results if r["status"] == "PASS"])
    print(f"\nИтого: {passed}/{len(results)} PASS")
    for result in results:
        if result["status"] != "PASS":
            print(f"  {result['id']}: {result.get('detail') or result.get('problems')}")

    report = ROOT / "_paraphrase_report.json"
    report.write_text(
        json.dumps([{k: v for k, v in r.items() if k != "card"} for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nПодробный отчёт: {report.name}")


if __name__ == "__main__":
    asyncio.run(main())
