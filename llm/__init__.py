"""Sélecteur de backend LLM. Choisit l'implémentation selon `LLM_PROVIDER`."""

from .base import LLMClient
from .ollama_client import OllamaClient
from .openai_compat_client import OpenAICompatClient
from .anthropic_client import AnthropicClient


# Base URLs par défaut quand l'utilisateur ne précise pas LLM_BASE_URL
DEFAULT_BASE_URLS = {
    "ollama":    "http://localhost:11434",
    "openai":    "https://api.openai.com",
    "deepseek":  "https://api.deepseek.com",
    "mistral":   "https://api.mistral.ai",
    "groq":      "https://api.groq.com/openai",
    "together":  "https://api.together.xyz",
    "anthropic": "https://api.anthropic.com",
}


def make_llm_client(cfg) -> LLMClient:
    """Construit le bon client à partir de la config GAB."""
    provider = (cfg.LLM_PROVIDER or "ollama").lower()
    base_url = cfg.LLM_BASE_URL or DEFAULT_BASE_URLS.get(provider, "")

    if provider == "ollama":
        return OllamaClient(
            base_url    = base_url,
            model       = cfg.LLM_MODEL,
            max_tokens  = cfg.LLM_MAX_TOKENS,
            temperature = cfg.LLM_TEMPERATURE,
        )

    if provider == "anthropic":
        return AnthropicClient(
            base_url    = base_url,
            model       = cfg.LLM_MODEL,
            api_key     = cfg.LLM_API_KEY,
            max_tokens  = cfg.LLM_MAX_TOKENS,
            temperature = cfg.LLM_TEMPERATURE,
        )

    # Tous les autres = format OpenAI-compatible (deepseek, openai, mistral, groq, together, …)
    return OpenAICompatClient(
        base_url    = base_url,
        model       = cfg.LLM_MODEL,
        api_key     = cfg.LLM_API_KEY,
        max_tokens  = cfg.LLM_MAX_TOKENS,
        temperature = cfg.LLM_TEMPERATURE,
    )


__all__ = ["LLMClient", "make_llm_client"]
