"""
Adaptateur Telegram pour GAB.
Utilise python-telegram-bot en mode polling.
"""

import re
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
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

# Mot d'éveil : `#gab`, `@gab`, `#ia`, `@ia`, … (le `@` couvre l'intuition humaine
# qui veut interpeller GAB comme une mention même quand Telegram ne le reconnaît
# pas comme une vraie mention — `@gab` n'est pas le username exact du bot).
# Le préfixe est exigé en début de message ou après un espace, pour éviter les
# faux positifs du type "email@gab.com".
WAKE_RE = re.compile(r"(?:^|\s)[#@](\w+)", re.UNICODE)


# ── Welcome flow (palier 1.7) ────────────────────────────────────────────────
# Permissions admin demandées via le lien magique. Couvrent l'usage typique
# (invitations, épinglage, modération légère).
ADMIN_PERMS = "delete_messages+pin_messages+invite_users+manage_chat"

ADMIN_WELCOME = (
    "🎩 *Bonjour !* Merci de m'avoir ajouté avec les permissions admin.\n\n"
    "Je suis votre concierge-agent : j'aide votre groupe à s'organiser "
    "(sondages, rappels, listes…). Quelques exemples pour démarrer :\n\n"
    "• `/sondage Restaurant ? Pizza | Sushi | Burger` — vote en 1 clic\n"
    "• `/rappel 2026-05-08 19:00 RDV chez Mario` — notification programmée\n"
    "• `/liste BBQ : Steaks | Salade | Vin` — liste partagée modifiable\n"
    "• `/help` — toutes les commandes\n\n"
    "Vous pouvez aussi me parler naturellement en mentionnant `@gab` ou avec "
    "le hashtag `#gab` — par exemple : *« @gab fais un sondage pour le resto »*."
)

MEMBER_WELCOME_TEMPLATE = (
    "🎩 *Bonjour !* Merci de m'avoir ajouté à ce groupe.\n\n"
    "Je suis votre concierge-agent (sondages, rappels, listes partagées…), "
    "mais je suis pour l'instant ajouté en *simple membre*. Pour fonctionner "
    "pleinement (gérer les invitations, épingler, etc.), j'ai besoin d'être "
    "*administrateur* avec quelques permissions.\n\n"
    "Demandez à un admin du groupe de me promouvoir, ou utilisez ce lien "
    "magique qui pré-coche les bonnes permissions :\n"
    "[➡️ Promouvoir GAB en admin](https://t.me/{bot_username}?startgroup=true&admin={perms})\n\n"
    "En attendant, vous pouvez tester `/help` pour voir mes commandes."
)

PROMOTION_THANKS = (
    "🎩 Merci pour la promotion ! Je suis maintenant admin avec les bonnes "
    "permissions — toutes mes fonctionnalités sont disponibles. `/help` pour les voir."
)


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

    async def send_message(self, target_chat: str, text: str) -> None:
        """Envoie un message texte à un chat Telegram (groupe ou DM).

        Utilisé par le scheduler de rappels pour livrer les notifications à
        l'heure dite. `target_chat` est l'identifiant Telegram numérique du
        groupe (-100…) ou de l'utilisateur en DM.
        """
        try:
            await self._app.bot.send_message(
                chat_id    = int(target_chat),
                text       = text,
                parse_mode = ParseMode.MARKDOWN,
            )
        except Exception as exc:
            logger.error("Échec envoi Telegram → %s : %s", target_chat, exc)
            raise

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
        app.add_handler(CommandHandler("sondage",      self._on_command))
        app.add_handler(CommandHandler("rappel",       self._on_command))
        app.add_handler(CommandHandler("liste",        self._on_command))
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

        # Vote sur un sondage : `vote:<poll_id>:<option_index>`
        if query.data and query.data.startswith("vote:"):
            await self._handle_vote_click(query)
            return

        # Claim d'un item de liste : `claim:<list_id>:<item_index>`
        if query.data and query.data.startswith("claim:"):
            await self._handle_claim_click(query)
            return

        # Sinon, callback générique : on réinjecte comme texte de commande
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
        """Détecte quand GAB lui-même est ajouté/retiré d'un groupe.

        Trois transitions intéressantes (palier 1.7 — welcome flow) :
        - left/kicked → administrator : welcome admin (toutes les commandes dispo)
        - left/kicked → member        : welcome simple membre + lien magique
                                        pour promotion en admin
        - member      → administrator : remerciements brefs (promotion réussie)
        """
        mcm = update.my_chat_member
        if not mcm:
            return
        chat = mcm.chat
        new_status = mcm.new_chat_member.status
        old_status = mcm.old_chat_member.status if mcm.old_chat_member else "left"

        was_in = old_status in ("member", "administrator", "creator", "restricted")
        is_in  = new_status in ("member", "administrator", "creator", "restricted")
        is_group = chat.type in ("group", "supergroup")

        if not is_in or not is_group:
            return

        # Enregistre la présence (palier 1.1)
        self.agent.groups.register_member(
            group_id   = str(chat.id),
            group_name = chat.title or "",
            platform   = self.name,
            user_id    = str(mcm.from_user.id),
            username   = mcm.from_user.username or mcm.from_user.first_name or "",
        )
        logger.info("🎩 GAB dans %s (%s) : %s → %s",
                    chat.title, chat.id, old_status, new_status)

        # Auto-whitelist (palier 1.7+) : si l'inviteur est un user de confiance
        # (ALLOWED_USERS), on whitelist automatiquement le groupe pour que tous
        # ses membres puissent utiliser GAB. Évite d'avoir à éditer .env à la
        # main pour chaque nouveau groupe créé par l'admin.
        if not was_in:
            inviter_id = str(mcm.from_user.id)
            inviter_keys = {inviter_id, f"{self.name}:{inviter_id}"}
            allowed_users = self.agent.cfg.ALLOWED_USERS
            if allowed_users and any(k in allowed_users for k in inviter_keys):
                self.agent.groups.whitelist(
                    group_id = str(chat.id),
                    platform = self.name,
                    added_by = inviter_id,
                )

        # Welcome flow
        try:
            if not was_in:
                # Premier ajout au groupe
                if new_status == "administrator":
                    await ctx.bot.send_message(
                        chat_id    = chat.id,
                        text       = ADMIN_WELCOME,
                        parse_mode = ParseMode.MARKDOWN,
                    )
                else:
                    await ctx.bot.send_message(
                        chat_id    = chat.id,
                        text       = MEMBER_WELCOME_TEMPLATE.format(
                            bot_username = ctx.bot.username,
                            perms        = ADMIN_PERMS,
                        ),
                        parse_mode = ParseMode.MARKDOWN,
                        disable_web_page_preview = True,
                    )
            elif old_status == "member" and new_status == "administrator":
                # Promotion en cours de route
                await ctx.bot.send_message(
                    chat_id    = chat.id,
                    text       = PROMOTION_THANKS,
                    parse_mode = ParseMode.MARKDOWN,
                )
        except Exception as exc:
            # Ne pas faire crasher le handler pour un message de bienvenue raté
            logger.warning("Welcome message non envoyé dans %s : %s", chat.id, exc)

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

        # Sondage fraîchement créé : on attache le clavier inline et c'est tout
        if response.action == "render_poll" and response.action_data:
            await tg_msg.reply_text(
                response.text,
                parse_mode    = ParseMode.MARKDOWN,
                reply_markup  = self._build_poll_keyboard(response.action_data),
            )
            return

        # Liste fraîchement créée : pareil, clavier inline pour les claims
        if response.action == "render_list" and response.action_data:
            await tg_msg.reply_text(
                response.text,
                parse_mode    = ParseMode.MARKDOWN,
                reply_markup  = self._build_list_keyboard(response.action_data),
            )
            return

        # Réponse silencieuse : on n'envoie rien (utile pour le rejet whitelist
        # en groupe ou tout autre cas où Response.text est vide).
        if response.text:
            # Si GAB pose une question dans un groupe, on attache ForceReply pour
            # nudger l'utilisateur à répondre via la fonction Reply de Telegram.
            # Sans ça, en mode passif, sa réponse libre serait ignorée.
            reply_markup = None
            if is_group and response.text.rstrip().endswith("?"):
                reply_markup = ForceReply(selective=True)
            await tg_msg.reply_text(
                response.text,
                parse_mode   = ParseMode.MARKDOWN,
                reply_markup = reply_markup,
            )

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
        - Hashtag d'éveil (`#gab`, `#ia`, …) configurable via WAKE_TAGS
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

        # Mot d'éveil (#gab, @gab, #ia, @ia, …) — match `@` ou `#` indifféremment
        wake_tags = set(self.agent.cfg.WAKE_TAGS or [])
        if wake_tags:
            for match in WAKE_RE.finditer(text):
                if match.group(1).lower() in wake_tags:
                    return True

        # Réponse à un message de GAB
        if tg_msg.reply_to_message and tg_msg.reply_to_message.from_user:
            if tg_msg.reply_to_message.from_user.id == ctx.bot.id:
                return True

        return False

    # ── Sondages : rendu du clavier + traitement d'un clic de vote ────────────

    @staticmethod
    def _build_poll_keyboard(poll: dict) -> InlineKeyboardMarkup:
        rows = [
            [InlineKeyboardButton(
                f"{opt['label']}  ({opt['votes']})",
                callback_data=f"vote:{poll['id']}:{opt['index']}",
            )]
            for opt in poll["options"]
        ]
        return InlineKeyboardMarkup(rows)

    async def _handle_vote_click(self, query) -> None:
        try:
            _, poll_id, idx_str = query.data.split(":", 2)
            option_index = int(idx_str)
        except (ValueError, AttributeError):
            return
        user = query.from_user
        poll = await self.agent.vote(
            poll_id      = poll_id,
            user_id      = str(user.id),
            option_index = option_index,
            username     = user.username or user.first_name or "",
        )
        if not poll:
            return
        try:
            await query.message.edit_text(
                self.agent.polls.format_message(poll),
                parse_mode   = ParseMode.MARKDOWN,
                reply_markup = self._build_poll_keyboard(poll),
            )
        except Exception as exc:
            # "Message is not modified" si l'utilisateur reclique sur la même option
            if "not modified" not in str(exc).lower():
                logger.warning("Edit du sondage impossible : %s", exc)

    # ── Listes : rendu du clavier + traitement d'un clic de claim ─────────────

    @staticmethod
    def _build_list_keyboard(lst: dict) -> InlineKeyboardMarkup:
        rows = []
        for it in lst["items"]:
            if it["claimer_id"]:
                label = f"{it['label']}  ✅ {it['claimer_name'] or '?'}"
            else:
                label = f"{it['label']}  ◻️"
            rows.append([InlineKeyboardButton(
                label,
                callback_data=f"claim:{lst['id']}:{it['index']}",
            )])
        return InlineKeyboardMarkup(rows)

    async def _handle_claim_click(self, query) -> None:
        try:
            _, list_id, idx_str = query.data.split(":", 2)
            item_index = int(idx_str)
        except (ValueError, AttributeError):
            return
        user = query.from_user
        lst, outcome = await self.agent.claim_list_item(
            list_id    = list_id,
            item_index = item_index,
            user_id    = str(user.id),
            user_name  = user.first_name or user.username or "",
        )
        if not lst:
            return
        # Toast d'information selon le résultat. show_alert=False = bandeau
        # bref en haut de l'écran (non bloquant).
        if outcome == "blocked":
            blocker = ""
            for it in lst["items"]:
                if it["index"] == item_index and it["claimer_name"]:
                    blocker = it["claimer_name"]
                    break
            await query.answer(
                text=f"Déjà pris{' par ' + blocker if blocker else ''}.",
                show_alert=False,
            )
            return  # rien à éditer, l'état n'a pas changé
        elif outcome == "claimed":
            await query.answer(text="✅ C'est noté.", show_alert=False)
        elif outcome == "unclaimed":
            await query.answer(text="◻️ Libéré.", show_alert=False)
        try:
            await query.message.edit_text(
                self.agent.lists.format_message(lst),
                parse_mode   = ParseMode.MARKDOWN,
                reply_markup = self._build_list_keyboard(lst),
            )
        except Exception as exc:
            if "not modified" not in str(exc).lower():
                logger.warning("Edit de la liste impossible : %s", exc)
