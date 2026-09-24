"""Загрузчик учебных данных кейса FB01."""

import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "fb01"


@lru_cache(maxsize=None)
def load(name: str):
    path = DATA_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"Не найден учебный файл {path}. Распакуйте 02_Учебные_данные кейса FB01 в data/fb01/"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def segments() -> dict[str, str]:
    return load("segmentation_rules.json")["segments"]


def segmentation_rules() -> list[str]:
    return load("segmentation_rules.json")["rules"]


def knowledge_items() -> list[dict]:
    return load("knowledge_base.json")["items"]


def registration_events() -> list[dict]:
    return load("registration_events.json")


def event_by_client_id(client_id: str) -> dict | None:
    return next((e for e in registration_events() if e.get("client_id") == client_id), None)


def dialogues() -> list[dict]:
    return load("dialogues.json")


def dialogue_for(client_id: str) -> dict | None:
    return next((d for d in dialogues() if d.get("client_id") == client_id), None)


def tests() -> list[dict]:
    return load("tests.json")
