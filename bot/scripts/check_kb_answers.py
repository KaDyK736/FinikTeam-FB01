"""Проверка ответов по базе знаний на учебных входах tests.json (кейс FB01).

Каждую реплику человека прогоняем через assistant/answers.py дважды: только
правила движка и правила+модель. Смотрим, какое правило базы выбрано и не
появилось ли в ответе выдуманного (цифры, цены, обещания — как в run_tests.py).
Меню и кнопки прогон не трогает.

Запуск из bot/:  python scripts/check_kb_answers.py
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

from assistant import answers  # noqa: E402

TESTS_PATH = ROOT.parent / 'data' / 'fb01' / 'tests.json'
FORBIDDEN = ('гарантируем доход', 'вы получите', 'скидка 50', 'акция действует', '₽', 'рублей')


async def run(text: str, use_llm: str) -> answers.Answer:
    os.environ['USE_LLM'] = use_llm
    return await answers.answer_for(text)


async def main() -> None:
    tests = json.load(open(TESTS_PATH, encoding='utf-8'))
    inputs = [t for t in tests if t.get('input') and t.get('client_id') is not None]
    print(f'MODEL = {os.getenv("LLM_MODEL")} @ {os.getenv("LLM_BASE_URL")}')
    print(f'Входов из tests.json: {len(inputs)}')
    print(f'Вне базы (ожидаем OUT_OF_KB): часть реплик — сообщения о цели, не вопросы\n')

    problems = []
    for item in inputs:
        text, tid = item['input'], item['test_id']
        rules_only = await run(text, '0')
        with_model = await run(text, '1')
        safe = all(word not in with_model.text.lower() for word in FORBIDDEN)
        no_digits = not any(digit in with_model.text for digit in '0123456789')
        if not (safe and no_digits):
            problems.append(tid)
        mark = 'OK ' if safe and no_digits else 'ЖЁСТКО'
        print(f"[{mark}] {tid} правила={rules_only.rule_id or '—'} модель+правила={with_model.rule_id or '—'}")
        print(f'       вход: {text!r}')
        print(f'       ответ: {with_model.text.splitlines()[0][:120]}')
        if rules_only.rule_id != with_model.rule_id:
            print(f'       ⚑ правила выбрали {rules_only.rule_id or "—"}, с моделью — {with_model.rule_id or "—"}')

    # Реплики, которых в базе нет: проверка, что бот честно уходит к наставнику.
    print('\n--- вопросы вне базы знаний ---')
    for text in ('Как дела?', 'Дай совет про погоду', 'Расскажи стих про зиму'):
        rules_only = await run(text, '0')
        with_model = await run(text, '1')
        print(f"{text!r} → правила={rules_only.rule_id or 'нет правила'}, "
              f"модель+правила={with_model.rule_id or 'нет правила'}")
        print(f'    ответ: {with_model.text.splitlines()[0][:120]}')

    print(f'\nИтого: входов {len(inputs)}, ответов с выдуманными условиями или цифрами: {problems or "нет"}')


asyncio.run(main())
