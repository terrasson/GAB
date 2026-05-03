"""Interface abstraite pour les clients LLM de GAB.

Tout backend (Ollama, OpenAI-compatible, Anthropic, …) doit implémenter
cette interface pour être utilisable par GabAgent.

Le résultat d'un appel `chat()` est `LLMResult`, qui peut porter à la fois :
- du texte (réponse classique)
- des appels d'outils structurés (tool calling, alias function calling)

Cette double sortie permet à GAB de demander au LLM d'invoquer des actions
côté backend (ex : `create_poll(question, options)`) plutôt que d'exiger de
l'utilisateur la syntaxe rigide d'une commande slash.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    """Un appel d'outil émis par le LLM."""
    id: str                  # identifiant Telegram-style retourné par le provider
    name: str                # nom de l'outil (ex : "create_poll")
    arguments: dict          # arguments JSON désérialisés


@dataclass
class LLMResult:
    """Réponse unifiée d'un appel LLM."""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMClient(ABC):
    """Contrat minimal qu'un client LLM doit respecter pour fonctionner avec GAB."""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        system: str | None = None,
        tools: list[dict] | None = None,
    ) -> LLMResult:
        """Envoie l'historique de messages, retourne le texte ou des tool calls.

        `tools` est au format OpenAI tools-calling : liste d'objets
        `{"type": "function", "function": {"name", "description", "parameters"}}`.
        Les backends qui ne supportent pas le tool calling l'ignorent et
        renvoient simplement du texte.
        """
        ...

    @abstractmethod
    async def is_alive(self) -> bool:
        """Vérifie que le backend répond et que le modèle configuré est utilisable."""
        ...

    @abstractmethod
    async def aclose(self) -> None:
        """Libère les ressources (sessions HTTP, etc.)."""
        ...
