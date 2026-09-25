"""Состояния FSM первичного диалога.

Имена состояний совпадают с ключами вопросов движка (assistant/engine.py),
поэтому шаг диалога читается прямо из значения состояния.
"""
from aiogram.fsm.state import State, StatesGroup


class Dialogue(StatesGroup):
    phone = State()
    goal = State()
    clarify = State()
    interests = State()
    available_time = State()
    experience = State()


class Question(StatesGroup):
    text = State()


class Editing(StatesGroup):
    value = State()


class AdminOps(StatesGroup):
    event_json = State()


def step_of(raw_state: str | None) -> str | None:
    """'Dialogue:goal' -> 'goal'."""
    if not raw_state or ':' not in raw_state:
        return None
    return raw_state.split(':')[-1]
