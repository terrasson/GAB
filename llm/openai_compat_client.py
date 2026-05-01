"""Client pour les API au format OpenAI : OpenAI, DeepSeek, Mistral, Groq, Together,
LM Studio, vLLM, ollama-openai, …

Endpoint POST {base_url}/v1/chat/completions, header Authorization: Bearer <key>.
"""

import logging
import httpx

from .base import LLMClient

logger = logging.getLogger("GAB.llm.openai_compat")


class OpenAICompatClient(LLMClient):
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
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
            },
        )

    async def chat(self, messages: list[dict], system: str | None = None) -> str:
        full = list(messages)
        if system:
            full = [{"role": "system", "content": system}, *full]
        payload = {
            "model":       self.model,
            "messages":    full,
            "max_tokens":  self.max_tokens,
            "temperature": self.temperature,
            "stream":      False,
        }
        try:
            resp = await self._client.post(f"{self.base_url}/v1/chat/completions", json=payload)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except httpx.HTTPStatusError as exc:
            logger.error("Erreur HTTP %s : %s", exc.response.status_code, exc.response.text)
            raise
        except httpx.RequestError as exc:
            logger.error("Impossible de joindre %s : %s", self.base_url, exc)
            raise

    async def is_alive(self) -> bool:
        try:
            resp = await self._client.get(f"{self.base_url}/v1/models")
            resp.raise_for_status()
            return True
        except Exception:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
