"""Заглушка выгрузки с сайта Faberlic.

В реальном контуре сайт сам передаёт анкету регистрации в бота. Доступа к сайту
нет, поэтому выгрузка смоделирована списком ниже: поля ровно те, что человек
заполняет на форме (населённый пункт, ФИО, пол, e-mail, мобильный телефон,
дата рождения, номер пригласившего, согласия).

Ключ сверки — нормализованный телефон. Ключевые идентификаторы кейса (client_id
F001..F010) к телефонам не привязаны: учебные события телефонов не содержат,
поэтому телефон позволяет найти уже созданную карточку, а не заводить вторую.

ВСЕ ЗАПИСИ ВЫМЫШЛЕНЫ. Свой настоящий номер для проверки сверки кладите в `.env`
(`MENTOR_PHONE`), а не в этот файл: кейс запрещает публиковать реальные
персональные данные.
"""
from utils.validators import normalize_phone

# (телефон, фамилия, имя, отчество, пол, e-mail, город, дата рождения, телефон пригласившего, согласия)
SITE_PROFILES: tuple[dict, ...] = (
    {
        'phone': '+79990000004',
        'last_name': 'Зайцева', 'first_name': 'Мария', 'middle_name': '',
        'gender': 'ж', 'email': 'm.zaytseva@example.test',
        'city': 'Волгоград', 'birth_date': '', 'referrer_phone': '',
        'consent': True,
    },
    {
        'phone': '+79990000001',
        'last_name': 'Смирнова', 'first_name': 'Анна', 'middle_name': 'Павловна',
        'gender': 'ж', 'email': 'a.smirnova@example.test',
        'city': 'Москва', 'birth_date': '1990-04-12', 'referrer_phone': '+79990000009',
        'consent': True,
    },
    {
        'phone': '+79990000002',
        'last_name': 'Кузнецов', 'first_name': 'Пётр', 'middle_name': 'Игоревич',
        'gender': 'м', 'email': 'p.kuznetsov@example.test',
        'city': 'Волгоград', 'birth_date': '1985-11-02', 'referrer_phone': '',
        'consent': True,
    },
    {
        'phone': '+79990000003',
        'last_name': 'Орлова', 'first_name': 'Мария', 'middle_name': 'Сергеевна',
        'gender': 'ж', 'email': 'm.orlova@example.test',
        'city': 'Санкт-Петербург', 'birth_date': '1998-07-30', 'referrer_phone': '+79990000001',
        'consent': False,
    },
)


def find_site_profile(raw_phone: str) -> dict | None:
    phone = normalize_phone(raw_phone)
    if not phone:
        return None
    return next((item for item in SITE_PROFILES if item['phone'] == phone), None)


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
