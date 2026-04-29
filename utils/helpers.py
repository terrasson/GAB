"""Utilitaires partagés."""

import functools
import logging
from typing import Callable

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger("GAB.utils")

MAX_TG_MSG = 4096  # limite Telegram


def admin_only(func: Callable) -> Callable:
    """Décorateur : refuse l'accès si l'utilisateur n'est pas dans ADMIN_IDS."""

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        cfg = context.bot_data.get("config")
        user_id = update.effective_user.id if update.effective_user else None
        if cfg and cfg.ADMIN_IDS and user_id not in cfg.ADMIN_IDS:
            await update.effective_message.reply_text(
                "⛔ Désolé, cette commande est réservée aux administrateurs."
            )
            logger.warning("Accès refusé à %s pour %s", user_id, func.__name__)
            return
        return await func(update, context)

    return wrapper


def truncate(text: str, max_len: int = MAX_TG_MSG) -> str:
    """Tronque un texte pour respecter la limite Telegram."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "…"


def format_reply(text: str) -> str:
    """Nettoie et formate la réponse avant envoi."""
    return truncate(text.strip())
