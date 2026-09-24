"""Reply-клавиатуры: кнопка телефона и главное меню клиента."""
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.utils.keyboard import ReplyKeyboardBuilder

MENU = {
    'dialog': 'Продолжить диалог',
    'card': 'Моя анкета',
    'edit': 'Изменить анкету',
    'phone': 'Сверить телефон',
    'questions': 'Вопрос наставнику',
}

CONTACT_BUTTON = 'Отправить номер из Telegram'


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
    builder.button(text=MENU['dialog'])
    builder.button(text=MENU['card'])
    builder.button(text=MENU['edit'])
    builder.button(text=MENU['questions'])
    if with_phone:
        builder.button(text=MENU['phone'])
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)


def hide_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def cancel_row() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text='/cancel')
    return builder.as_markup(resize_keyboard=True)
