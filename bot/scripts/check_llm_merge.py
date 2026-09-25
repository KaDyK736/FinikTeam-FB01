"""Проверка связки LLM+бот на учебных входах tests.json (кейс FB01).

Для каждой реплики человека строит карточку двумя способами: только правила
движка и правила+LLM, затем сверяет обе с expected_* из tests.json.
Меню и тексты бота прогон не трогает.

Запуск из bot/:  python scripts/check_llm_merge.py
"""
import asyncio
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from assistant import analyzer, engine  # noqa: E402

TESTS_PATH = ROOT.parent / 'data' / 'fb01' / 'tests.json'


def card_for(profile: dict) -> dict:
    return engine.build_card({**profile, 'client_id': profile.get('client_id') or 'test'})


async def main() -> None:
    tests = json.loads(TESTS_PATH.read_text(encoding='utf-8'))
    # Берём только диалоговые входы (F001..F010): проверки загрузчика F011/F012
    # без client_id — не реплика человека (тот же отбор, что в run_tests.py).
    inputs = [t for t in tests if t.get('input') and t.get('client_id') is not None]
    print(f'USE_LLM(файл .env) = {os.getenv("USE_LLM")} | MODEL = {os.getenv("LLM_MODEL")} '
          f'| BASE = {os.getenv("LLM_BASE_URL")}')
    print(f'Входов из tests.json: {len(inputs)}\n')

    same, drifted, wrong = 0, [], []
    for item in inputs:
        text, tid = item['input'], item['test_id']

        os.environ['USE_LLM'] = '0'
        rules_card = card_for(engine.apply_answer({'segment': 'unknown'}, text, 'goal'))

        os.environ['USE_LLM'] = '1'
        merged_card = card_for(await analyzer.apply_answer_async({'segment': 'unknown'}, text, 'goal'))

        expected_ok = (
            merged_card['segment'] == item['expected_segment']
            and merged_card['do_not_contact'] == item['expected_do_not_contact']
            and merged_card['next_action'] == item['expected_next_action']
        )
        mark = 'OK ' if expected_ok else 'FAIL'
        diff = '' if rules_card == merged_card else ' ≠правила'
        if not diff:
            same += 1
        else:
            drifted.append((tid, rules_card, merged_card))
        if not expected_ok:
            wrong.append(tid)
        print(f"[{mark}] {tid}{diff} segment={merged_card['segment']} "
              f"interests={merged_card['interests'] or '-'} next={merged_card['next_action']!r}\n       вход: {text!r}")

    print(f'\nИтого: входов {len(inputs)}, совпадений с чистыми правилами {same}, '
          f'расхождений {len(drifted)}, провалов ожидаемых {len(wrong)} {wrong or ""}')
    for tid, rules_card, merged_card in drifted:
        keys = [k for k in ('segment', 'interests', 'next_action', 'do_not_contact')
                if rules_card[k] != merged_card[k]]
        print(f'\n--- {tid}: различие только в {keys}')
        for k in keys:
            print(f'    {k}: правила={rules_card[k]!r} | правила+LLM={merged_card[k]!r}')


asyncio.run(main())
