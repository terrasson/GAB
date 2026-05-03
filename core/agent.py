"""
GabAgent — cerveau central de GAB.
Reçoit un message depuis n'importe quelle plateforme,
le traite avec le LLM configuré et retourne une réponse unifiée.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from config import Config
from llm import make_llm_client
from core.memory import Memory
from core.group_manager import GroupManager
from core.polls import PollManager, parse_sondage
from core.reminders import ReminderManager, parse_rappel, format_fires_at_fr
from core.lists import ListManager, parse_liste
from core.tools import GROUP_TOOLS, DM_TOOLS

logger = logging.getLogger("GAB.agent")

# Localisation FR sans dépendre de la locale système (qui peut manquer sur le VPS)
_WEEKDAYS_FR = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MONTHS_FR = (
    "", "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)
_TZ_PARIS = ZoneInfo("Europe/Paris")


def _now_fr() -> str:
    """Retourne la date/heure courantes en français, ex : 'samedi 2 mai 2026, 21h32 (heure de Paris)'."""
    now = datetime.now(_TZ_PARIS)
    return (
        f"{_WEEKDAYS_FR[now.weekday()]} {now.day} {_MONTHS_FR[now.month]} {now.year}, "
        f"{now.hour:02d}h{now.minute:02d} (heure de Paris)"
    )


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
        "/sondage":     "_cmd_sondage",
        "/rappel":      "_cmd_rappel",
        "/liste":       "_cmd_liste",
    }

    def __init__(self, cfg: Config):
        self.cfg       = cfg
        self.memory    = Memory()
        self.groups    = GroupManager()
        self.polls     = PollManager()
        self.reminders = ReminderManager()
        self.lists     = ListManager()
        self.llm       = make_llm_client(cfg)

    # ── Point d'entrée principal ─────────────────────────────────────────────

    async def handle(self, msg: Message) -> Response:
        logger.info("[%s] %s → %r", msg.platform, msg.username, msg.text[:80])

        # 1. Whitelist : barrière d'accès AVANT toute consommation LLM
        if not self._is_allowed(msg):
            logger.info("🔒 Refusé : %s/%s (groupe %s) — non whitelisté",
                        msg.platform, msg.user_id, msg.group_id)
            if msg.group_id:
                # En groupe : silence (évite la pollution + le name-and-shame)
                return Response(text="")
            return Response(text=(
                "🔒 Cette instance de GAB est privée.\n"
                "Contactez l'administrateur pour obtenir l'accès, "
                "ou self-hostez la vôtre : https://github.com/terrasson/GAB"
            ))

        text = msg.text.strip()

        # 2. Routage vers une commande explicite
        for cmd, method_name in self.COMMANDS.items():
            if text.lower().startswith(cmd):
                arg = text[len(cmd):].strip()
                return await getattr(self, method_name)(msg, arg)

        # 3. Sinon : conversation libre avec le LLM
        return await self._llm_chat(msg, text)

    # ── Whitelist d'accès ────────────────────────────────────────────────────

    def _is_allowed(self, msg: Message) -> bool:
        """Détermine si un message a le droit d'invoquer GAB.

        Règle :
        - Si AUCUNE liste blanche n'est configurée → tout passe (mode dev/perso).
        - Sinon, message autorisé SI :
          * son user_id est dans ALLOWED_USERS (en `<id>` ou `<platform>:<id>`), OU
          * son group_id est dans ALLOWED_GROUPS.
        """
        cfg = self.cfg
        if not cfg.ALLOWED_USERS and not cfg.ALLOWED_GROUPS:
            return True
        if msg.group_id and msg.group_id in cfg.ALLOWED_GROUPS:
            return True
        user_keys = {msg.user_id, f"{msg.platform}:{msg.user_id}"}
        return any(k in cfg.ALLOWED_USERS for k in user_keys)

    # ── Commandes ────────────────────────────────────────────────────────────

    async def _cmd_start(self, msg: Message, _: str) -> Response:
        return Response(
            text=(
                f"🎩 Bonsoir, {msg.username}. Je suis *GAB*, votre majordome virtuel.\n\n"
                "Je peux vous aider à :\n"
                "• 💬 Répondre à vos questions\n"
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
            "`/ask <question>`       — Poser une question au LLM\n"
            "`/creategroup <nom>`    — Créer un groupe de discussion\n"
            "`/invite <user>`        — Inviter un membre dans le groupe courant\n"
            "`/summary`              — Résumer la conversation récente\n"
            "`/clear`                — Effacer l'historique de la conversation\n"
            "`/status`               — État du LLM et des plateformes actives\n"
            "`/members`              — Lister les IDs des membres connus du groupe\n"
            "`/sondage <Q?> <O1>|<O2>|<O3>` — Lancer un vote multi-options\n"
            "`/rappel <YYYY-MM-DD> <HH:MM> <message>` — Programmer un rappel\n"
            "`/liste <Titre> : <Item1>|<Item2>|...` — Liste partagée modifiable\n\n"
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
        conv = self.memory.get(msg.platform, msg.user_id, msg.group_id)
        history = conv.get_history()
        if not history:
            return Response(text="Aucun historique à résumer pour le moment.")

        # On demande au LLM de résumer
        summary_prompt = (
            "Voici une conversation. Fais-en un résumé clair et concis en 5 points maximum :\n\n"
            + "\n".join(f"{m['role'].upper()} : {m['content']}" for m in history)
        )
        result = await self.llm.chat(
            messages=[{"role": "user", "content": summary_prompt}],
            system=self._build_system_prompt(),
        )
        return Response(text=f"📝 *Résumé de la conversation :*\n\n{result.text}")

    async def _cmd_clear(self, msg: Message, _: str) -> Response:
        self.memory.clear(msg.platform, msg.user_id, msg.group_id)
        scope = "du groupe" if msg.group_id else "de la conversation"
        return Response(text=f"🗑️ Historique {scope} effacé. Nouvelle conversation démarrée.")

    async def _cmd_status(self, msg: Message, _: str) -> Response:
        alive = await self.llm.is_alive()
        llm_status = "✅ connecté" if alive else "❌ hors ligne"
        cfg = self.cfg
        lines = [
            f"🤖 LLM `{cfg.LLM_PROVIDER}/{cfg.LLM_MODEL}` — {llm_status}",
            "",
            "📡 *Plateformes actives :*",
            f"  • Telegram : {'✅' if cfg.TELEGRAM_ENABLED else '❌'}",
            f"  • WhatsApp : {'✅' if cfg.WA_ENABLED else '❌'}",
            f"  • Discord  : {'✅' if cfg.DISCORD_ENABLED else '❌'}",
        ]
        return Response(text="\n".join(lines))

    async def _cmd_sondage(self, msg: Message, arg: str) -> Response:
        if not msg.group_id:
            return Response(text="ℹ️ `/sondage` ne fonctionne qu'en groupe.")
        question, options = parse_sondage(arg)
        if len(options) < 2:
            return Response(text=(
                "Usage : `/sondage Question ? Option1 | Option2 | Option3`\n"
                "Au moins 2 options sont requises, séparées par `|`."
            ))
        poll = self.polls.create(
            group_id   = msg.group_id,
            creator_id = msg.user_id,
            question   = question or "Sondage",
            options    = options,
        )
        return Response(
            text        = self.polls.format_message(poll),
            action      = "render_poll",
            action_data = poll,
        )

    async def vote(
        self,
        poll_id: str,
        user_id: str,
        option_index: int,
        username: str = "",
    ) -> dict | None:
        """Point d'entrée appelé par les plateformes sur clic de bouton."""
        return self.polls.vote(poll_id, user_id, option_index, username=username)

    async def _cmd_rappel(self, msg: Message, arg: str) -> Response:
        when, message, error = parse_rappel(arg)
        if error:
            return Response(text=error)
        target_chat = msg.group_id or msg.user_id
        reminder = self.reminders.create(
            platform    = msg.platform,
            target_chat = target_chat,
            creator_id  = msg.user_id,
            fires_at    = when,
            message     = message,
        )
        when_label = format_fires_at_fr(reminder["fires_at"])
        return Response(
            text=f"⏰ C'est noté. Je rappellerai *{message}* le {when_label}."
        )

    async def _cmd_liste(self, msg: Message, arg: str) -> Response:
        if not msg.group_id:
            return Response(text="ℹ️ `/liste` ne fonctionne qu'en groupe.")
        title, items = parse_liste(arg)
        if not items:
            return Response(text=(
                "Usage : `/liste Titre : Item1 | Item2 | Item3`\n"
                "Au moins 1 item est requis, séparés par `|`."
            ))
        lst = self.lists.create(
            group_id   = msg.group_id,
            creator_id = msg.user_id,
            title      = title or "Liste",
            items      = items,
        )
        return Response(
            text        = self.lists.format_message(lst),
            action      = "render_list",
            action_data = lst,
        )

    async def claim_list_item(
        self,
        list_id: str,
        item_index: int,
        user_id: str,
        user_name: str = "",
    ) -> tuple[dict | None, str]:
        """Point d'entrée appelé par les plateformes sur clic de bouton item."""
        return self.lists.claim(list_id, item_index, user_id, user_name)

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
        conv = self.memory.get(msg.platform, msg.user_id, msg.group_id)
        # En groupe : on enregistre l'auteur pour que le LLM sache qui parle
        conv.add("user", text, author=msg.username)

        # Sélection des outils selon le contexte. En groupe : tout (sondages,
        # rappels, …). En DM : seulement les outils qui ont du sens pour un user
        # seul (rappels, mais pas sondages — un sondage exige un groupe).
        tools = GROUP_TOOLS if msg.group_id else DM_TOOLS

        try:
            result = await self.llm.chat(
                messages = conv.get_history(),
                system   = self._build_system_prompt(),
                tools    = tools,
            )
        except Exception as exc:
            logger.error("Erreur LLM : %s", exc)
            return Response(
                text="⚠️ Je ne parviens pas à joindre le LLM pour le moment. "
                     "Vérifiez que le backend configuré est accessible."
            )

        # Diagnostic : ce que le LLM a réellement retourné. Permet de débugger
        # un cas où le LLM "simule" un tool call en texte au lieu d'invoquer.
        tool_names = [tc.name for tc in result.tool_calls] or ["<aucun>"]
        text_preview = (result.text or "")[:120].replace("\n", " ")
        logger.info("LLM result : tools=%s | text=%r", tool_names, text_preview)

        # Le LLM a-t-il décidé d'invoquer un outil ?
        for tc in result.tool_calls:
            if tc.name == "create_poll":
                return self._exec_create_poll(msg, conv, tc, result.text)
            if tc.name == "create_reminder":
                return self._exec_create_reminder(msg, conv, tc, result.text)
            if tc.name == "create_list":
                return self._exec_create_list(msg, conv, tc, result.text)
            logger.warning("Tool call inconnu ignoré : %s", tc.name)

        # Pas d'outil : réponse texte classique
        reply = result.text or ""
        conv.add("assistant", reply)
        return Response(text=reply)

    # ── Exécution des tool calls ─────────────────────────────────────────────

    def _exec_create_poll(self, msg: Message, conv, tool_call, accompanying_text: str) -> Response:
        """Crée un sondage demandé par le LLM via tool calling."""
        args      = tool_call.arguments or {}
        question  = (args.get("question") or "").strip()
        options   = [str(o).strip() for o in (args.get("options") or []) if str(o).strip()]
        if len(options) < 2:
            # Le LLM a appelé create_poll sans assez d'options → on renvoie un texte
            # qui demande au groupe de préciser, plutôt que de poster un sondage cassé.
            fallback = (
                accompanying_text
                or "J'ai besoin d'au moins 2 options proposées par le groupe pour lancer un sondage. "
                   "Quelles options voulez-vous mettre au vote ?"
            )
            conv.add("assistant", fallback)
            return Response(text=fallback)

        poll = self.polls.create(
            group_id   = msg.group_id,
            creator_id = msg.user_id,
            question   = question or "Sondage",
            options    = options,
        )
        # Trace dans la mémoire de groupe pour que le LLM sache qu'il a lancé le sondage
        memo = (accompanying_text + " " if accompanying_text else "") + \
               f"[Sondage lancé : {poll['question']} — options : {', '.join(options)}]"
        conv.add("assistant", memo)
        # Texte affiché aux humains : préambule du LLM (s'il y en a un) + sondage
        body = self.polls.format_message(poll)
        text_out = f"{accompanying_text}\n\n{body}" if accompanying_text else body
        return Response(
            text        = text_out,
            action      = "render_poll",
            action_data = poll,
        )

    def _exec_create_reminder(self, msg: Message, conv, tool_call, accompanying_text: str) -> Response:
        """Programme un rappel demandé par le LLM via tool calling."""
        args     = tool_call.arguments or {}
        fires_at = (args.get("fires_at") or "").strip()
        message  = (args.get("message") or "").strip()

        # Validation : ISO parseable, timezone-aware, dans le futur
        try:
            when = datetime.fromisoformat(fires_at)
        except (ValueError, TypeError):
            fallback = (
                accompanying_text
                or "Je n'ai pas compris la date du rappel. À quelle date et heure exactement ?"
            )
            conv.add("assistant", fallback)
            return Response(text=fallback)

        if when.tzinfo is None:
            # On considère Europe/Paris si le LLM a oublié l'offset
            when = when.replace(tzinfo=_TZ_PARIS)

        if when <= datetime.now(_TZ_PARIS):
            fallback = (
                accompanying_text
                or "Cette date est déjà passée. Pour quand veux-tu le rappel ?"
            )
            conv.add("assistant", fallback)
            return Response(text=fallback)

        if not message:
            fallback = (
                accompanying_text
                or "De quoi veux-tu que je te rappelle exactement ?"
            )
            conv.add("assistant", fallback)
            return Response(text=fallback)

        target_chat = msg.group_id or msg.user_id
        reminder = self.reminders.create(
            platform    = msg.platform,
            target_chat = target_chat,
            creator_id  = msg.user_id,
            fires_at    = when,
            message     = message,
        )
        when_label = format_fires_at_fr(reminder["fires_at"])
        confirm = (
            (accompanying_text + "\n\n" if accompanying_text else "")
            + f"⏰ C'est noté. Je rappellerai *{message}* le {when_label}."
        )
        # Trace dans la mémoire pour que le LLM sache qu'il a programmé le rappel
        conv.add(
            "assistant",
            f"[Rappel programmé : {message} — {when_label}]"
        )
        return Response(text=confirm)

    def _exec_create_list(self, msg: Message, conv, tool_call, accompanying_text: str) -> Response:
        """Crée une liste partagée demandée par le LLM via tool calling."""
        args  = tool_call.arguments or {}
        title = (args.get("title") or "").strip()
        items = [str(i).strip() for i in (args.get("items") or []) if str(i).strip()]
        if not items:
            fallback = (
                accompanying_text
                or "Quels items voulez-vous mettre dans la liste ? Donnez-moi-les "
                   "et je crée la liste."
            )
            conv.add("assistant", fallback)
            return Response(text=fallback)

        lst = self.lists.create(
            group_id   = msg.group_id,
            creator_id = msg.user_id,
            title      = title or "Liste",
            items      = items,
        )
        memo = (accompanying_text + " " if accompanying_text else "") + \
               f"[Liste créée : {lst['title']} — items : {', '.join(items)}]"
        conv.add("assistant", memo)
        body = self.lists.format_message(lst)
        text_out = f"{accompanying_text}\n\n{body}" if accompanying_text else body
        return Response(
            text        = text_out,
            action      = "render_list",
            action_data = lst,
        )

    # ── System prompt enrichi du contexte temporel ───────────────────────────

    def _build_system_prompt(self) -> str:
        """Combine le prompt système éditable avec la date/heure courantes.

        Sans cet ancrage, les LLM hallucinent l'heure (souvent celle de leur
        dataset d'entraînement). En injectant la date/heure réelles à chaque
        appel, GAB répond correctement aux questions temporelles ("on est
        quand ?", "il est quelle heure ?", "quel jour ?").
        """
        return (
            f"{self.cfg.SYSTEM_PROMPT}\n\n"
            f"---\n"
            f"Contexte temporel actuel : {_now_fr()}.\n"
            f"Utilise cette information quand tu réponds à des questions sur "
            f"la date ou l'heure."
        )

    async def close(self) -> None:
        await self.llm.aclose()
