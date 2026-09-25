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
MENTOR_NAME = 'Наставник из .env 1'   # так подписан номер, пришедший из MENTOR_PHONE
os.environ['MENTOR_PHONE'] = MENTOR_PHONE
# Настоящий номер клиента подставляется из .env — в прогоне он вымышленный,
# чтобы тест не зависел от того, что лежит в .env, и не светил реальные данные.
os.environ['DEMO_PHONE'] = '+7 900 111-22-33'

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from aiogram import Bot
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.types import (  # noqa: E402
    CallbackQuery, Chat, Contact, Message, Update, User as TgUser,
)

from app import create_dispatcher  # noqa: E402
from assistant import engine  # noqa: E402
from database.engine import close_db, drop_db, init_db, session_maker  # noqa: E402
from database.repository import orm_count_clients, orm_get_client  # noqa: E402
from database.site_export import register_url  # noqa: E402
from kbds.inline import ContactCB, DraftCB, EditCB, FilterCB, MenuCB  # noqa: E402
from kbds.reply import MENU  # noqa: E402

REGISTER_URL = register_url()

# id в тесте всегда свои: иначе значения из .env делают клиента наставником
os.environ['ADMIN_TG_ID'] = str(ADMIN_TG)

CLIENT_TG = 5000000004          # условный чат клиента: номер карточки F003 из базы сайта
PHONE_TEXT = '8 (921) 475-09-18'
UNKNOWN_PHONE = '+7 999 000-11-22'   # такого номера в базе нет — карточка не заведётся
BUSINESS_PHONE = '8 (905) 238-46-17'  # карточка F004: цель ещё не названа
CASE_CLIENT_TG = 6000000005     # чат человека, чья карточка уже есть в файлах кейса (F002)

RESULTS: list[tuple[str, bool, str]] = []
_counter = 0


def check(name: str, ok: bool, detail: str = '') -> None:
    RESULTS.append((name, bool(ok), detail))


class RecordingSession(BaseSession):
    """Вместо сети складывает в себя вызовы методов бота."""

    def __init__(self):
        super().__init__()
        self.sent: list[tuple[int, str, object]] = []
        self.last_marks: list = []

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
        """Забирает тексты ответа и оставляет клавиатуры этого же ответа."""
        self.last_marks = [markup for _chat, _text, markup in self.sent if markup is not None]
        texts = [text for _chat, text, _markup in self.sent]
        self.sent.clear()
        return texts


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


def buttons(marks: list) -> list[str]:
    """Подписи всех inline-кнопок из собранных клавиатур."""
    return [button.text for markup in marks if hasattr(markup, 'inline_keyboard')
            for row in markup.inline_keyboard for button in row]


def link_urls(marks: list) -> list[str]:
    """Ссылки inline-кнопок: по ним проверяем кнопку регистрации."""
    return [button.url for markup in marks if hasattr(markup, 'inline_keyboard')
            for row in markup.inline_keyboard for button in row if button.url]


def menu(marks: list, row: int = 0) -> list[str]:
    """Подписи кнопок reply-клавиатуры: рядовый клавишный интерфейс клиента."""
    for markup in marks:
        if hasattr(markup, 'keyboard') and len(markup.keyboard) > row:
            return [button.text for button in markup.keyboard[row]]
    return []


def all_menu(marks: list) -> list[str]:
    return [button.text for markup in marks if hasattr(markup, 'keyboard')
            for row in markup.keyboard for button in row]


async def main() -> int:
    await drop_db()
    await init_db()
    bot = Bot('123456:TEST-TOKEN')
    session = RecordingSession()
    bot.session = session
    dp = create_dispatcher()

    # --- 0. Вход: /start — экран с кнопкой «Начнем» ---
    out = await send_text(bot, dp, session, '/start', CLIENT_TG)
    check('старт показывает кнопку «Начнем»',
          'Начнем' in all_menu(session.last_marks) and has(out, 'Нажмите «Начнем»'),
          out[0][:60] if out else '')
    check('на экране входа нет вопросов и анкетных кнопок',
          not any(word in out[0] for word in ('Моя анкета', 'Изменить анкету')), out[0][:60])

    # --- 1. Сверка телефона: карточка есть только у номера из базы сайта ---
    out = await send_text(bot, dp, session, MENU['start'], CLIENT_TG)
    check('кнопка «Начнем» просит номер', has(out, 'Сверю ваш номер'), out[-1][:60] if out else '')

    out = await send_text(bot, dp, session, '+7 999 00', CLIENT_TG)
    check('битый номер не создаёт карточку', has(out, 'Не смог распознать'), out[-1][:60] if out else '')
    async with session_maker() as s:
        check('после битого номера карточек не прибавилось',
              await orm_count_clients(s) == 10)

    out = await send_text(bot, dp, session, UNKNOWN_PHONE, CLIENT_TG)
    check('номера нет в базе — карточку не заводит',
          has(out, 'карточку не завожу') and has(out, '+7999 *** ** 22'),
          out[0][:70] if out else '')
    check('незарегистрированному дают ссылку на сайт',
          REGISTER_URL in link_urls(session.last_marks)
          and has(out, 'Зарегистрируйтесь по ссылке'), str(link_urls(session.last_marks))[:70])
    async with session_maker() as s:
        check('неизвестный номер не добавил карточку', await orm_count_clients(s) == 10)

    out = await press(bot, dp, session, MenuCB(action='phone').pack(), CLIENT_TG)
    check('кнопка «я зарегистрирован» снова просит номер',
          has(out, 'Сверю ваш номер'), out[-1][:60] if out else '')
    out = await send_text(bot, dp, session, 'Я ещё не зарегистрирован', CLIENT_TG)
    check('слова про регистрацию дают ссылку, а не карточку',
          REGISTER_URL in link_urls(session.last_marks), str(link_urls(session.last_marks))[:70])
    async with session_maker() as s:
        check('по словам о регистрации карточек не прибавилось',
              await orm_count_clients(s) == 10)

    out = await send_contact(bot, dp, session, PHONE_TEXT, CLIENT_TG)
    check('номер из базы нашёл карточку кейса', has(out, 'найдена в базе'),
          out[0][:70] if out else '')
    check('известное не переспрашивается: вопрос про опыт', has(out, 'Есть ли опыт работы'))

    # --- 2. Диалог: ответ про опыт завершает первичный цикл (KB02) ---
    out = await send_text(bot, dp, session, 'Руководила небольшой группой', CLIENT_TG)
    check('после ответов диалог завершён', has(out, 'для первичного диалога'),
          out[-1][:60] if out else '')

    out = await send_text(bot, dp, session, 'Моя анкета', CLIENT_TG)
    card_text = ' '.join(out)
    rows = [[button.text for button in row]
            for markup in session.last_marks if hasattr(markup, 'keyboard')
            for row in markup.keyboard]
    labels = [text for row in rows for text in row]
    check('меню клиента: анкета и диалог',
          {'Начать диалог', 'Моя анкета', 'Изменить анкету', 'Вопрос наставнику'} <= set(labels),
          str(labels)[:120])
    check('бизнес — отдельные кнопки того же меню',
          {'Бизнес: дополнительный доход', 'Бизнес: развивать свою группу'} <= set(labels),
          str(labels)[:120])
    check('бизнес-кнопки не смешиваются с анкетными в одном ряду',
          all(not any(text.startswith('Бизнес') for text in row)
              or all(text.startswith('Бизнес') for text in row) for row in rows),
          str(rows)[:120])
    check('анкета показывает телефон и шаг',
          has(out, 'Телефон') and has(out, 'Развитие бизнеса') and has(out, 'Следующий шаг'),
          out[-1][:60] if out else '')
    check('полей анкеты сайта в карточке больше нет',
          not any(word in card_text for word in
                  ('Фамилия', 'Имя', 'Отчество', 'Пол', 'E-mail', 'Населённый пункт',
                   'Дата рождения', 'Телефон пригласившего', 'Город')),
          card_text[:60])
    check('анкета без служебных идентификаторов и путей к файлам',
          not has(out, 'B' + str(CLIENT_TG)) and not has(out, '.json'), out[-1][:60] if out else '')

    # --- 2б. Прощание: вежливый конец диалога, карточка не портится ---
    out = await send_text(bot, dp, session, 'Спасибо, до свидания', CLIENT_TG)
    check('прощание закрывает диалог вежливо', has(out, 'Спасибо за общение') and has(out, 'завершён'),
          out[-1][:70] if out else '')
    async with session_maker() as s:
        client = await orm_get_client(s, 'F003')
        check('прощание не стало ответом на вопрос о цели',
              client.goal_answer == 'Хочу развивать команду, раньше руководил небольшой группой.'
              and client.dialogue_step == 'closed',
              f'{client.goal_answer} / {client.dialogue_step}')
    out = await send_text(bot, dp, session, 'Goodbye', CLIENT_TG)
    check('английское прощание тоже закрывает диалог', has(out, 'Спасибо за общение'))

    # --- 3. Правка параметра, которого нет на форме сайта ---
    out = await send_text(bot, dp, session, 'Изменить анкету', CLIENT_TG)
    check('меню правки предлагает диалоговые параметры', has(out, 'не заполняются на форме сайта'))
    out = await press(bot, dp, session, EditCB(key='goal').pack(), CLIENT_TG)
    check('кнопка правки цели задаёт вопрос', has(out, 'новую цель своими словами'), out[-1][:60] if out else '')
    out = await send_text(bot, dp, session, 'Хочу покупать для себя', CLIENT_TG)
    check('после правки сегмент пересчитан', has(out, 'Покупка для себя'), out[0][:70] if out else '')
    async with session_maker() as s:
        client = await orm_get_client(s, 'F003')
        check('история правки сохранена', client.segment == 'personal')
        check('новая формулировка встала в карточку', client.goal_answer == 'Хочу покупать для себя')

    # --- 4. Вопрос про акции: без выдуманных условий, шаг — наставнику ---
    out = await send_text(bot, dp, session, 'Какая скидка и сколько стоит доставка?', CLIENT_TG)
    check('условия не выдумываются', has(out, 'выдумывать их не буду'), out[-1][:70] if out else '')

    # --- 5. Отказ от общения ---
    out = await send_text(bot, dp, session, 'Не пишите мне больше', CLIENT_TG)
    check('отказ останавливает диалог', has(out, 'дальнейшие сообщения не приходят'),
          out[-1][:60] if out else '')
    async with session_maker() as s:
        client = await orm_get_client(s, 'F003')
        check('флаг do_not_contact сохранён', client.do_not_contact)
        from utils.cards import draft_text
        check('черновик наставнику не готовится', 'Черновик не готовится' in draft_text(client),
              draft_text(client)[:60])

    # --- 6. Наставник: доступ по номеру телефона, карточки, черновик ---
    out = await send_text(bot, dp, session, '/start', MENTOR_TG)
    check('экран входа наставника тоже ждёт «Начнем»', has(out, 'Нажмите «Начнем»'),
          out[0][:60] if out else '')
    out = await send_text(bot, dp, session, MENU['start'], MENTOR_TG)
    check('незнакомый номер просят прислать', has(out, 'Сверю ваш номер'), out[-1][:60] if out else '')

    out = await send_text(bot, dp, session, MENTOR_PHONE, MENTOR_TG)
    check('наставник опознан по номеру телефона', has(out, 'в списке наставников'),
          out[0][:70] if out else '')
    async with session_maker() as s:
        check('карточка клиента для наставника не заведена',
              await orm_count_clients(s) == 10)
    await send_text(bot, dp, session, '/start', MENTOR_TG)
    out = await send_text(bot, dp, session, MENU['start'], MENTOR_TG)
    check('повторный вход не просит номер заново', has(out, 'в списке наставников'),
          out[0][:70] if out else '')

    out = await send_text(bot, dp, session, '/cards', MENTOR_TG)
    check('наставник видит список карточек', has(out, 'Карточки новых клиентов'), out[-1][:60] if out else '')
    out = await send_text(bot, dp, session, '/card F002', MENTOR_TG)
    check('карточка подтверждена цитатой', has(out, 'Ищу дополнительный доход, могу уделять'))
    check('карточка без путей к файлам и служебных ключей',
          not has(out, 'tests.json') and not has(out, 'evidence'), out[-1][:60] if out else '')
    check('телефон наставнику скрыт',
          not any(phone in text for text in out
                  for phone in ('+79134862057', '+79214750918')))

    check('на карточке согласившегося есть кнопка связи',
          'Связаться с партнёром по бизнесу' in buttons(session.last_marks),
          str(buttons(session.last_marks))[:120])
    await send_text(bot, dp, session, '/card F006', MENTOR_TG)
    check('на карточке отказавшегося кнопки связи нет',
          not any('Связаться' in text for text in buttons(session.last_marks)))

    # --- 6б. Фильтр по роли: клиент или партнёр по бизнесу ---
    out = await send_text(bot, dp, session, '/cards клиенты', MENTOR_TG)
    labels = buttons(session.last_marks)
    check('список подписан активным фильтром', has(out, 'фильтр «Клиенты»'), out[0][:70] if out else '')
    check('фильтр по цели оставляет только покупателей для себя',
          {'F009 · Покупка для себя'} <= set(labels)
          and 'F002 · Дополнительный доход' not in labels, str(labels)[:120])
    out = await press(bot, dp, session, FilterCB(role='partner').pack(), MENTOR_TG)
    check('кнопка фильтра работает в списке', has(out, 'Партнёры по бизнесу'), out[-1][:70] if out else '')
    check('фильтр по роли показывает партнёров',
          'F002 · Дополнительный доход' in buttons(session.last_marks),
          str(buttons(session.last_marks))[:120])

    # --- 6в. Нажатие «связаться»: статус в карточке и сообщение человеку ---
    await send_text(bot, dp, session, '/start', CASE_CLIENT_TG)
    out = await send_text(bot, dp, session, '+7 913 486-20-57', CASE_CLIENT_TG)
    check('номер карточки кейса находит её, а не заводит вторую',
          has(out, 'найдена в базе') and not has(out, 'завёл карточку'), out[0][:70] if out else '')
    async with session_maker() as s:
        check('сверка человека из карточки кейса не добавила новую',
              await orm_count_clients(s) == 10)
    out = await press(bot, dp, session, ContactCB(client_id='F002').pack(), MENTOR_TG)
    check('человек получил сообщение, что наставник готов помочь',
          has(out, 'готов вам помочь') and has(out, MENTOR_NAME), out[-1][:70] if out else '')
    check('статус связи появился в карточке наставника', has(out, 'готов помочь'),
          out[0][:60] if out else '')
    async with session_maker() as s:
        f002 = await orm_get_client(s, 'F002')
        check('статус связи сохранён в базе',
              f002.contact_offered_at and f002.contact_offered_by == MENTOR_NAME,
              f'{f002.contact_offered_at} / {f002.contact_offered_by}')

    out = await press(bot, dp, session, DraftCB(client_id='F002').pack(), MENTOR_TG)
    check('черновик помечен как требующий подтверждения',
          has(out, 'подтверждает наставник') and has(out, 'автоматической'), out[-1][:60] if out else '')

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
    check('сводка по сегментам собрана', has(out, 'Карточек в базе: 10'), out[0][:60] if out else '')

    # --- 7б. Бизнес-кнопки: отдельный блок меню ведёт цель партнёра ---
    biz_tg = 6000000007
    await send_text(bot, dp, session, MENU['start'], biz_tg)
    out = await send_contact(bot, dp, session, BUSINESS_PHONE, biz_tg)
    check('карточка F004 нашлась по номеру из выгрузки', has(out, 'найдена в базе'),
          out[0][:70] if out else '')
    await send_text(bot, dp, session, '/cancel', biz_tg)
    out = await send_text(bot, dp, session, MENU['group'], biz_tg)
    check('бизнес-кнопка ставит цель развития группы', has(out, 'Развитие бизнеса'),
          out[0][:70] if out else '')
    check('роль после бизнес-кнопки — партнёр', has(out, 'Партнёры по бизнесу'),
          out[0][:70] if out else '')
    async with session_maker() as s:
        client = await orm_get_client(s, 'F004')
        check('бизнес-кнопка сохранена в карточке',
              client.segment == 'business'
              and client.goal_answer == engine.BUSINESS_GOALS['business'],
              f'{client.segment} / {client.goal_answer}')
    await send_text(bot, dp, session, '/cancel', biz_tg)
    out = await send_text(bot, dp, session, MENU['income'], biz_tg)
    check('кнопка дохода меняет цель на доход', has(out, 'Дополнительный доход'),
          out[0][:70] if out else '')

    # --- 8. Дублей нет: столько карточек, сколько номеров пришло с сайта ---

    async with session_maker() as s:
        total = await orm_count_clients(s)
    check('сверки и загрузки не множат карточки', total == 10, f'всего карточек: {total}')

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
