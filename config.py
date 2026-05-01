"""Configuration centralisée de GAB — Grand Assistant de Bureau."""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


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

    SYSTEM_PROMPT: str = (
        "Tu es GAB, un majordome virtuel élégant, précis et légèrement pince-sans-rire. "
        "Tu réponds toujours en français, avec courtoisie et efficacité. "
        "Tu organises des groupes de discussion, invites des membres, "
        "résumes les échanges et aides l'utilisateur sur toutes ses demandes."
    )

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
