"""
Mémoire conversationnelle par utilisateur et par plateforme.
Clé : (platform, user_id)
"""

from collections import defaultdict
from dataclasses import dataclass, field


MAX_HISTORY = 20  # messages gardés par conversation


@dataclass
class Conversation:
    messages: list[dict] = field(default_factory=list)

    def add(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
        if len(self.messages) > MAX_HISTORY:
            self.messages = self.messages[-MAX_HISTORY:]

    def get_history(self) -> list[dict]:
        return list(self.messages)

    def clear(self) -> None:
        self.messages.clear()


class Memory:
    """Stockage en mémoire des conversations (à remplacer par Redis pour la prod)."""

    def __init__(self):
        self._store: dict[tuple[str, str], Conversation] = defaultdict(Conversation)

    def get(self, platform: str, user_id: str) -> Conversation:
        return self._store[(platform, user_id)]

    def clear(self, platform: str, user_id: str) -> None:
        self._store[(platform, user_id)].clear()
