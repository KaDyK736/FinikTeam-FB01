"""Текстовые карточки: клиенту — его анкета, наставнику — сводка без личных данных."""
from assistant import engine
from common.edit_fields import EDIT_LABELS
from database.repository import profile_of
from utils.validators import mask_phone

SITE_LABELS = (
    ('site_city', 'Населённый пункт'),
    ('site_last_name', 'Фамилия'),
    ('site_first_name', 'Имя'),
    ('site_middle_name', 'Отчество'),
    ('site_gender', 'Пол'),
    ('site_email', 'E-mail'),
    ('site_phone', 'Мобильный телефон'),
    ('site_birth_date', 'Дата рождения'),
    ('site_referrer_phone', 'Телефон пригласившего'),
)


def _value(client, key: str) -> str:
    return getattr(client, key) or '—'


def card_of(client) -> dict:
    """Карточка клиента в формате output_example.json.

    Подтверждением служат последние явные формулировки цели: они и лежат в
    goal_answer / clarify_answer, а вся история остаётся в dialogue_turn.
    """
    return engine.build_card(profile_of(client))


def site_block(client, *, mask: bool) -> list[str]:
    lines = []
    for key, label in SITE_LABELS:
        value = _value(client, key)
        if key == 'site_phone' and mask:
            value = mask_phone(client.site_phone) if client.site_phone else '—'
        lines.append(f'{label}: {value}')
    return lines


def bot_block(client) -> list[str]:
    profile = profile_of(client)
    lines = []
    for key in ('goal', 'interests', 'available_time', 'experience', 'do_not_contact'):
        label = EDIT_LABELS[key]
        value = profile.get(key)
        if key == 'goal':
            value = profile.get('goal_answer')
        if key == 'do_not_contact':
            value = 'не писать' if value else 'писать можно'
        lines.append(f'{label}: {value or "—"}')
    return lines


def client_card_text(client) -> str:
    lines = ['<b>Моя анкета</b>', '<b>Данные формы регистрации</b> (их меняет сайт):']
    lines += [f'· {line}' for line in site_block(client, mask=False)]
    lines.append('')
    lines.append('<b>Параметры из диалога</b> — их можно изменить кнопкой «Изменить анкету»:')
    lines += [f'· {line}' for line in bot_block(client)]
    card = card_of(client)
    lines += [
        '',
        f'<b>Сегмент цели:</b> {engine.SEGMENTS.get(card["segment"], card["segment"])}',
        f'<b>Следующий шаг:</b> {card["next_action"]}',
    ]
    if card['missing_information']:
        lines.append('<b>Не хватает:</b> ' + '; '.join(card['missing_information']))
    return '\n'.join(lines)


def mentor_card_text(client) -> str:
    """Сводка для наставника: телефон скрыт, вывод подтверждён цитатой."""
    card = card_of(client)
    name = client.display_name or 'без имени'
    lines = [f'<b>Карточка {client.client_id}</b> — {name}']
    lines.append(f'<b>Цель:</b> {engine.SEGMENTS.get(card["segment"], card["segment"])}')
    if card['evidence']:
        lines.append('<b>Что сказал человек:</b>')
        lines += [f'· «{item["quote"]}» ({item["source"]})' for item in card['evidence']]
    lines.append('<b>Интересы:</b> ' + (', '.join(card['interests']) or 'не названы'))
    lines.append('<b>Не хватает:</b> ' + ('; '.join(card['missing_information']) or 'нет'))
    lines.append(f'<b>Не беспокоить:</b> {"да" if card["do_not_contact"] else "нет"}')
    lines.append(f'<b>Следующий шаг:</b> {card["next_action"]}')
    lines.append(f'<b>Город:</b> {_value(client, "site_city")}')
    lines.append(f'<b>Телефон:</b> {mask_phone(client.site_phone)}')
    return '\n'.join(lines)


def draft_text(client) -> str:
    card = card_of(client)
    draft = card['draft_message']
    if not draft:
        return (f'{client.client_id}: человек попросил не писать ему. '
                'Черновик не готовится, повторное сообщение не предлагается (KB06).')
    return (f'<b>Черновик сообщения</b> — отправляет человек, автоматической отправки нет:\n'
            f'{draft}\n\n<i>requires_human_approval: true</i>')
