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

    async def send_message(self, target_chat: str, text: str) -> None:
        """Envoie un message texte à un chat (groupe ou DM).

        Utilisé par le scheduler de rappels et par tout dispatcher asynchrone.
        Implémentation par défaut : NotImplementedError. Les plateformes
        actives doivent surcharger cette méthode. Les plateformes non encore
        utilisées en prod (Discord pour le moment) peuvent garder le défaut —
        le scheduler loggue l'erreur et passe au rappel suivant.
        """
        raise NotImplementedError(f"{self.name}: send_message non implémenté")
