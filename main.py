#!/usr/bin/env python3
"""
GAB — Grand Assistant de Bureau
Majordome multi-plateforme alimenté par le LLM Hermes (Ollama).

Plateformes supportées :
  • Telegram  (polling)
  • WhatsApp  (Meta Cloud API — webhook)
  • Discord   (gateway)
"""

import asyncio
import logging
import signal
import uvicorn

from config import Config
from core.agent import GabAgent
from platforms.telegram import TelegramPlatform
from platforms.whatsapp import WhatsAppPlatform
from platforms.discord import DiscordPlatform
from api.server import build_app

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger("GAB")


async def run() -> None:
    cfg   = Config()
    agent = GabAgent(cfg)

    active_platforms = []

    # ── Telegram ──────────────────────────────────────────────────────────────
    if cfg.TELEGRAM_ENABLED:
        tg = TelegramPlatform(agent, cfg.TELEGRAM_TOKEN)
        active_platforms.append(tg)
        logger.info("✅ Telegram activé")
    else:
        logger.warning("⚠️  Telegram désactivé (TELEGRAM_BOT_TOKEN manquant)")

    # ── WhatsApp ──────────────────────────────────────────────────────────────
    wa = None
    if cfg.WA_ENABLED:
        wa = WhatsAppPlatform(agent, cfg.WA_TOKEN, cfg.WA_PHONE_ID)
        active_platforms.append(wa)
        logger.info("✅ WhatsApp activé")
    else:
        logger.warning("⚠️  WhatsApp désactivé (WA_TOKEN / WA_PHONE_ID manquants)")

    # ── Discord ───────────────────────────────────────────────────────────────
    if cfg.DISCORD_ENABLED:
        dc = DiscordPlatform(agent, cfg.DISCORD_TOKEN)
        active_platforms.append(dc)
        logger.info("✅ Discord activé")
    else:
        logger.warning("⚠️  Discord désactivé (DISCORD_TOKEN manquant)")

    if not active_platforms:
        logger.error("❌ Aucune plateforme configurée. Ajoutez au moins un token dans .env")
        return

    # ── Serveur FastAPI (webhooks WhatsApp + healthcheck) ─────────────────────
    fastapi_app = build_app(whatsapp_platform=wa, verify_token=cfg.WA_VERIFY_TOKEN)
    uvi_config  = uvicorn.Config(
        fastapi_app,
        host=cfg.API_HOST,
        port=cfg.API_PORT,
        log_level="warning",
    )
    uvi_server  = uvicorn.Server(uvi_config)

    logger.info("🎩 GAB démarre sur %d plateforme(s)…", len(active_platforms))

    # Démarrage de toutes les plateformes en parallèle
    tasks = [asyncio.create_task(p.start()) for p in active_platforms]
    tasks.append(asyncio.create_task(uvi_server.serve()))

    # Arrêt propre sur SIGINT / SIGTERM
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(_shutdown(active_platforms, tasks)))

    await asyncio.gather(*tasks, return_exceptions=True)
    await agent.close()
    logger.info("🎩 GAB arrêté. Au revoir, maître.")


async def _shutdown(platforms, tasks) -> None:
    logger.info("🛑 Arrêt en cours…")
    for p in platforms:
        try:
            await p.stop()
        except Exception:
            pass
    for t in tasks:
        t.cancel()


if __name__ == "__main__":
    asyncio.run(run())
