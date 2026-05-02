"""
Adaptateur Telegram pour GAB.
Utilise python-telegram-bot en mode polling.
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    filters,
    ContextTypes,
)

from platforms.base import BasePlatform
from core.agent import GabAgent, Message

logger = logging.getLogger("GAB.telegram")


class TelegramPlatform(BasePlatform):
    """Plateforme Telegram : polling + gestion des groupes natifs."""

    name = "telegram"

    def __init__(self, agent: GabAgent, token: str):
        super().__init__(agent)
        self._token = token
        self._app = (
            ApplicationBuilder()
            .token(token)
            .concurrent_updates(True)
            .build()
        )
        self._register_handlers()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        logger.info("🎩 Telegram — démarrage du polling…")
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=["message", "chat_member", "my_chat_member", "callback_query"],
        )

    async def stop(self) -> None:
        await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()
        logger.info("Telegram — arrêté.")

    # ── Handlers ─────────────────────────────────────────────────────────────

    def _register_handlers(self) -> None:
        app = self._app
        app.add_handler(CommandHandler("start",        self._on_command))
        app.add_handler(CommandHandler("help",         self._on_command))
        app.add_handler(CommandHandler("ask",          self._on_command))
        app.add_handler(CommandHandler("creategroup",  self._on_command))
        app.add_handler(CommandHandler("invite",       self._on_command))
        app.add_handler(CommandHandler("summary",      self._on_command))
        app.add_handler(CommandHandler("clear",        self._on_command))
        app.add_handler(CommandHandler("status",       self._on_command))
        app.add_handler(CommandHandler("members",      self._on_command))
        app.add_handler(CallbackQueryHandler(self._on_button))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message))
        app.add_handler(ChatMemberHandler(self._on_chat_member, ChatMemberHandler.CHAT_MEMBER))
        app.add_handler(ChatMemberHandler(self._on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    async def _on_command(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch(update, ctx)

    async def _on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch(update, ctx)

    async def _on_button(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        # On réinjecte le callback_data comme texte de commande
        fake_msg = Message(
            platform   = self.name,
            user_id    = str(query.from_user.id),
            username   = query.from_user.first_name or "User",
            text       = f"/{query.data}",
            group_id   = str(query.message.chat.id) if query.message.chat else None,
            group_name = query.message.chat.title if query.message.chat else None,
        )
        response = await self.agent.handle(fake_msg)
        await query.message.reply_text(response.text, parse_mode=ParseMode.MARKDOWN)

        # Action spéciale : créer un vrai lien d'invitation Telegram
        if response.action == "create_group" and query.message.chat.type in ("group", "supergroup"):
            try:
                link = await ctx.bot.create_chat_invite_link(
                    chat_id=query.message.chat.id,
                    name=response.action_data.get("name", "GAB invite"),
                )
                await query.message.reply_text(f"🔗 Lien d'invitation : {link.invite_link}")
            except Exception as exc:
                logger.warning("Impossible de créer le lien Telegram : %s", exc)

    # ── Suivi des membres ─────────────────────────────────────────────────────

    async def _on_chat_member(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Détecte les arrivées/départs de membres dans un groupe où GAB est admin."""
        cm = update.chat_member
        if not cm:
            return
        chat = cm.chat
        new = cm.new_chat_member
        old = cm.old_chat_member
        was_in  = old.status in ("member", "administrator", "creator", "restricted")
        is_in   = new.status in ("member", "administrator", "creator", "restricted")
        user    = new.user

        if is_in and not was_in:
            self.agent.groups.register_member(
                group_id   = str(chat.id),
                group_name = chat.title or "",
                platform   = self.name,
                user_id    = str(user.id),
                username   = user.username or user.first_name or "",
            )
        elif was_in and not is_in:
            self.agent.groups.remove_member(str(chat.id), str(user.id))
            logger.info("➖ Membre %s (id=%s) a quitté %s", user.first_name, user.id, chat.id)

    async def _on_my_chat_member(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Détecte quand GAB lui-même est ajouté/retiré d'un groupe."""
        mcm = update.my_chat_member
        if not mcm:
            return
        chat = mcm.chat
        new_status = mcm.new_chat_member.status
        if new_status in ("member", "administrator") and chat.type in ("group", "supergroup"):
            self.agent.groups.register_member(
                group_id   = str(chat.id),
                group_name = chat.title or "",
                platform   = self.name,
                user_id    = str(mcm.from_user.id),
                username   = mcm.from_user.username or mcm.from_user.first_name or "",
            )
            logger.info("🎩 GAB ajouté au groupe %s (%s) — statut: %s", chat.title, chat.id, new_status)

    # ── Dispatch central ──────────────────────────────────────────────────────

    async def _dispatch(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_user:
            return

        tg_msg = update.effective_message
        user   = update.effective_user
        chat   = update.effective_chat
        text   = tg_msg.text or ""
        is_group = chat.type in ("group", "supergroup")

        msg = Message(
            platform   = self.name,
            user_id    = str(user.id),
            username   = user.first_name or user.username or "User",
            text       = text,
            group_id   = str(chat.id) if is_group else None,
            group_name = chat.title if is_group else None,
        )

        # Collecte passive : tout sender dans un groupe est enregistré
        if msg.group_id:
            self.agent.groups.register_member(
                group_id   = msg.group_id,
                group_name = msg.group_name or "",
                platform   = self.name,
                user_id    = msg.user_id,
                username   = user.username or user.first_name or "",
            )

        # Mode écoute passive : en groupe, on ne parle que si sollicité.
        # Sinon on enregistre le message dans la mémoire du groupe pour que
        # le LLM ait le contexte la prochaine fois qu'il est appelé.
        if is_group and not self._should_respond_in_group(tg_msg, ctx):
            conv = self.agent.memory.get(msg.platform, msg.user_id, msg.group_id)
            conv.add("user", text, author=user.username or user.first_name or "")
            return

        # Indicateur "en train d'écrire…"
        await ctx.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)

        response = await self.agent.handle(msg)
        # Réponse silencieuse : on n'envoie rien (utile pour le rejet whitelist
        # en groupe ou tout autre cas où Response.text est vide).
        if response.text:
            await tg_msg.reply_text(response.text, parse_mode=ParseMode.MARKDOWN)

        # Génération automatique d'un lien si on est dans un groupe
        if (
            response.action == "create_group"
            and is_group
        ):
            try:
                link = await ctx.bot.create_chat_invite_link(
                    chat_id=chat.id,
                    name=response.action_data.get("name", "GAB invite"),
                )
                await tg_msg.reply_text(f"🔗 Lien d'invitation Telegram : {link.invite_link}")
            except Exception as exc:
                logger.warning("Lien d'invitation impossible : %s", exc)

    # ── Mode écoute passive : on ne répond que si sollicité ───────────────────

    def _should_respond_in_group(self, tg_msg, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
        """En groupe, GAB ne répond que si on l'invite explicitement :
        - Commande (/start, /sondage, ...)
        - Mention textuelle `@<bot_username>`
        - Réponse à l'un de ses propres messages
        """
        text = tg_msg.text or ""

        # Commande explicite
        if text.startswith("/"):
            return True

        # Mention de GAB dans les entities
        bot_username = (ctx.bot.username or "").lower()
        if bot_username and tg_msg.entities:
            for entity in tg_msg.entities:
                if entity.type == "mention":
                    mention = text[entity.offset : entity.offset + entity.length]
                    if mention.lower() == f"@{bot_username}":
                        return True

        # Réponse à un message de GAB
        if tg_msg.reply_to_message and tg_msg.reply_to_message.from_user:
            if tg_msg.reply_to_message.from_user.id == ctx.bot.id:
                return True

        return False
