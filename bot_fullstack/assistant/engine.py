"""Правила первичного диалога помощника нового клиента (кейс FB01).

Модуль не знает ни про Telegram, ни про базу: чистые функции. Их используют и
бот, и консольный интерфейс, и прогонщик проверок, поэтому поведение на
демонстрации и в тестах совпадает по построению.

Сегмент цели определяется по явным сигналам в словах человека (правило
«сегментировать только по явному намерению» из segmentation_rules.json).
Ответов из tests.json здесь нет.
"""
from dataclasses import dataclass

SEGMENTS: dict[str, str] = {
    'personal': 'Покупка для себя',
    'income': 'Дополнительный доход',
    'business': 'Развитие бизнеса',
    'unknown': 'Цель не определена',
}

GOAL_SIGNALS: dict[str, tuple[str, ...]] = {
    'personal': ('для себя', 'себе', 'покупать', 'покупаю', 'пользоваться', 'косметик', 'уход за'),
    'income': ('доход', 'подработ', 'заработ', 'приработ', 'финанс', 'консультир'),
    'business': ('развивать', 'развити', 'команд', 'групп', 'структур', 'руковод', 'бизнес',
                 'своё дело', 'свою группу', 'партнёр', 'наставник сам'),
}

PRIORITY_MARKERS = ('главн', 'приоритет', 'в первую очередь', 'больше всего', 'именно', 'скорее')
PRIORITY_DENIALS = ('не знаю', 'не определил', 'ещё не решил', 'пока не решил', 'не выбрал', 'не понял')

REFUSAL_SIGNALS = ('не пишите', 'не пиши', 'не звоните', 'не звони', 'больше не', 'прекрати',
                   'останови', 'отстань', 'удали меня', 'отпиши', 'не общайся', 'не хочу общаться')

INTEREST_TOPICS: dict[str, tuple[str, ...]] = {
    'уход за домом': ('дом', 'уборк', 'бытов', 'кухн'),
    'косметика и уход': ('косметик', 'крем', 'маска', 'уход за лицом', 'гель', 'скатк'),
    'парфюмерия': ('духи', 'парфюм', 'аромат'),
    'декоративная косметика': ('макияж', 'помад', 'тушь', 'тональн'),
    'здоровье и витамины': ('витамин', 'здоровь', 'бад', 'иммун'),
    'одежда и обувь': ('одет', 'обув', 'бель', 'одежд'),
    'детская линия': ('детск', 'ребен', 'ребён'),
    'дополнительный доход': ('доход', 'подработ', 'заработ'),
    'развитие команды': ('команд', 'групп', 'структур'),
    'скидки и условия': ('скидк', 'акци', 'промоко', 'балл', 'доставк', 'стоимост', 'цен'),
}

# Красные флаги: тема, требующая передачи наставнику, и границы прототипа.
FLAG_SIGNALS: dict[str, tuple[str, ...]] = {
    'promo': ('скидк', 'акци', 'промоко', 'балл', 'доставк', 'стоимост', 'цен', 'условия акции'),
    'guarantee': ('гарант',),
    'medical': ('вылеч', 'излеч', 'болезн', 'лекарств', 'диагноз', 'давлен', 'диабет', 'онко', 'антибиотик'),
    'external_action': ('зарегистрируй', 'зарегистрируйте', 'оплати', 'оплатите', 'оформи',
                        'закажи', 'внеси', 'сделай за меня', 'купи мне', 'отправь за'),
}

FLAG_ACTIONS: dict[str, str] = {
    'promo': 'Передать вопрос о текущих условиях наставнику',
    'guarantee': 'Не обещать доход, предложить уточнение у наставника',
    'medical': 'Не давать лечебных обещаний, передать вопрос человеку',
    'external_action': 'Не выполнять регистрацию и оплату, передать запрос наставнику',
}

# Ответы человеку: границы прототипа и запрет на выдуманные сведения (KB04, KB08).
FLAG_REPLIES: dict[str, str] = {
    'promo': 'Актуальных акций, цен и условий доставки в учебном наборе нет, выдумывать их не буду. Передам вопрос наставнику.',
    'guarantee': 'Гарантий дохода никто не даёт — этого не обещает и прототип. Условия обсуждаются с наставником.',
    'medical': 'О лечебных свойствах товаров говорить не буду: это вне моих правил. Вопрос передам наставнику.',
    'external_action': 'Регистрировать за вас и оплачивать заказы я не могу — это не входит в прототип. Передам запрос наставнику.',
}

BASE_ACTIONS: dict[str, str] = {
    'personal': 'Ознакомиться с материалами по интересующей категории',
    'income': 'Предложить вводную беседу с наставником',
    'business': 'Подготовить встречу о развитии группы',
    'unknown': 'Уточнить основную цель',
}

DUAL_GOAL_ACTION = 'Уточнить приоритет, сохранить оба интереса'
REFUSAL_ACTION = 'Остановить общение'

QUESTIONS: dict[str, str] = {
    'goal': 'Какая цель знакомства с возможностями для вас основная: покупать для себя, '
            'получать дополнительный доход или развивать бизнес?',
    'clarify': 'Вы назвали сразу несколько направлений. Что для вас главнее — покупка для себя, '
               'дополнительный доход или развитие бизнеса? Можно ответить «не знаю».',
    'interests': 'Что из ассортимента вам интересно: уход за домом, косметика и уход, парфюмерия, '
                 'декоративная косметика, витамины, одежда и обувь, детская линия?',
    'available_time': 'Сколько времени вы готовы уделять — например, два вечера в неделю?',
    'experience': 'Есть ли опыт работы с людьми: руководили группой, консультировали, ничего не было?',
}


@dataclass
class Analysis:
    """Результат разбора одной реплики человека."""
    text: str
    goals: tuple[str, ...] = ()
    segment: str = 'unknown'
    priority_given: bool = False
    refusal: bool = False
    flags: tuple[str, ...] = ()
    interests: tuple[str, ...] = ()
    matched: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


def _hits(text: str, patterns: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(pattern for pattern in patterns if pattern in text)


def analyse(raw_text: str) -> Analysis:
    """Сегмент, интересы и красные флаги по явному содержанию реплики."""
    text = (raw_text or '').strip().lower().replace('ё', 'е')
    if not text:
        return Analysis(text=raw_text or '')

    goals = tuple(name for name, signals in GOAL_SIGNALS.items() if _hits(text, signals))

    denial = bool(_hits(text, PRIORITY_DENIALS))
    marker = _hits(text, PRIORITY_MARKERS)
    priority_given = bool(marker) and not denial
    if len(goals) > 1 and priority_given:
        # Главная цель — та, о которой сказано после маркера приоритета.
        anchor = min(text.find(word) for word in marker)
        goals = _pick_after_marker(text, goals, anchor)

    if len(goals) == 1:
        segment = goals[0]
    else:
        segment = 'unknown'

    refusal = bool(_hits(text, REFUSAL_SIGNALS))
    flags = tuple(name for name, patterns in FLAG_SIGNALS.items() if _hits(text, patterns))
    if 'guarantee' in flags and not _hits(text, ('доход', 'заработ', 'тысяч', 'рубл', 'оклад',
                                                 'процент', 'прибыл', 'подработ', 'деньги')):
        flags = tuple(name for name in flags if name != 'guarantee')

    interests = tuple(name for name, signals in INTEREST_TOPICS.items() if _hits(text, signals))

    return Analysis(
        text=raw_text, goals=goals, segment=segment, priority_given=priority_given,
        refusal=refusal, flags=flags, interests=interests,
        matched=tuple(goals) + flags + interests,
    )


def _pick_after_marker(text: str, goals: tuple[str, ...], anchor: int) -> tuple[str, ...]:
    positions = {}
    for goal in goals:
        found = [text.find(signal) for signal in GOAL_SIGNALS[goal] if signal in text]
        after = [pos for pos in found if pos >= anchor]
        positions[goal] = min(after) if after else len(text) + 1
    best = min(goals, key=lambda goal: positions[goal])
    return (best,) if positions[best] < len(text) + 1 else goals


def next_question(profile: dict) -> str | None:
    """Политика диалога: какой вопрос задать следующим, не повторяя известное.

    None означает, что вопросов больше нет и пора показывать следующий шаг.
    """
    if profile.get('do_not_contact'):
        return None
    if not profile.get('goal_answer'):
        return QUESTIONS['goal']

    segment = profile.get('segment', 'unknown')
    if segment == 'unknown':
        # KB07: цель не определена или противоречива — одно уточнение, дальше
        # передача наставнику, а не угадывание.
        return None if profile.get('clarify_attempted') else QUESTIONS['clarify']

    if not profile.get('interests'):
        return QUESTIONS['interests']
    if segment == 'income' and not profile.get('available_time'):
        return QUESTIONS['available_time']
    if segment == 'business' and not profile.get('experience'):
        return QUESTIONS['experience']
    return None


def question_key(question_text: str) -> str:
    """Ключ вопроса по его тексту — чтобы хендлер знал, на какой шаг пришёл ответ."""
    for key, text in QUESTIONS.items():
        if text == question_text:
            return key
    return 'goal'


def goals_of(profile: dict) -> tuple[str, ...]:
    raw = profile.get('goals') or ''
    return tuple(item for item in raw.split(',') if item)


def next_action(profile: dict) -> str:
    """Один следующий шаг. Отказ важнее всего, затем красный флаг: он требует
    ответа человека, и маршрутом по цели это не перекрывается."""
    if profile.get('do_not_contact'):
        return REFUSAL_ACTION
    flag_actions = [FLAG_ACTIONS[flag] for flag in _profile_flags(profile) if flag in FLAG_ACTIONS]
    if flag_actions:
        return '; '.join(dict.fromkeys(flag_actions))
    segment = profile.get('segment', 'unknown')
    if segment == 'unknown' and len(goals_of(profile)) > 1:
        return DUAL_GOAL_ACTION
    return BASE_ACTIONS.get(segment, BASE_ACTIONS['unknown'])


def _profile_flags(profile: dict) -> tuple[str, ...]:
    raw = profile.get('flags') or ''
    return tuple(item for item in raw.split(',') if item)


def replies_for(profile: dict) -> list[str]:
    """Реплики человеку про красные флаги: без обещаний и выдуманных условий."""
    return [FLAG_REPLIES[flag] for flag in _profile_flags(profile) if flag in FLAG_REPLIES]


def missing_information(profile: dict) -> list[str]:
    missing = []
    segment = profile.get('segment', 'unknown')
    if segment == 'unknown':
        missing.append('основная цель знакомства')
    if not profile.get('interests'):
        missing.append('интересующие категории товаров')
    if segment == 'income' and not profile.get('available_time'):
        missing.append('сколько времени готов уделять')
    if segment == 'business' and not profile.get('experience'):
        missing.append('опыт работы с людьми')
    for flag in _profile_flags(profile):
        if flag in FLAG_ACTIONS:
            missing.append(f'нужен ответ наставника: {FLAG_ACTIONS[flag].lower()}')
    return missing


def draft_message(profile: dict, card: dict) -> str:
    """Черновик сообщения наставнику. Автоматическая отправка запрещена."""
    if card['do_not_contact']:
        return ''
    quote = (card['evidence'][0]['quote'] if card['evidence'] else '').strip()
    interests = ', '.join(card['interests']) or 'интересы не названы'
    opening = f'Вы упомянули: «{quote}».' if quote else 'Первичный диалог завершён.'
    if card['segment'] == 'income':
        ask = 'Удобно ли обсудить с наставником доступные варианты и условия?'
    elif card['segment'] == 'business':
        ask = 'Удобно ли обсудить формат встречи о развитии группы?'
    elif card['segment'] == 'personal':
        ask = 'Показать учебные материалы по интересующей категории?'
    else:
        ask = 'Помочь определится с целью на короткой встрече?'
    return f'{opening} Интересы: {interests}. {ask}'


def build_card(client: dict, quotes: list[str] | None = None) -> dict:
    """Карточка клиента в формате output_example.json."""
    evidence_source = client.get('evidence_source') or f'registration_events.json:{client.get("client_id")}'
    collected = quotes or [
        item for item in (client.get('goal_answer'), client.get('clarify_answer')) if item
    ]
    card = {
        'synthetic': True,
        'client_id': client.get('client_id'),
        'segment': client.get('segment') or 'unknown',
        'evidence': [{'source': evidence_source, 'quote': quote} for quote in collected if quote],
        'interests': split_values(client.get('interests')),
        'missing_information': missing_information(client),
        'do_not_contact': bool(client.get('do_not_contact')),
        'next_action': next_action(client),
        'requires_human_approval': True,
    }
    card['draft_message'] = draft_message(client, card)
    return card


def split_values(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [item.strip() for item in raw if item and item.strip()]
    return [item.strip() for item in str(raw).split(',') if item.strip()]


def apply_answer(profile: dict, text: str, step: str) -> dict:
    """Обновляет профиль клиента по ответу на текущем шаге диалога.

    Профиль — плоский dict, чтобы его можно было и сохранить в БД, и разобрать
    движком без состояния.
    """
    result = dict(profile)
    analysis = analyse(text)

    if analysis.refusal:
        # Отказ важнее прочих выводов (KB06), но слова человека остаются
        # доказательством в карточке: цитата идёт в evidence.
        result['do_not_contact'] = True
        result['goal_answer'] = text
        result['last_quote'] = text
        return result

    if step == 'goal':
        result['goal_answer'] = text
        result['goals'] = ','.join(analysis.goals)
        result['segment'] = analysis.segment
        result['clarify_attempted'] = False
        result.setdefault('interests', '')
        result['last_quote'] = text
        if analysis.interests:
            result['interests'] = ','.join(sorted(set(split_values(result.get('interests'))) | set(analysis.interests)))
    elif step == 'clarify':
        chosen = analysis.segment if analysis.segment != 'unknown' else result.get('segment', 'unknown')
        result['segment'] = chosen
        result['clarify_answer'] = text
        result['clarify_attempted'] = True
        result['last_quote'] = text
        if analysis.goals:
            result['goals'] = ','.join(analysis.goals)
    elif step == 'interests':
        merged = set(split_values(result.get('interests'))) | set(analysis.interests)
        if not analysis.interests and text.strip():
            merged.add(text.strip()[:80])
        result['interests'] = ','.join(sorted(item for item in merged if item))
        result['last_quote'] = text
    elif step == 'available_time':
        result['available_time'] = text.strip()[:120]
        result['last_quote'] = text
    elif step == 'experience':
        result['experience'] = text.strip()[:120]
        result['last_quote'] = text
    else:
        result['last_quote'] = text

    result['flags'] = ','.join(sorted(set(_profile_flags(result)) | set(analysis.flags)))
    return result
