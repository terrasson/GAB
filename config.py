"""Configuration centralisée de GAB — Grand Assistant de Bureau."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)  # `.env` est la source de vérité, prime sur les vars d'env système

_PROMPT_FILE = Path(__file__).parent / "prompts" / "system.md"
_FALLBACK_PROMPT = (
    "Tu es GAB, un concierge-agent qui aide des groupes humains à s'organiser. "
    "Réponds en français, avec courtoisie, efficacité et concision."
)


def _load_system_prompt() -> str:
    if _PROMPT_FILE.exists():
        return _PROMPT_FILE.read_text(encoding="utf-8").strip()
    return _FALLBACK_PROMPT


@dataclass
class Config:
    # ── LLM (provider-agnostique) ────────────────────────────────────────────
    # Provider : ollama | openai | deepseek | mistral | groq | together | anthropic
    LLM_PROVIDER: str    = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "ollama"))
    # Modèle : qwen3:8b, gpt-4o-mini, deepseek-chat, claude-sonnet-4-6, mistral-large-latest, …
    LLM_MODEL: str       = field(default_factory=lambda: os.getenv("LLM_MODEL") or os.getenv("HERMES_MODEL", "qwen3:8b"))
    # URL de l'API. Vide = défaut du provider (ex: https://api.deepseek.com pour deepseek)
    LLM_BASE_URL: str    = field(default_factory=lambda: os.getenv("LLM_BASE_URL") or os.getenv("OLLAMA_BASE_URL", ""))
    # Clé API. Vide pour Ollama, requis pour les providers cloud.
    LLM_API_KEY: str     = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))

    LLM_MAX_TOKENS: int    = field(default_factory=lambda: int(os.getenv("LLM_MAX_TOKENS", "1024")))
    LLM_TEMPERATURE: float = field(default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.7")))

    SYSTEM_PROMPT: str = field(default_factory=_load_system_prompt)

    # ── Telegram ─────────────────────────────────────────────────────────────
    TELEGRAM_TOKEN: str   = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    TELEGRAM_ENABLED: bool = field(default_factory=lambda: bool(os.getenv("TELEGRAM_BOT_TOKEN")))

    # ── WhatsApp (Meta Cloud API) ─────────────────────────────────────────────
    WA_TOKEN: str        = field(default_factory=lambda: os.getenv("WA_TOKEN", ""))
    WA_PHONE_ID: str     = field(default_factory=lambda: os.getenv("WA_PHONE_ID", ""))
    WA_VERIFY_TOKEN: str = field(default_factory=lambda: os.getenv("WA_VERIFY_TOKEN", "gab_secret"))
    WA_ENABLED: bool     = field(default_factory=lambda: bool(os.getenv("WA_TOKEN") and os.getenv("WA_PHONE_ID")))

    # ── Discord ───────────────────────────────────────────────────────────────
    DISCORD_TOKEN: str   = field(default_factory=lambda: os.getenv("DISCORD_TOKEN", ""))
    DISCORD_ENABLED: bool = field(default_factory=lambda: bool(os.getenv("DISCORD_TOKEN")))

    # ── API Webhook interne ───────────────────────────────────────────────────
    API_HOST: str = field(default_factory=lambda: os.getenv("API_HOST", "0.0.0.0"))
    API_PORT: int = field(default_factory=lambda: int(os.getenv("API_PORT", "8000")))

    # ── Admins (IDs cross-plateforme, format "platform:id") ───────────────────
    ADMIN_IDS: list[str] = field(
        default_factory=lambda: [x.strip() for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
    )

    # ── Whitelist d'accès (sécurité contre l'usage abusif des crédits LLM) ────
    # Si les deux listes sont vides → mode permissif (tout le monde peut parler).
    # Si au moins une est remplie → mode strict : seuls les users/groupes listés.
    ALLOWED_USERS: list[str] = field(
        default_factory=lambda: [x.strip() for x in os.getenv("ALLOWED_USERS", "").split(",") if x.strip()]
    )
    ALLOWED_GROUPS: list[str] = field(
        default_factory=lambda: [x.strip() for x in os.getenv("ALLOWED_GROUPS", "").split(",") if x.strip()]
    )
