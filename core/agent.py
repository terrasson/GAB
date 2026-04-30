"""
GabAgent — cerveau central de GAB.
Reçoit un message depuis n'importe quelle plateforme,
le traite avec Hermes et retourne une réponse unifiée.
"""

import logging
from dataclasses import dataclass

from config import Config
from llm import HermesClient
from core.memory import Memory
from core.group_manager import GroupManager

logger = logging.getLogger("GAB.agent")


@dataclass
class Message:
    """Représentation unifiée d'un message entrant, quelle que soit la plateforme."""
    platform: str        # "telegram" | "whatsapp" | "discord"
    user_id: str
    username: str
    text: str
    group_id: str | None = None   # ID du groupe/channel si message depuis un groupe
    group_name: str | None = None


@dataclass
class Response:
    """Réponse unifiée retournée à la plateforme."""
    text: str
    action: str | None = None     # action spéciale : "create_group", "invite", "summary"...
    action_data: dict | None = None


class GabAgent:
    """Orchestre le LLM, la mémoire et les actions de gestion de groupe."""

    COMMANDS = {
        "/start":       "_cmd_start",
        "/help":        "_cmd_help",
        "/ask":         "_cmd_ask",
        "/creategroup": "_cmd_creategroup",
        "/invite":      "_cmd_invite",
        "/summary":     "_cmd_summary",
        "/clear":       "_cmd_clear",
        "/status":      "_cmd_status",
        "/members":     "_cmd_members",
    }

    def __init__(self, cfg: Config):
        self.cfg     = cfg
        self.memory  = Memory()
        self.groups  = GroupManager()
        self.hermes  = HermesClient(
            base_url    = cfg.OLLAMA_BASE_URL,
            model       = cfg.HERMES_MODEL,
            max_tokens  = cfg.LLM_MAX_TOKENS,
            temperature = cfg.LLM_TEMPERATURE,
        )

    # ── Point d'entrée principal ─────────────────────────────────────────────

    async def handle(self, msg: Message) -> Response:
        logger.info("[%s] %s → %r", msg.platform, msg.username, msg.text[:80])

        text = msg.text.strip()

        # Routage vers une commande explicite
        for cmd, method_name in self.COMMANDS.items():
            if text.lower().startswith(cmd):
                arg = text[len(cmd):].strip()
                return await getattr(self, method_name)(msg, arg)

        # Sinon : conversation libre avec Hermes
        return await self._llm_chat(msg, text)

    # ── Commandes ────────────────────────────────────────────────────────────

    async def _cmd_start(self, msg: Message, _: str) -> Response:
        return Response(
            text=(
                f"🎩 Bonsoir, {msg.username}. Je suis *GAB*, votre majordome virtuel.\n\n"
                "Je peux vous aider à :\n"
                "• 💬 Répondre à vos questions (Hermes LLM)\n"
                "• 👥 Créer et gérer des groupes de discussion\n"
                "• 📨 Inviter des membres dans vos groupes\n"
                "• 📝 Résumer les conversations\n\n"
                "Tapez `/help` pour voir toutes les commandes."
            )
        )

    async def _cmd_help(self, msg: Message, _: str) -> Response:
        return Response(text=(
            "🎩 *Commandes GAB*\n\n"
            "`/start`                — Accueil\n"
            "`/ask <question>`       — Poser une question à Hermes\n"
            "`/creategroup <nom>`    — Créer un groupe de discussion\n"
            "`/invite <user>`        — Inviter un membre dans le groupe courant\n"
            "`/summary`              — Résumer la conversation récente\n"
            "`/clear`                — Effacer l'historique de la conversation\n"
            "`/status`               — État du LLM et des plateformes actives\n\n"
            "💬 Vous pouvez aussi m'écrire librement."
        ))

    async def _cmd_ask(self, msg: Message, question: str) -> Response:
        if not question:
            return Response(text="Usage : `/ask <votre question>`")
        return await self._llm_chat(msg, question)

    async def _cmd_creategroup(self, msg: Message, name: str) -> Response:
        group_name = name or "Nouveau Groupe"
        group = self.groups.create(
            name      = group_name,
            creator   = msg.user_id,
            platform  = msg.platform,
        )
        logger.info("Groupe créé : %s (%s)", group["id"], msg.platform)
        return Response(
            text=(
                f"✅ Groupe *{group_name}* créé avec succès !\n"
                f"ID interne : `{group['id']}`\n\n"
                "Invitez des membres avec `/invite @pseudo`."
            ),
            action      = "create_group",
            action_data = group,
        )

    async def _cmd_invite(self, msg: Message, target: str) -> Response:
        if not target:
            return Response(text="Usage : `/invite @pseudo` ou `/invite numéro`")
        return Response(
            text        = f"📨 Invitation envoyée à *{target}*.",
            action      = "invite",
            action_data = {"target": target, "group_id": msg.group_id},
        )

    async def _cmd_summary(self, msg: Message, _: str) -> Response:
        conv = self.memory.get(msg.platform, msg.user_id)
        history = conv.get_history()
        if not history:
            return Response(text="Aucun historique à résumer pour le moment.")

        # On demande à Hermes de résumer
        summary_prompt = (
            "Voici une conversation. Fais-en un résumé clair et concis en 5 points maximum :\n\n"
            + "\n".join(f"{m['role'].upper()} : {m['content']}" for m in history)
        )
        result = await self.hermes.chat(
            messages=[{"role": "user", "content": summary_prompt}],
            system=self.cfg.SYSTEM_PROMPT,
        )
        return Response(text=f"📝 *Résumé de la conversation :*\n\n{result}")

    async def _cmd_clear(self, msg: Message, _: str) -> Response:
        self.memory.clear(msg.platform, msg.user_id)
        return Response(text="🗑️ Historique effacé. Nouvelle conversation démarrée.")

    async def _cmd_status(self, msg: Message, _: str) -> Response:
        alive = await self.hermes.is_alive()
        hermes_status = "✅ connecté" if alive else "❌ hors ligne"
        cfg = self.cfg
        lines = [
            f"🤖 Hermes (`{cfg.HERMES_MODEL}`) — {hermes_status}",
            f"🔗 Ollama : `{cfg.OLLAMA_BASE_URL}`",
            "",
            "📡 *Plateformes actives :*",
            f"  • Telegram : {'✅' if cfg.TELEGRAM_ENABLED else '❌'}",
            f"  • WhatsApp : {'✅' if cfg.WA_ENABLED else '❌'}",
            f"  • Discord  : {'✅' if cfg.DISCORD_ENABLED else '❌'}",
        ]
        return Response(text="\n".join(lines))

    async def _cmd_members(self, msg: Message, _: str) -> Response:
        if not msg.group_id:
            return Response(text="ℹ️ `/members` doit être utilisé dans un groupe.")
        group = self.groups.get(msg.group_id)
        if not group or not group.get("members"):
            return Response(text="Aucun membre enregistré pour le moment.")
        info = group.get("members_info", {})
        lines = [f"👥 *Membres connus de {group['name']}* :"]
        for uid in group["members"]:
            uname = info.get(uid, {}).get("username") or "—"
            lines.append(f"  • `{uid}` — {uname}")
        return Response(text="\n".join(lines))

    # ── Conversation LLM ─────────────────────────────────────────────────────

    async def _llm_chat(self, msg: Message, text: str) -> Response:
        conv = self.memory.get(msg.platform, msg.user_id)
        conv.add("user", text)

        try:
            reply = await self.hermes.chat(
                messages = conv.get_history(),
                system   = self.cfg.SYSTEM_PROMPT,
            )
            conv.add("assistant", reply)
            return Response(text=reply)
        except Exception as exc:
            logger.error("Erreur Hermes : %s", exc)
            return Response(
                text="⚠️ Je ne parviens pas à joindre Hermes pour le moment. "
                     "Vérifiez qu'Ollama tourne bien sur le serveur."
            )

    async def close(self) -> None:
        await self.hermes.aclose()
