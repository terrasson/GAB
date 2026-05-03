"""Client pour les API au format OpenAI : OpenAI, DeepSeek, Mistral, Groq, Together,
LM Studio, vLLM, ollama-openai, …

Endpoint POST {base_url}/v1/chat/completions, header Authorization: Bearer <key>.
"""

import json
import logging
import httpx

from .base import LLMClient, LLMResult, ToolCall

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

    def _api_url(self, path: str) -> str:
        """Construit l'URL finale en n'ajoutant `/v1` que si ce n'est pas déjà
        présent dans la base. Permet à l'utilisateur de mettre soit
        `https://api.openai.com` soit `https://api.openai.com/v1`."""
        base = self.base_url
        if base.endswith("/v1") or "/v1/" in base or "/api/v1" in base:
            return f"{base}/{path}"
        return f"{base}/v1/{path}"

    async def chat(
        self,
        messages: list[dict],
        system: str | None = None,
        tools: list[dict] | None = None,
    ) -> LLMResult:
        full = list(messages)
        if system:
            full = [{"role": "system", "content": system}, *full]
        payload: dict = {
            "model":       self.model,
            "messages":    full,
            "max_tokens":  self.max_tokens,
            "temperature": self.temperature,
            "stream":      False,
        }
        if tools:
            payload["tools"]       = tools
            payload["tool_choice"] = "auto"
        try:
            resp = await self._client.post(self._api_url("chat/completions"), json=payload)
            resp.raise_for_status()
            msg = resp.json()["choices"][0]["message"]
        except httpx.HTTPStatusError as exc:
            logger.error("Erreur HTTP %s : %s", exc.response.status_code, exc.response.text)
            raise
        except httpx.RequestError as exc:
            logger.error("Impossible de joindre %s : %s", self.base_url, exc)
            raise

        text = (msg.get("content") or "").strip()
        tool_calls: list[ToolCall] = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                logger.warning("Arguments tool-call non JSON, ignoré : %r", raw_args)
                continue
            tool_calls.append(ToolCall(
                id        = tc.get("id", ""),
                name      = fn.get("name", ""),
                arguments = args if isinstance(args, dict) else {},
            ))
        return LLMResult(text=text, tool_calls=tool_calls)

    async def is_alive(self) -> bool:
        """Vérifie que le provider est joignable.

        `/v1/models` est l'endpoint OpenAI standard, mais tous les providers
        OpenAI-compatibles ne l'exposent pas (ex : Manifest, certains vLLM,
        certaines instances LM Studio). Un 404/405 doit donc être traité
        comme « endpoint absent » et non « provider mort ».

        Règles :
        - 200            → joignable, on est sûr
        - 404 / 405      → endpoint pas exposé, on assume joignable
        - 401 / 403      → clé invalide, on considère KO (le chat échouera aussi)
        - autres 4xx     → le provider a répondu de manière structurée, joignable
        - 5xx            → provider en panne, KO
        - erreur réseau  → injoignable, KO
        """
        try:
            resp = await self._client.get(self._api_url("models"))
        except httpx.RequestError:
            return False
        code = resp.status_code
        if code == 200 or code in (404, 405) or (400 <= code < 500 and code not in (401, 403)):
            return True
        return False

    async def aclose(self) -> None:
        await self._client.aclose()
