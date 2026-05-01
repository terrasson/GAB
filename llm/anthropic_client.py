"""Client Anthropic Claude — endpoint POST /v1/messages.

Utilise httpx direct (pas le SDK anthropic) pour rester léger et homogène
avec les autres clients de GAB.
"""

import logging
import httpx

from .base import LLMClient

logger = logging.getLogger("GAB.llm.anthropic")

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicClient(LLMClient):
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        max_tokens: int,
        temperature: float,
    ):
        self.base_url    = base_url.rstrip("/")
        self.model       = model
        self.max_tokens  = max_tokens
        self.temperature = temperature
        self._client     = httpx.AsyncClient(
            timeout=120.0,
            headers={
                "x-api-key":         api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "Content-Type":      "application/json",
            },
        )

    async def chat(self, messages: list[dict], system: str | None = None) -> str:
        payload: dict = {
            "model":       self.model,
            "messages":    messages,
            "max_tokens":  self.max_tokens,
            "temperature": self.temperature,
        }
        if system:
            payload["system"] = system
        try:
            resp = await self._client.post(f"{self.base_url}/v1/messages", json=payload)
            resp.raise_for_status()
            data = resp.json()
            blocks = data.get("content", [])
            return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        except httpx.HTTPStatusError as exc:
            logger.error("Erreur HTTP Anthropic %s : %s", exc.response.status_code, exc.response.text)
            raise
        except httpx.RequestError as exc:
            logger.error("Impossible de joindre Anthropic (%s) : %s", self.base_url, exc)
            raise

    async def is_alive(self) -> bool:
        try:
            resp = await self._client.post(
                f"{self.base_url}/v1/messages",
                json={
                    "model":      self.model,
                    "messages":   [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                },
            )
            return resp.status_code < 500
        except Exception:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
