"""Client Ollama (local ou self-hosted) — endpoint /api/chat.

Utilisé pour qwen3, llama3, mistral, nous-hermes2, etc.
Aucune clé API : c'est l'utilisateur qui héberge Ollama.
"""

import logging
import httpx

from .base import LLMClient, LLMResult

logger = logging.getLogger("GAB.llm.ollama")


class OllamaClient(LLMClient):
    def __init__(
        self,
        base_url: str,
        model: str,
        max_tokens: int,
        temperature: float,
    ):
        self.base_url    = base_url.rstrip("/")
        self.model       = model
        self.max_tokens  = max_tokens
        self.temperature = temperature
        self._client     = httpx.AsyncClient(timeout=120.0)

    async def chat(
        self,
        messages: list[dict],
        system: str | None = None,
        tools: list[dict] | None = None,
    ) -> LLMResult:
        # Ollama : tool calling pas exposé de façon homogène entre modèles → on l'ignore.
        # Les utilisateurs Ollama gardent /sondage manuel comme fallback.
        full = list(messages)
        if system:
            full = [{"role": "system", "content": system}, *full]
        payload = {
            "model":    self.model,
            "stream":   False,
            "think":    False,
            "messages": full,
            "options":  {"num_predict": self.max_tokens, "temperature": self.temperature},
        }
        try:
            resp = await self._client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            return LLMResult(text=resp.json()["message"]["content"].strip())
        except httpx.HTTPStatusError as exc:
            logger.error("Erreur HTTP Ollama %s : %s", exc.response.status_code, exc.response.text)
            raise
        except httpx.RequestError as exc:
            logger.error("Impossible de joindre Ollama (%s) : %s", self.base_url, exc)
            raise

    async def is_alive(self) -> bool:
        try:
            resp = await self._client.get(f"{self.base_url}/api/tags")
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            return any(self.model in m for m in models)
        except Exception:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
