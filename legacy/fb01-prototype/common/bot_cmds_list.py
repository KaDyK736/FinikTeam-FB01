from aiogram.types import BotCommand

private = [
    BotCommand(command="start", description="Начать диалог или взять учебное событие (/start F002)"),
    BotCommand(command="card", description="Карточка: моя или клиента (/card F002)"),
    BotCommand(command="new", description="Очистить мой диалог и начать заново"),
    BotCommand(command="clients", description="Наставнику: все карточки"),
    BotCommand(command="dialog", description="Наставнику: о чём говорили (/dialog F002)"),
    BotCommand(command="unknown", description="Наставнику: у кого цель не определена"),
]
