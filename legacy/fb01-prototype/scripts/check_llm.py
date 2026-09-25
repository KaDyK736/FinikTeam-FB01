"""Проверка подключения к LLM.

    python scripts/check_llm.py models        — список моделей провайдера
    python scripts/check_llm.py prompt        — показать собранный системный промпт
    python scripts/check_llm.py test F002     — карточка по учебному событию
    python scripts/check_llm.py test "реплика" F007 — карточка по своей реплике
"""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(str(ROOT / ".env")))

from common.card import validate_card  # noqa: E402
from common.llm import LlmNotConfigured, LlmUnavailable, complete_json, get_base_url, get_model, list_models  # noqa: E402
from common.prompts import CARD_SYSTEM_PROMPT, build_card_prompt  # noqa: E402
from common.case import load_dataset_case  # noqa: E402


async def cmd_models() -> None:
    found = await list_models()
    print(f"Доступных моделей: {len(found)}")
    for model_id, name in found:
        print(f"  {model_id:<58} {name}")


def cmd_prompt() -> None:
    print(CARD_SYSTEM_PROMPT)
    print("-" * 60)
    print(f"строк: {len(CARD_SYSTEM_PROMPT.splitlines())}, символов: {len(CARD_SYSTEM_PROMPT)}")


async def cmd_test(text: str, client_id: str | None) -> None:
    ctx = load_dataset_case(text, client_id)
    user_prompt = build_card_prompt(ctx)
    card = await complete_json(CARD_SYSTEM_PROMPT, user_prompt)
    print(f"endpoint: {get_base_url()}\nmodel: {get_model()}\nclient_id: {ctx.client_id}")
    print(user_prompt)
    print("-" * 60)
    print(json.dumps(card, ensure_ascii=False, indent=2))
    print("-" * 60)
    print(json.dumps(validate_card(card, ctx.client_turn_texts()), ensure_ascii=False, indent=2))


async def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "prompt"
    argument = sys.argv[2] if len(sys.argv) > 2 else "F002"
    extra = sys.argv[3] if len(sys.argv) > 3 else None

    if command == "models":
        await cmd_models()
    elif command == "prompt":
        cmd_prompt()
    elif command == "test":
        await cmd_test(argument, extra)
    else:
        print(__doc__)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (LlmNotConfigured, LlmUnavailable) as error:
        print(f"Проверка не выполнена: {error}")
        sys.exit(1)
