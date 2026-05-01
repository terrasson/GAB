"""Interface abstraite pour les clients LLM de GAB.

Tout backend (Ollama, OpenAI-compatible, Anthropic, …) doit implémenter
cette interface pour être utilisable par GabAgent.
"""

from abc import ABC, abstractmethod


class LLMClient(ABC):
    """Contrat minimal qu'un client LLM doit respecter pour fonctionner avec GAB."""

    @abstractmethod
    async def chat(self, messages: list[dict], system: str | None = None) -> str:
        """Envoie l'historique de messages, retourne la réponse complète."""
        ...

    @abstractmethod
    async def is_alive(self) -> bool:
        """Vérifie que le backend répond et que le modèle configuré est utilisable."""
        ...

    @abstractmethod
    async def aclose(self) -> None:
        """Libère les ressources (sessions HTTP, etc.)."""
        ...
