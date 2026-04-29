"""Interface abstraite commune à toutes les plateformes."""

from abc import ABC, abstractmethod
from core.agent import GabAgent


class BasePlatform(ABC):
    """Chaque adaptateur de plateforme hérite de cette classe."""

    def __init__(self, agent: GabAgent):
        self.agent = agent

    @abstractmethod
    async def start(self) -> None:
        """Démarre l'écoute des messages (polling ou webhook)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Arrête proprement la plateforme."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Nom lisible de la plateforme."""
        ...
