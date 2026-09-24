"""Доступ к учебным данным кейса FB01.

Агент видит только knowledge_base.json, segmentation_rules.json,
registration_events.json и dialogues.json. Файл tests.json читает только
прогонщик проверок — в базу знаний агента ожидаемые ответы не загружаются.
"""
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _data_dir() -> pathlib.Path:
    """Папка с файлами кейса: своя, либо общий data/fb01 репозитория команды."""
    env = os.getenv('CASE_DATA_DIR')
    if env:
        return pathlib.Path(env)
    for candidate in (ROOT / '02_Учебные_данные', ROOT.parent / 'data' / 'fb01'):
        if (candidate / 'knowledge_base.json').exists():
            return candidate
    return ROOT / '02_Учебные_данные'


DATA_DIR = _data_dir()


def _load(name: str):
    path = DATA_DIR / name
    if not path.exists():
        raise FileNotFoundError(f'Нет файла данных кейса: {path}')
    return json.loads(path.read_text(encoding='utf-8'))


def knowledge_base() -> dict:
    return _load('knowledge_base.json')


def segmentation_rules() -> dict:
    return _load('segmentation_rules.json')


def registration_events() -> list[dict]:
    return _load('registration_events.json')


def dialogues() -> list[dict]:
    return _load('dialogues.json')


def tests() -> list[dict]:
    return _load('tests.json')


def output_example() -> dict:
    return _load('output_example.json')


def kb(rule_id: str) -> str:
    """Текст учебного правила по идентификатору (KB01..KB08)."""
    for item in knowledge_base().get('items', []):
        if item.get('id') == rule_id:
            return item.get('text', '')
    return ''
