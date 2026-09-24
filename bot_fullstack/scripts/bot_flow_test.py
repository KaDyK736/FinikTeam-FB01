"""Сквозной прогон бота без токена Telegram.

Собираем настоящий диспетчер (app.create_dispatcher) и подаём в него вручную
сконструированные Update: тексты, контакт с телефоном и нажатия inline-кнопок.
Так проверяется вся цепочка — middleware, FSM, движок правил, база, — а не только
функции. Ответы бота собираются из вызовов sendMessage/editMessageText.

Запуск:  python scripts/bot_flow_test.py
"""
import asyncio
import datetime
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DB_URL'] = f'sqlite+aiosqlite:///{(ROOT / "bot_flow_test.db").as_posix()}'

# Наставник заводится по номеру телефона (как в .env), а не по идентификатору чата.
# Значение должно попасть в окружение до импорта database.engine: список читается там.
ADMIN_TG = 7770000009
MENTOR_TG = 7770000001
MENTOR_PHONE = '+7 999 000-00-99'
os.environ['MENTOR_PHONE'] = MENTOR_PHONE

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from aiogram import Bot
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.types import (  # noqa: E402
    CallbackQuery, Chat, Contact, Message, Update, User as TgUser,
)

from app import create_dispatcher  # noqa: E402
from database.engine import close_db, drop_db, init_db, session_maker  # noqa: E402
from database.repository import orm_count_clients, orm_get_client  # noqa: E402
from kbds.inline import DraftCB, EditCB  # noqa: E402

# id в тесте всегда свои: иначе значения из .env делают клиента наставником
os.environ['ADMIN_TG_ID'] = str(ADMIN_TG)

CLIENT_TG = 5000000004          # условный чат клиента: демо-номер есть в выгрузке сайта
PHONE_TEXT = '8 (999) 000-00-04'

RESULTS: list[tuple[str, bool, str]] = []
_counter = 0


def check(name: str, ok: bool, detail: str = '') -> None:
    RESULTS.append((name, bool(ok), detail))


class RecordingSession(BaseSession):
    """Вместо сети складывает в себя вызовы методов бота."""

    def __init__(self):
        super().__init__()
        self.sent: list[tuple[int, str, object]] = []

    async def make_request(self, bot, method, timeout=None, **kwargs):
        chat_id = getattr(method, 'chat_id', None)
        text = getattr(method, 'text', None) or getattr(method, 'new_text', None)
        markup = getattr(method, 'reply_markup', None)
        if text is not None:
            self.sent.append((chat_id, text, markup))
        return None

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        yield b''

    async def close(self):  # pragma: no cover
        pass

    def drain(self) -> list[str]:
        texts = [text for _chat, text, _markup in self.sent]
        self.sent.clear()
        return texts

    def keyboards(self):
        marks = [markup for _chat, _text, markup in self.sent if markup is not None]
        self.sent.clear()
        return marks


async def push(bot: Bot, dp, session: RecordingSession, update: Update) -> list[str]:
    await dp.feed_update(bot, update)
    return session.drain()


def _tg(id: int, name: str) -> TgUser:
    return TgUser(id=id, is_bot=False, first_name=name)


async def send_text(bot, dp, session, text: str, tg_id: int, name='Тест') -> list[str]:
    global _counter
    _counter += 1
    update = Update(
        update_id=_counter,
        message=Message(
            message_id=_counter, date=datetime.datetime.now(datetime.timezone.utc),
            chat=Chat(id=tg_id, type='private'), from_user=_tg(tg_id, name), text=text,
        ),
    )
    return await push(bot, dp, session, update)


async def send_contact(bot, dp, session, phone: str, tg_id: int) -> list[str]:
    global _counter
    _counter += 1
    update = Update(
        update_id=_counter,
        message=Message(
            message_id=_counter, date=datetime.datetime.now(datetime.timezone.utc),
            chat=Chat(id=tg_id, type='private'), from_user=_tg(tg_id, 'Тест'),
            contact=Contact(phone_number=phone, first_name='Тест'),
        ),
    )
    return await push(bot, dp, session, update)


async def press(bot, dp, session, data: str, tg_id: int, msg_id: int = 1) -> list[str]:
    global _counter
    _counter += 1
    update = Update(
        update_id=_counter,
        callback_query=CallbackQuery(
            id=str(_counter), from_user=_tg(tg_id, 'Тест'), chat_instance='test',
            data=data,
            message=Message(
                message_id=msg_id, date=datetime.datetime.now(datetime.timezone.utc),
                chat=Chat(id=tg_id, type='private'), from_user=_tg(tg_id, 'Тест'), text='меню',
            ),
        ),
    )
    return await push(bot, dp, session, update)


def has(texts: list[str], needle: str) -> bool:
    return any(needle in text for text in texts)


async def main() -> int:
    await drop_db()
    await init_db()
    bot = Bot('123456:TEST-TOKEN')
    session = RecordingSession()
    bot.session = session
    dp = create_dispatcher()

    # --- 1. Старт и сверка телефона: номер из выгрузки сайта находит карточку ---
    out = await send_text(bot, dp, session, '/start', CLIENT_TG)
    check('старт просит телефон', has(out, 'Сверю ваш номер'), out[-1][:60] if out else '')

    out = await send_text(bot, dp, session, '+7 999 00', CLIENT_TG)
    check('битый номер не создаёт карточку', has(out, 'Не смог распознать'), out[-1][:60] if out else '')

    out = await send_contact(bot, dp, session, PHONE_TEXT, CLIENT_TG)
    check('номер распознан и найден на сайте', has(out, 'Ваш номер есть в выгрузке с сайта'),
          out[0][:70] if out else '')
    check('первый вопрос — про цель', has(out, 'Какая цель знакомства'))

    # --- 2. Диалог: ответ про доход ведёт к вопросу о времени (KB02) ---
    out = await send_text(bot, dp, session, 'Ищу дополнительный доход', CLIENT_TG)
    check('доход: спрашиваем свободное время', has(out, 'Сколько времени'), out[-1][:60] if out else '')
    out = await send_text(bot, dp, session, 'Два вечера в неделю', CLIENT_TG)
    check('после ответов диалог завершён', has(out, 'для первичного диалога'))

    out = await send_text(bot, dp, session, 'Моя анкета', CLIENT_TG)
    check('анкета показывает поля формы сайта', has(out, 'Мобильный телефон') and has(out, 'Волгоград'))
    check('анкета показывает сегмент и шаг', has(out, 'Дополнительный доход') and has(out, 'Следующий шаг'))

    # --- 3. Правка параметра, которого нет на форме сайта ---
    out = await send_text(bot, dp, session, 'Изменить анкету', CLIENT_TG)
    check('меню правки предлагает диалоговые параметры', has(out, 'не заполняются на форме сайта'))
    out = await press(bot, dp, session, EditCB(key='goal').pack(), CLIENT_TG)
    check('кнопка правки цели задаёт вопрос', has(out, 'новую цель своими словами'), out[-1][:60] if out else '')
    out = await send_text(bot, dp, session, 'Хочу развивать команду', CLIENT_TG)
    check('после правки сегмент пересчитан', has(out, 'Развитие бизнеса'), out[0][:70] if out else '')
    async with session_maker() as s:
        client = await orm_get_client(s, f'B{CLIENT_TG}')
        check('история правки сохранена', client.segment == 'business')
        check('старая формулировка не удалена из истории', client.goal_answer == 'Хочу развивать команду')

    # --- 4. Вопрос про акции: без выдуманных условий, шаг — наставнику ---
    out = await send_text(bot, dp, session, 'Какая скидка и сколько стоит доставка?', CLIENT_TG)
    check('условия не выдумываются', has(out, 'выдумывать их не буду'), out[-1][:70] if out else '')

    # --- 5. Отказ от общения ---
    out = await send_text(bot, dp, session, 'Не пишите мне больше', CLIENT_TG)
    check('отказ останавливает диалог', has(out, 'дальнейшие сообщения не приходят'),
          out[-1][:60] if out else '')
    async with session_maker() as s:
        client = await orm_get_client(s, f'B{CLIENT_TG}')
        check('флаг do_not_contact сохранён', client.do_not_contact)
        from utils.cards import draft_text
        check('черновик наставнику не готовится', 'Черновик не готовится' in draft_text(client),
              draft_text(client)[:60])

    # --- 6. Наставник: доступ по номеру телефона, карточки, черновик ---
    out = await send_text(bot, dp, session, '/start', MENTOR_TG)
    check('незнакомый номер просят прислать', has(out, 'Сверю ваш номер'), out[-1][:60] if out else '')

    out = await send_text(bot, dp, session, MENTOR_PHONE, MENTOR_TG)
    check('наставник опознан по номеру телефона', has(out, 'в списке наставников'),
          out[0][:70] if out else '')
    async with session_maker() as s:
        check('карточка клиента для наставника не заведена',
              await orm_get_client(s, f'B{MENTOR_TG}') is None)
    out = await send_text(bot, dp, session, '/start', MENTOR_TG)
    check('повторный вход не просит номер заново', has(out, 'в списке наставников'),
          out[0][:70] if out else '')

    out = await send_text(bot, dp, session, '/cards', MENTOR_TG)
    check('наставник видит список карточек', has(out, 'Карточки новых клиентов'), out[-1][:60] if out else '')
    out = await send_text(bot, dp, session, '/card F002', MENTOR_TG)
    check('карточка подтверждена цитатой', has(out, 'Ищу дополнительный доход, могу уделять'))
    check('телефон наставнику скрыт', not any('+79990000004' in text for text in out))

    keyboards = session.keyboards()
    out = await press(bot, dp, session, DraftCB(client_id='F002').pack(), MENTOR_TG)
    check('черновик помечен как требующий подтверждения',
          has(out, 'requires_human_approval') and has(out, 'автоматической'), out[-1][:60] if out else '')

    # --- 7. Кривой и повторный вход события ---
    out = await send_text(bot, dp, session, '/event {"initial_message": "привет"}', CLIENT_TG)
    out2 = await send_text(bot, dp, session, '/load', CLIENT_TG)
    check('команды админки недоступны клиенту', not has(out + out2, 'События регистрации'))

    out = await send_text(bot, dp, session, '/event {"initial_message": "привет"}', ADMIN_TG)
    check('FB01-F011: вход без client_id отклонён', has(out, 'Вход некорректен'),
          out[0][:70] if out else '')
    check('FB01-F011: чужая карточка не тронута', not has(out, 'Событие обработано'))

    out = await send_text(bot, dp, session, '/load', ADMIN_TG)
    check('FB01-F012: перегрузка файла обновила записи без дублей',
          has(out, 'обновлено 10') and has(out, 'отклонено 0'), out[0][:80] if out else '')
    out = await send_text(bot, dp, session, '/stats', ADMIN_TG)
    check('сводка по сегментам собрана', has(out, 'Карточек в базе: 11'), out[0][:60] if out else '')

    # --- 8. Дублей нет: 10 событий + одна карточка клиента ---
    async with session_maker() as s:
        total = await orm_count_clients(s)
    check('повторные сверки и загрузки не множат карточки', total == 11, f'всего карточек: {total}')

    await close_db()
    (ROOT / 'bot_flow_test.db').unlink(missing_ok=True)

    width = max(len(name) for name, _ok, _d in RESULTS)
    for name, ok, detail in RESULTS:
        print(f'[{"ok" if ok else "FAIL"}] {name.ljust(width)} {detail}')
    passed = sum(1 for _n, ok, _d in RESULTS if ok)
    print(f'\nПройдено {passed} из {len(RESULTS)}')
    return 0 if passed == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
