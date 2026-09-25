import re

PHONE_DIGITS = re.compile(r'\D')
NAME_RE = re.compile(r'^[А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z\s\-.]{1,49}$')
NICK_RE = re.compile(r'^@?([A-Za-z][A-Za-z0-9_]{3,31})$')


def normalize_phone(raw: str) -> str | None:
    """Приводит любой ввод ('8 999 123-45-67', '+79991234567', '7999...') к +7XXXXXXXXXX."""
    if not raw:
        return None
    digits = PHONE_DIGITS.sub('', str(raw))
    if len(digits) == 10:
        digits = '7' + digits
    elif len(digits) == 11 and digits[0] in '78':
        digits = '7' + digits[1:]
    elif len(digits) == 11 and digits.startswith('9'):
        digits = '7' + digits
    else:
        return None
    return f'+{digits}' if len(digits) == 11 else None


def mask_phone(phone: str | None) -> str:
    """+79991234567 -> +7 999 *** ** 67 — номер наставнику не показываем целиком."""
    if not phone or len(phone) < 11:
        return 'не указан'
    return f'{phone[:5]} *** ** {phone[-2:]}'


def validate_name(raw: str) -> str | None:
    text = (raw or '').strip()
    return text.title() if NAME_RE.match(text) else None


def validate_city(raw: str) -> str | None:
    return validate_name(raw)


def validate_free_text(raw: str, min_len: int = 3, max_len: int = 150) -> str | None:
    text = re.sub(r'\s+', ' ', (raw or '')).strip()
    return text[:max_len] if len(text) >= min_len else None


def validate_nickname(raw: str) -> str | None:
    match = NICK_RE.match((raw or '').strip())
    return f'@{match.group(1)}' if match else None


def validate_choice(choices: tuple[str, ...]):
    def _validate(raw: str) -> str | None:
        text = (raw or '').strip()
        return text if text in choices else None
    return _validate
