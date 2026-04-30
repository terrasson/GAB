"""
Connecteur vers le modèle Hermes via l'API Ollama.
Docs Ollama : https://github.com/ollama/ollama/blob/main/docs/api.md
"""

import logging
from typing import AsyncGenerator

import httpx

logger = logging.getLogger("GAB.llm")


class HermesClient:
    """Client asynchrone pour le LLM Hermes (Ollama)."""

    def __init__(self, base_url: str, model: str, max_tokens: int, temperature: float):
        self.base_url    = base_url.rstrip("/")
        self.model       = model
        self.max_tokens  = max_tokens
        self.temperature = temperature
        self._client     = httpx.AsyncClient(timeout=120.0)

    # ── Génération simple (attend la réponse complète) ───────────────────────

    async def chat(
        self,
        messages: list[dict],
        system: str | None = None,
    ) -> str:
        """Envoie une liste de messages et retourne la réponse complète."""
        payload = self._build_payload(messages, system, stream=False)
        try:
            resp = await self._client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"].strip()
        except httpx.HTTPStatusError as exc:
            logger.error("Erreur HTTP Ollama %s : %s", exc.response.status_code, exc.response.text)
            raise
        except httpx.RequestError as exc:
            logger.error("Impossible de joindre Ollama (%s) : %s", self.base_url, exc)
            raise

    # ── Génération en streaming ──────────────────────────────────────────────

    async def stream(
        self,
        messages: list[dict],
        system: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Génère la réponse mot par mot (streaming)."""
        payload = self._build_payload(messages, system, stream=True)
        async with self._client.stream(
            "POST",
            f"{self.base_url}/api/chat",
            json=payload,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                import json
                chunk = json.loads(line)
                token = chunk.get("message", {}).get("content", "")
                if token:
                    yield token
                if chunk.get("done"):
                    break

    # ── Santé ────────────────────────────────────────────────────────────────

    async def is_alive(self) -> bool:
        """Vérifie qu'Ollama répond et que le modèle est disponible."""
        try:
            resp = await self._client.get(f"{self.base_url}/api/tags")
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            return any(self.model in m for m in models)
        except Exception:
            return False

    # ── Helpers privés ───────────────────────────────────────────────────────

    def _build_payload(
        self,
        messages: list[dict],
        system: str | None,
        stream: bool,
    ) -> dict:
        full_messages = list(messages)
        if system:
            full_messages = [{"role": "system", "content": system}, *full_messages]
        return {
            "model":  self.model,
            "stream": stream,
            "think":  False,
            "options": {
                "num_predict": self.max_tokens,
                "temperature": self.temperature,
            },
            "messages": full_messages,
        }

    async def aclose(self) -> None:
        await self._client.aclose()
