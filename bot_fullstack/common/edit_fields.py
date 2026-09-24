"""Параметры анкеты, которых нет на форме регистрации сайта.

На форме Faberlic человек заполняет населённый пункт, ФИО, пол, e-mail, мобильный
телефон, дату рождения и телефон пригласившего. Цель знакомства, интересы,
доступное время, опыт и согласие на общение там не спрашивают — их собирает
первичный диалог, и их же можно изменить в боте по кнопке «Изменить анкету».
"""
from dataclasses import dataclass

from assistant import engine
from utils.validators import validate_free_text

DENY_CONTACT = 'Не писать мне'
ALLOW_CONTACT = 'Писать можно'


@dataclass(frozen=True)
class EditField:
    key: str          # колонка карточки
    label: str        # показывает человек в меню и в истории
    question: str     # вопрос при правке
    choices: tuple[str, ...] = ()
    max_len: int = 160


EDIT_FIELDS: tuple[EditField, ...] = (
    EditField(
        key='goal', label='Основная цель знакомства',
        question='Напишите новую цель своими словами: покупать для себя, получать доход, '
                 'развивать бизнес или пока не определился.',
    ),
    EditField(
        key='interests', label='Интересующие категории товаров',
        question='Перечислите интересующие категории: уход за домом, косметика и уход, '
                 'парфюмерия, декоративная косметика, витамины, одежда и обувь, детская линия.',
    ),
    EditField(
        key='available_time', label='Сколько времени готовы уделять',
        question='Напишите, сколько времени готовы уделять, например: два вечера в неделю.',
    ),
    EditField(
        key='experience', label='Опыт работы с людьми',
        question='Опишите опыт работы с людьми: руководили группой, консультировали или опыта нет.',
    ),
    EditField(
        key='do_not_contact', label='Согласие на обращения',
        question='Разрешить ли обращения к вам?',
        choices=(ALLOW_CONTACT, DENY_CONTACT),
    ),
)

BY_KEY: dict[str, EditField] = {field.key: field for field in EDIT_FIELDS}
# Русские имена ключей — для консольного интерфейса, где нет кнопок.
ALIASES: dict[str, str] = {
    'цель': 'goal', 'цели': 'goal', 'интересы': 'interests', 'время': 'available_time',
    'опыт': 'experience', 'контакт': 'do_not_contact', 'согласие': 'do_not_contact',
}
EDIT_LABELS: dict[str, str] = {field.key: field.label for field in EDIT_FIELDS}


def validate(key: str, raw: str) -> str | None:
    field = BY_KEY.get(key)
    if field is None:
        return None
    text = (raw or '').strip()
    if field.choices:
        return text if text in field.choices else None
    return validate_free_text(text, min_len=2, max_len=field.max_len)


def apply_edit(profile: dict, key: str, text: str) -> dict:
    """Применяет правку и пересчитывает производные поля карточки."""
    result = dict(profile)
    if key == 'goal':
        return engine.apply_answer(result, text, 'goal')
    if key == 'interests':
        named = {item.strip().lower() for item in text.split(',') if item.strip()}
        topics = set(engine.analyse(text).interests)
        free = {item for item in named
                if item not in topics and len(item) > 2
                and not any(item in topic or topic in item for topic in topics)}
        result['interests'] = ','.join(sorted(topics | free))
        return result
    if key in ('available_time', 'experience'):
        result[key] = text[:BY_KEY[key].max_len]
        return result
    if key == 'do_not_contact':
        result['do_not_contact'] = text == DENY_CONTACT
        if not result['do_not_contact'] and result.get('dialogue_step') == 'stopped':
            result['dialogue_step'] = None
        return result
    return result
