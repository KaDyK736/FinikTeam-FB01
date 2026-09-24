"""Прогон учебных ситуаций tests.json через LLM.

    python scripts/run_tests.py                       # все 10 содержательных кейсов
    python scripts/run_tests.py F002 F006 F007        # только указанные
    python scripts/run_tests.py --model ministral-8b-latest
    python scripts/run_tests.py --show                # печатать полные карточки

Флаг ok означает совпадение segment и do_not_contact с ожидаемыми плюс пройденную
проверку структуры карточки. Формулировку next_action сравнивает текстом, но решение
о зачёте принимает человек: перефразирование допустимо.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(str(ROOT / ".env")))

from common.card import client_role, validate_card  # noqa: E402
from common.case import load_dataset_case  # noqa: E402
from common.knowledge import tests  # noqa: E402
from common.llm import LlmNotConfigured, LlmUnavailable, chat_json, get_base_url, get_model  # noqa: E402
from common.prompts import CARD_SYSTEM_PROMPT, build_card_prompt  # noqa: E402


def expected_for(client_id: str) -> dict:
    return next((t for t in tests() if t.get("client_id") == client_id), {})


async def run_one(client_id: str, show: bool) -> dict:
    ctx = load_dataset_case(client_id)
    expected = expected_for(client_id)
    result = {"client_id": client_id, "input": ctx.new_message}

    try:
        card, answer = await chat_json(CARD_SYSTEM_PROMPT, build_card_prompt(ctx))
    except (LlmNotConfigured, LlmUnavailable, ValueError) as error:
        return {**result, "status": "ERROR", "detail": str(error)[:900]}

    check = validate_card(card, ctx.client_turn_texts())
    segment_ok = card.get("segment") == expected.get("expected_segment")
    dnc_ok = card.get("do_not_contact") is expected.get("expected_do_not_contact")
    action = str(card.get("next_action") or "")
    action_expected = str(expected.get("expected_next_action") or "")
    question = str(card.get("clarifying_question") or "")

    result.update({
        "tokens": f"{answer.prompt_tokens}+{answer.completion_tokens}={answer.total_tokens}",
        "status": "PASS" if segment_ok and dnc_ok and check["ok"] else "FAIL",
        "segment": f"{card.get('segment')} / {expected.get('expected_segment')}{'' if segment_ok else ' !='}",
        "role": client_role(card),
        "do_not_contact": f"{card.get('do_not_contact')} / {expected.get('expected_do_not_contact')}"
                          f"{'' if dnc_ok else ' !='}",
        "next_action": action,
        "next_action_expected": action_expected,
        "action_text_match": action.split()[0].lower() == action_expected.split()[0].lower() if action and action_expected else False,
        "question": question,
        "escalate": card.get("escalate_to_mentor"),
        "evidence": [item.get("quote") for item in card.get("evidence", []) if isinstance(item, dict)],
        "errors": check["errors"],
        "warnings": check["warnings"],
        "card": card,
    })
    if show:
        print(json.dumps(card, ensure_ascii=False, indent=2))
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ids", nargs="*", help="client_id из tests.json")
    parser.add_argument("--model")
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()

    if args.model:
        os.environ["LLM_MODEL"] = args.model

    wanted = args.ids or [t["client_id"] for t in tests() if t.get("client_id")]
    print(f"endpoint: {get_base_url()}\nmodel: {get_model()}\n")

    results = []
    for index, client_id in enumerate(wanted):
        if index:
            await asyncio.sleep(float(os.getenv("TEST_DELAY", "8")))
        started = time.monotonic()
        result = await run_one(client_id, args.show)
        result["seconds"] = round(time.monotonic() - started, 1)
        results.append(result)
        print(f"{result['client_id']}: {result['status']} ({result['seconds']}с)", flush=True)
        for key in ("tokens", "segment", "do_not_contact", "role", "escalate", "question", "next_action",
                    "next_action_expected", "evidence", "errors", "warnings", "detail"):
            if result.get(key):
                print(f"    {key}: {result[key]}", flush=True)

    passed = len([r for r in results if r["status"] == "PASS"])
    print(f"\nИтого: {passed}/{len(results)} PASS; next_action совпал текстом: "
          f"{len([r for r in results if r.get('action_text_match')])}/{len(results)}")
    for result in results:
        if result["status"] != "PASS":
            print(f"  {result['client_id']}: {result.get('detail') or result.get('errors') or result}")

    bot_level = [t["test_id"] for t in tests() if not t.get("client_id")]
    if bot_level and not args.ids:
        print("Не проверяется одним промптом — это поведение бота: " + ", ".join(bot_level))


if __name__ == "__main__":
    asyncio.run(main())
