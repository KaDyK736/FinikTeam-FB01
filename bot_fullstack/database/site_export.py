"""Заглушка выгрузки с сайта Faberlic.

В реальном контуре сайт сам передаёт анкету регистрации в бота. Доступа к сайту
нет, поэтому из всей анкеты смоделированы те поля, без которых карточка не
работает: номер телефона (он же ключ сверки) и согласие на обращения. ФИО, город,
пол, e-mail, дата рождения и телефон пригласившего из карточки убраны — на
сегмент, вопросы диалога и следующий шаг они не влияют.

Ключевые идентификаторы кейса (client_id F001..F010) привязаны к телефонам здесь
же: карточка человека, чьего номера в этом списке нет, не заводится — сверка
только находит существующую запись и не плодит дубли.

ВСЕ ЗАПИСИ ВЫМЫШЛЕНЫ. Свой настоящий номер кладите в `.env` (`DEMO_PHONE`),
а не в этот файл: кейс запрещает публиковать реальные персональные данные.
"""
import os

from utils.validators import normalize_phone

# Ссылка регистрации для тех, кого ещё нет в выгрузке анкет сайта. Номер
# пригласившего — публичная часть ссылки, её можно менять через .env
# (`REGISTER_URL`), если стенд показывают от другого аккаунта.
REGISTER_URL = os.getenv(
    'REGISTER_URL', 'https://faberlic.com/ru/ru?sponsornumber=714059875',
)


def register_url() -> str:
    return REGISTER_URL

# (идентификатор карточки, телефон формы регистрации, согласие на обращения)
# Номера вымышленные. У F001 здесь заглушка: настоящий номер владельца стенда
# подставляет `case_seed` из `.env` (`DEMO_PHONE`), поэтому в коде он не лежит.
CASE_FORMS: tuple[dict, ...] = (
    {'client_id': 'F001', 'phone': '+79000000001', 'consent': True},
    {'client_id': 'F002', 'phone': '+79134862057', 'consent': True},
    {'client_id': 'F003', 'phone': '+79214750918', 'consent': True},
    {'client_id': 'F004', 'phone': '+79052384617', 'consent': True},
    {'client_id': 'F005', 'phone': '+79631470258', 'consent': True},
    {'client_id': 'F006', 'phone': '+79164802573', 'consent': True},
    {'client_id': 'F007', 'phone': '+79775361742', 'consent': True},
    {'client_id': 'F008', 'phone': '+79038461257', 'consent': True},
    {'client_id': 'F009', 'phone': '+79625738149', 'consent': True},
    {'client_id': 'F010', 'phone': '+79116048273', 'consent': True},
)


def case_form(client_id: str) -> dict | None:
    return next((item for item in CASE_FORMS
                 if item['client_id'] == (client_id or '').strip().upper()), None)


# Наставники: доступ к карточкам даётся по номеру телефона, а не по telegram_id.
# Здесь только вымышленные учебные номера. Свой настоящий номер кладите в .env
# (MENTOR_PHONE=+7...) — файл не попадает ни в репозиторий, ни в архив кейса.
MENTOR_PROFILES: tuple[dict, ...] = (
    {'name': 'Учебный наставник 1', 'phone': '+79990000009'},
    {'name': 'Учебный наставник 2', 'phone': '+79990000010'},
    {'name': 'Наставник Волноваха', 'phone': '+79990000011'},
)


def mentor_profiles_from_env(raw: str = '') -> tuple[dict, ...]:
    """Наставники из MENTOR_PHONE: реальный номер не попадает в код и в архив."""
    numbers = [item for item in raw.replace(';', ',').split(',') if item.strip()]
    result = []
    for index, item in enumerate(numbers, start=1):
        phone = normalize_phone(item)
        if phone:
            result.append({'name': f'Наставник из .env {index}', 'phone': phone})
    return tuple(result)
