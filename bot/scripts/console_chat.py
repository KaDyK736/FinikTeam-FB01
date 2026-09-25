"""Тестовый интерфейс диалога в консоли.

Держатель кейса просит, чтобы общение с клиентом шло через мессенджер MAX.
Подключить MAX к прототипу сейчас нельзя, поэтому диалог сначала показывают
здесь — на том же движке правил и той же базе, что и в Telegram-боте.
План подключения к MAX описан в README.

Запуск:  python scripts/console_chat.py
Команды: /анкета, /правка цель <текст>, /черновик, /выход
"""
import asyncio
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DB_URL', f'sqlite+aiosqlite:///{(ROOT / "console_chat.db").as_posix()}')

for stream in (sys.stdout, sys.stdin):
    if hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding='utf-8')  # иначе cp1251 в консоли Windows ломает кириллицу

from assistant import engine  # noqa: E402
from common.edit_fields import ALIASES, BY_KEY, apply_edit, validate  # noqa: E402
from database.engine import close_db, init_db, session_maker  # noqa: E402
from database.repository import (  # noqa: E402
    orm_add_turn, orm_link_client_id, orm_link_phone, orm_save_answer, orm_store_profile,
    orm_update, profile_of,
)
from database.site_export import register_url  # noqa: E402
from utils.cards import title_of  # noqa: E402
from utils.validators import mask_phone, normalize_phone  # noqa: E402

CONSOLE_TG = 1  # условный чат консоли: один собеседник за запуск


def say(text: str) -> None:
    for tag in ('<b>', '</b>', '<i>', '</i>'):
        text = text.replace(tag, '')
    print(f'\n[помощник] {text}')


async def ask(session, client) -> str | None:
    profile = profile_of(client)
    question = engine.next_question(profile)
    if question is None:
        for reply in engine.replies_for(profile):
            say(reply)
        say('Для первичного диалога достаточно. Дальнейший шаг: '
            f'{engine.next_action(profile)}.')
        return None
    for reply in engine.replies_for(profile):
        say(reply)
    say(question)
    return engine.question_key(question)


async def show_card(session, client) -> None:
    from utils.cards import client_card_text

    say(client_card_text(client))


def offer_registration(phone: str = '') -> None:
    """Как в боте: номера нет в выгрузке сайта — карточку не заводим, даём ссылку."""
    if phone:
        say(f'Номера {phone} среди анкет, которые приходят с сайта, нет.')
    say(engine.REGISTRATION_OFFER.format(url=register_url()))


async def main() -> None:
    await init_db()
    async with session_maker() as session:
        client = None
        step = None
        say('Здравствуйте! В боте на этом месте кнопка «Начнем», а цель по бизнесу '
            'выбирается отдельными кнопками меню. Здесь просто сверим номер с анкетой '
            'с сайта — напишите его (или /выход).')
        while True:
            try:
                text = (input('\n[клиент] ')).strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not text:
                continue
            if text in ('/выход', 'exit'):
                break
            if text == '/анкета':
                if client is not None:
                    await show_card(session, client)
                continue
            if text == '/черновик':
                from utils.cards import draft_text

                say(draft_text(client) if client else 'Сначала сверим номер.')
                continue
            if text.startswith('/правка'):
                parts = text.split(maxsplit=2)
                if client is None or len(parts) < 3:
                    say('Формат: /правка цель <текст>. Доступно: ' + ', '.join(BY_KEY))
                    continue
                key = ALIASES.get(parts[1].lower(), parts[1].lower())
                value = parts[2]
                if key not in BY_KEY or validate(key, value) is None:
                    say('Такой правки нет или значение пустое. Ключи: ' + ', '.join(BY_KEY))
                    continue
                profile = apply_edit(profile_of(client), key, value)
                await orm_store_profile(session, client, profile)
                say(f'Изменил {BY_KEY[key].label}. Сегмент: '
                    f'{engine.SEGMENTS[profile["segment"]]}. Шаг: {engine.next_action(profile)}.')
                continue

            if client is None:
                client, status = await orm_link_phone(session, CONSOLE_TG, text)
                if status == 'mentor':
                    say('Этот номер в списке наставников: карточку клиента не завожу, '
                        'список карточек — в боте командой /cards.')
                    continue
                if status == 'not-found':
                    offer_registration(mask_phone(normalize_phone(text)))
                    continue
                if client is None:
                    found, by_id = await orm_link_client_id(session, CONSOLE_TG, text)
                    if by_id == 'found':
                        client = found
                    elif engine.mentions_registration(text):
                        offer_registration()
                        continue
                    else:
                        say(f'Не получилось: {status}. Напишите номер из регистрации '
                            'или идентификатор события (F002), либо /выход.')
                        continue
                say(f'Карточка {title_of(client)}, телефон {mask_phone(client.site_phone)}.')
                step = await ask(session, client)
                continue

            if engine.is_farewell(text):
                await orm_add_turn(session, client, 'user', text, step='farewell')
                await orm_update(session, client, dialogue_step='closed')
                say(engine.FAREWELL_REPLY)
                step = None
                continue

            if step is not None:
                profile = await orm_save_answer(session, client, text, step)
                await orm_update(session, client, dialogue_step=profile.get('dialogue_step'))
                step = await ask(session, client)
            else:
                say('Диалог закончен. Кнопки: /анкета, /правка цель <текст>, /черновик, /выход.')
    await close_db()


if __name__ == '__main__':
    asyncio.run(main())
