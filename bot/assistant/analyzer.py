"""LLM-разбор реплики человека поверх правил движка (кейс FB01).

Модель делает то, что не умеют ключевые слова: понимает цель, интересы и
красные флаги в перефразированных репликах («хочу подзаработать»,
«интересует то, чем моют полы»). Правила engine.py считаются одновременно:
выводы модели скрещиваются с ними, а при любой ошибке модели bot работает
только правилами — меню и тексты бота от LLM не зависят.

Вход — одна реплика и шаг диалога, выход — движковский Analysis.
"""
import json
import re

from assistant import engine
from assistant.engine import Analysis
from assistant.llm import chat_json, llm_enabled

VALID_GOALS = frozenset(engine.GOAL_SIGNALS)
VALID_TOPICS = frozenset(engine.INTEREST_TOPICS)
VALID_FLAGS = frozenset(engine.FLAG_SIGNALS)

SYSTEM_PROMPT = f"""Ты разбираешь одно сообщение человека из первичного диалога компании (кейс FB01).
Верни ровно один JSON-объект без пояснений и без markdown:

{{
 "goals": {{"<personal|income|business>": "<дословная цитата из сообщения>"}},
 "interests": {{"<тема из списка ниже>": "<дословная цитата из сообщения>"}},
 "flags": {{"<promo|guarantee|medical|external_action>": "<дословная цитата>"}},
 "refusal": {{"quote": "<дословная цитата>"}},
 "farewell": false
}}

Цели — только если человек ЯВНО назвал намерение (вопрос про цену, скидку или
лечение целью не является):
- personal — покупать для себя или семьи;
- income — заработок, подработка, доход;
- business — своя команда, группа, развитие бизнеса.
По каждой цели — цитата, где человек о ней говорит. Нет явного намерения — goals = {{}}.

Интересы — товары или направления, которые человек назвал сам. Название темы бери
ровно из списка:
{', '.join(sorted(VALID_TOPICS))}.
Нет подходящей темы — придумай короткую формулировку (2-4 слова), но только по явным
словам человека, и тоже с цитатой.

Флаги (красные флаги, передаются наставнику):
- promo — спрашивает про скидки, акции, промокоды, цены, доставку, условия;
- guarantee — просит гарантировать доход;
- medical — спрашивает о лечении болезней или гарантированных свойствах товаров;
- external_action — просит зарегистрировать, оплатить, оформить заказ за него.

refusal — только когда человек прямо просит прекратить общение или удалить его
(не вежливое прощание: для «спасибо, до свидания» — refusal без ключа).
Цитата обязана стоять в сообщении без изменений; вывод без цитаты не принимается.
"""


def _user_prompt(step: str, text: str) -> str:
    question = engine.QUESTIONS.get(step, 'вопрос о цели знакомства')
    return f"Шаг диалога: {step}. Вопрос бота: {question}\n\nСообщение человека:\n{text}"


def _clean_words(raw: str, limit: int = 80) -> str:
    return re.sub(r'\s+', ' ', str(raw or '')).strip()[:limit]


def _norm(raw: str) -> str:
    return re.sub(r'\s+', ' ', str(raw or '')).strip().lower().replace('ё', 'е')


def _quote_ok(quote: str, original: str) -> str:
    """Цитата допустима, только дословно стоит в сообщении (нормализация регистров)."""
    normalized, source = _norm(quote), _norm(original)
    return normalized if normalized and normalized in source else ''


def _checked_items(raw: dict, original: str, valid: frozenset, kind: str) -> tuple[str, ...]:
    """Оставляет выводы, которые движок подтверждает своими словарями по цитате.

    kind — 'goal', 'interest' или 'flag': сверяем с соответствующими сигналами
    engine.analyse(цитаты). Модель тем самым только переводчик между живой
    речью и словарём движка; вывод без дословного доказательства отбрасывается.
    """
    lowered = _norm(original)
    kept = []
    for name, quote in (raw or {}).items():
        key = _norm(name)
        if key not in valid:
            continue
        quote_text = _quote_ok(quote, original)
        if not quote_text:
            continue
        if kind == 'interest':
            # Тема интереса должна быть названа в цитате или в сообщении:
            # интерес не приписываем, вывод делает движок по своим словам-сигналам.
            confirmed = key in lowered or key in quote_text or engine.analyse(quote_text).interests
        else:
            analysis = engine.analyse(quote_text)
            confirmed = key in (analysis.goals if kind == 'goal' else analysis.flags)
        if confirmed:
            kept.append(key)
    return tuple(dict.fromkeys(kept))


def _free_interests(raw: dict, original: str, known: tuple[str, ...]) -> tuple[str, ...]:
    """Свои формулировки модели: принимем только явные слова человека без сигнала темы."""
    lowered = _norm(original)
    result = []
    for name, quote in (raw or {}).items():
        key = _clean_words(name, 60)
        topic = _norm(key)
        if not key or topic in VALID_TOPICS or topic in known:
            continue
        quote_text = _quote_ok(key, original) or _quote_ok(quote, original)
        if not quote_text or len(topic.split()) < 2:
            continue
        if any(signal in lowered for signal in ('скидк', 'акци', 'цен', 'стоимост', 'доставк', 'вылеч')):
            continue
        result.append(key)
    return tuple(dict.fromkeys(result))


def _to_analysis(payload: dict, original_text: str) -> Analysis:
    """JSON модели -> Analysis движка.

    Каждый вывод модели сверяется с цитатой и словарями движка: цели, темы и
    флаги без дословного подтверждения в сообщении отбрасываются (правило
    кейса «вывод без цитаты не публикуется»). Приоритет размечает только
    движок по маркерам в исходной реплике.
    """
    goals = _checked_items(payload.get('goals'), original_text, VALID_GOALS, 'goal')
    interests = _checked_items(payload.get('interests'), original_text, VALID_TOPICS, 'interest')
    interests += _free_interests(payload.get('interests'), original_text, interests)

    flags = _checked_items(payload.get('flags'), original_text, VALID_FLAGS, 'flag')
    if 'guarantee' in flags:
        # Правило движка: гарантию флагуем только в контексте дохода.
        if not engine._hits(_norm(original_text), ('доход', 'заработ', 'тысяч', 'рубл', 'оклад',
                                                   'процент', 'прибыл', 'подработ', 'деньги')):
            flags = tuple(f for f in flags if f != 'guarantee')

    refusal_data = payload.get('refusal')
    refusal_quote = ''
    if isinstance(refusal_data, dict):
        refusal_quote = _quote_ok(refusal_data.get('quote', ''), original_text)
    elif refusal_data is True:
        refusal_quote = _norm(original_text)[:80]
    refusal = bool(refusal_quote) and bool(engine._hits(refusal_quote, engine.REFUSAL_SIGNALS))

    segment = goals[0] if len(goals) == 1 else 'unknown'
    return Analysis(
        text=original_text,
        goals=goals,
        segment=segment,
        priority_given=False,
        refusal=refusal,
        flags=flags,
        interests=tuple(dict.fromkeys(interests)),
        matched=goals + flags + interests,
    )


def merge(base: Analysis, extra: Analysis) -> Analysis:
    """Скрещивает разбор правил (base) и модели (extra).

    Цели определяет только движок по явным словам: правило кейса — не
    домысливать намерение (вопрос про скидку LLM иногда читается как «покупки
    для себя»). Сегмент берётся у правил; если они не определили, а модель
    видит ровно одну цель, доверяем модели — так работают перефразировки.
    Интересы и флаги складываются: здесь модель ловит то, чего ключевые
    слова не видят.
    """
    goals = base.goals
    flags = tuple(dict.fromkeys(base.flags + extra.flags))
    interests = tuple(dict.fromkeys(base.interests + extra.interests))

    segment = base.segment
    # Сегменту модели доверяем только когда она сама назвала явную цель:
    # вывод намерения из интереса к товару запрещён (KB04).
    if segment == 'unknown' and extra.goals and len(extra.goals) <= 1 and extra.segment != 'unknown':
        segment = extra.segment

    return Analysis(
        text=base.text or extra.text,
        goals=goals,
        segment=segment,
        priority_given=base.priority_given,
        refusal=base.refusal or extra.refusal,
        flags=flags,
        interests=interests,
        matched=goals + flags + interests,
    )


async def analyse_turn(text: str, step: str) -> Analysis:
    """Разбор реплики правилами + LLM. Ошибка модели не видна человеку."""
    base = engine.analyse(text)
    if not llm_enabled() or not text.strip():
        return base
    try:
        payload = await chat_json(SYSTEM_PROMPT, _user_prompt(step, text))
        if not isinstance(payload, dict):
            raise ValueError('модель вернула не объект')
        extra = _to_analysis(payload, text)
    except Exception as error:
        print(f'[llm] разбор отменён, работают правила: {type(error).__name__}: {str(error)[:200]}')
        return base
    return merge(base, extra)


async def apply_answer_async(profile: dict, text: str, step: str) -> dict:
    """Как engine.apply_answer, но реплику разбирает и модель тоже."""
    analysis = await analyse_turn(text, step)
    return engine.apply_analysis(profile, text, step, analysis)
