"""Контекст диалога: учебное событие регистрации плюс уже собранные сведения о человеке."""

from dataclasses import dataclass, field

from common import knowledge

UNKNOWN_CLIENT_ID = "UNKNOWN"


@dataclass
class DialogueContext:
    client_id: str
    initial_message: str
    new_message: str
    history: list[dict] = field(default_factory=list)
    known_facts: list[str] = field(default_factory=list)
    from_dataset: bool = True

    @property
    def is_new_client(self) -> bool:
        return self.client_id == UNKNOWN_CLIENT_ID

    def client_turn_texts(self) -> list[str]:
        """Реплики клиента — единственный источник, из которого агент вправе брать цитаты."""
        turns = [turn.get("text", "") for turn in self.history if turn.get("role") == "user"]
        return [text for text in [*turns, self.new_message] if text]


def load_dataset_case(message: str, client_id: str | None = None) -> DialogueContext:
    wanted = (client_id or message).strip()
    event = knowledge.event_by_client_id(wanted)

    if event is not None:
        dialogue = knowledge.dialogue_for(event["client_id"]) or {}
        return DialogueContext(
            client_id=event["client_id"],
            initial_message=event.get("initial_message", ""),
            new_message=message.strip() if client_id else event.get("initial_message", ""),
            history=dialogue.get("messages", []),
        )

    return DialogueContext(
        client_id=(client_id or UNKNOWN_CLIENT_ID).strip(),
        initial_message="",
        new_message=message.strip(),
        from_dataset=False,
    )
