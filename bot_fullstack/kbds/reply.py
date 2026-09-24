"""Reply-клавиатуры: кнопка входа «Начнем», кнопка телефона и меню клиента.

Меню разведено на два блока: анкета (диалог, карточка, правка, вопрос наставнику)
и бизнес — то, что касается партнёрства и дохода, идёт отдельными кнопками внизу.
"""
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.utils.keyboard import ReplyKeyboardBuilder

MENU = {
    'start': 'Начнем',
    'dialog': 'Начать диалог',
    'card': 'Моя анкета',
    'edit': 'Изменить анкету',
    'questions': 'Вопрос наставнику',
    'phone': 'Сверить телефон',
    'income': 'Бизнес: дополнительный доход',
    'group': 'Бизнес: развивать свою группу',
}

# Всё, что касается партнёрства, — отдельным блоком в конце клавиатуры.
BUSINESS_BUTTONS = (MENU['income'], MENU['group'])
CLIENT_BUTTONS = (MENU['dialog'], MENU['card'], MENU['edit'], MENU['questions'])

CONTACT_BUTTON = 'Отправить номер из Telegram'

# Бизнес-кнопки ведут в движок по ключу цели: формулировку ответа знает engine,
# подписи кнопок — здесь.
BUSINESS_MENU = {
    MENU['income']: 'income',
    MENU['group']: 'business',
}


def start_keyboard() -> ReplyKeyboardMarkup:
    """Одна кнопка «Начнем» — делает то же, что /start, но текстом на русском."""
    builder = ReplyKeyboardBuilder()
    builder.button(text=MENU['start'])
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def contact_keyboard() -> ReplyKeyboardMarkup:
    """Номер можно отправить и текстом; кнопка нужна, чтобы ввод не искажался."""
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text=CONTACT_BUTTON, request_contact=True))
    builder.adjust(1)
    return builder.as_markup(
        resize_keyboard=True, input_field_placeholder='или напишите номер текстом',
    )


def client_menu(with_phone: bool = True) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    for text in CLIENT_BUTTONS:
        builder.button(text=text)
    if with_phone:
        builder.button(text=MENU['phone'])
    builder.adjust(2)
    business = ReplyKeyboardBuilder()
    for text in BUSINESS_BUTTONS:
        business.button(text=text)
    business.adjust(1)
    markup = builder.as_markup(resize_keyboard=True, one_time_keyboard=False)
    # Отдельный блок: кнопки про партнёрство идут ниже анкетных и не смешиваются с ними.
    markup.keyboard.extend(business.export())
    return markup


def hide_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def cancel_row() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text='/cancel')
    return builder.as_markup(resize_keyboard=True)
