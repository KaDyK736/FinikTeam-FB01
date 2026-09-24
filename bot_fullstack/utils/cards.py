"""Текстовые карточки: клиенту — его анкета, наставнику — сводка без личных данных."""
from assistant import engine
from common.edit_fields import EDIT_LABELS
from database.repository import profile_of
from utils.validators import mask_phone


def title_of(client) -> str:
    """Заголовок карточки: идентификатор из файла кейса виден, служебный — нет."""
    if (client.source or '').startswith('учебное'):
        return client.client_id
    return client.display_name or 'карточка из диалога'


def is_case_card(client) -> bool:
    return (client.source or '').startswith('учебное')


def card_of(client) -> dict:
    """Карточка клиента в формате output_example.json.

    Подтверждением служат последние явные формулировки цели: они и лежат в
    goal_answer / clarify_answer, а вся история остаётся в dialogue_turn.
    """
    return engine.build_card(profile_of(client))


def phone_line(client, *, mask: bool) -> str:
    phone = client.site_phone or '—'
    return f'Телефон: {mask_phone(phone)}' if mask else f'Телефон: {phone}'


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
    lines = ['<b>Моя анкета</b>', phone_line(client, mask=False), '']
    lines.append('<b>Параметры из диалога</b> — их можно изменить кнопкой «Изменить анкету»:')
    lines += [f'· {line}' for line in bot_block(client)]
    card = card_of(client)
    lines += [
        '',
        f'<b>Сегмент цели:</b> {engine.SEGMENTS.get(card["segment"], card["segment"])}',
        f'<b>Роль:</b> {engine.ROLE_LABELS[card["role"]]}',
        f'<b>Следующий шаг:</b> {card["next_action"]}',
        contact_line(client),
    ]
    if card['missing_information']:
        lines.append('<b>Не хватает:</b> ' + '; '.join(card['missing_information']))
    return '\n'.join(lines)


def contact_line(client) -> str:
    """Статус связи: видно и наставнику, и самому человеку."""
    if client.do_not_contact:
        return '<b>Связь:</b> человек попросил не писать ему — связи нет (KB06)'
    if client.contact_offered_at:
        return (f'<b>Связь:</b> наставник {client.contact_offered_by} готов помочь '
                f'({client.contact_offered_at})')
    return '<b>Связь:</b> наставник ещё не выходил'


def mentor_card_text(client) -> str:
    """Сводка для наставника: телефон скрыт, вывод подтверждён цитатой."""
    card = card_of(client)
    title = f'<b>Карточка {title_of(client)}</b>'
    if client.display_name and title_of(client) != client.display_name:
        title += f' — {client.display_name}'
    lines = [title]
    lines.append(f'<b>Цель:</b> {engine.SEGMENTS.get(card["segment"], card["segment"])}')
    lines.append(f'<b>Роль:</b> {engine.ROLE_LABELS[card["role"]]}')
    if card['evidence']:
        lines.append('<b>Что сказал человек:</b>')
        lines += [f'· «{item["quote"]}»' for item in card['evidence']]
    lines.append('<b>Интересы:</b> ' + (', '.join(card['interests']) or 'не названы'))
    lines.append('<b>Не хватает:</b> ' + ('; '.join(card['missing_information']) or 'нет'))
    lines.append(f'<b>Не беспокоить:</b> {"да" if card["do_not_contact"] else "нет"}')
    lines.append(f'<b>Следующий шаг:</b> {card["next_action"]}')
    lines.append(contact_line(client))
    lines.append(phone_line(client, mask=True))
    return '\n'.join(lines)


def draft_text(client) -> str:
    card = card_of(client)
    draft = card['draft_message']
    if not draft:
        return (f'{title_of(client)}: человек попросил не писать ему. '
                'Черновик не готовится, повторное сообщение не предлагается (KB06).')
    return (f'<b>Черновик сообщения</b> — отправляет человек, автоматической отправки нет:\n'
            f'{draft}\n\n<i>Отправку подтверждает наставник.</i>')
