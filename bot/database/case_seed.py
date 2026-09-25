"""Учебные карточки кейса: реплики человека из tests.json + номер из формы сайта.

Доступа к сайту Faberlic нет, поэтому набор карточек F001..F010 собирается здесь
из двух источников:
- 02_Учебные_данные/tests.json — что сказал человек (поле input);
- database/site_export.py — номер телефона формы регистрации и согласие.

Остальные поля анкеты (ФИО, город, пол, e-mail, дата рождения, телефон
пригласившего) в карточку не кладутся: сегмент, вопросы и следующий шаг они не
меняют, а первичному диалогу они не нужны.

Ожидаемые ответы из tests.json (expected_segment, expected_next_action) сюда не
читаются: сегмент, интересы и отказ по-прежнему выводит движок assistant/engine.py
из текста реплики. Иначе проверка превратилась бы в переписывание ответа.

Карточка живого демо (F001) первой реплики не получает — её заполняет диалог в
Telegram, иначе показать первичный диалог с нуля не получится.

Настоящий номер телефона одного клиента берётся из .env (`DEMO_PHONE`, а если он
не задан — из `MENTOR_PHONE`) и в код не попадает: кейс запрещает публиковать
реальные персональные данные. Остальные номера вымышленные.
"""
import os

from assistant import knowledge
from database.site_export import case_form
from utils.validators import normalize_phone

# Карточка, которой принадлежит настоящий номер пользователя из .env.
DEMO_CLIENT_ID = 'F001'
SOURCE_LABEL = 'учебное событие'

# Карточка живого демо сидится пустой: у неё есть только идентификатор, номер и
# согласие — цель, интересы и флаги появляются из ответов в Telegram. Остальные
# девять несут initial_message из registration_events.json: так их присылает сайт.
EMPTY_CARDS = (DEMO_CLIENT_ID,)


def my_phone() -> str | None:
    """Настоящий номер для демонстрации сверки — только из .env."""
    for name in ('DEMO_PHONE', 'MENTOR_PHONE'):
        raw = os.getenv(name, '')
        for item in raw.replace(';', ',').split(','):
            phone = normalize_phone(item)
            if phone:
                return phone
    return None


def events() -> list[dict]:
    """События регистрации для загрузчика БД в том же формате, что приходят с сайта."""
    real_phone = my_phone()
    result = []
    for item in knowledge.tests():
        client_id = item.get('client_id')
        if not client_id:
            # FB01-F011: объект без идентификатора — загрузчик обязан отклонить вход.
            continue
        form = dict(case_form(client_id) or {})
        if client_id == DEMO_CLIENT_ID and real_phone:
            form['phone'] = real_phone
        result.append({
            'client_id': client_id,
            'initial_message': '' if client_id in EMPTY_CARDS else item.get('input', ''),
            'source': SOURCE_LABEL,
            'registered_at': '2026-09-23T18:30:00+03:00',
            'site_form': form,
        })
    return result
