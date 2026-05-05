"""
Nudges — relance proactive des décisions abandonnées (palier 2.3).

Distinction avec le palier 2.2 (intent.py) :
- 2.2 = scan sur message en cours, GAB *propose* sur intention claire.
- 2.3 = scan PÉRIODIQUE sur l'état des objets du groupe (sondages, listes,
  événements), GAB *relance* sur décision pendante abandonnée.

Heuristique v1 implémentée : **sondage sans tranche claire**. Un sondage
ouvert depuis plus de `NUDGE_POLL_AGE_HOURS` heures (défaut 24) avec
ratio max/total < `NUDGE_POLL_TRANCHE_RATIO` (défaut 0.6) est candidat.
Heuristiques 2 (événement imminent) et 3 (liste mi-claimée) à venir.

Garde-fous (mêmes que 2.2 + un de plus) :
1. Le groupe doit être whitelisté (sinon GAB ne devrait pas y parler du tout).
2. `intent_enabled` ON (le `/intent off` désactive aussi les nudges).
3. Cooldown global respecté (`GroupSettings.cooldown_ok`).
4. **Anti-doublon** : un même sondage n'est nudgé qu'UNE fois (table
   `nudges_sent`). Sinon GAB harcellerait un poll abandonné toutes les 30
   minutes.

Coût LLM : 1 appel par poll candidat (rare : ~0-3 par jour pour un
groupe actif). La détection elle-même est purement SQL, gratuite.
"""

import os
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Awaitable, Callable

from core.storage import connection
from core.intents import GroupSettings

logger = logging.getLogger("GAB.nudges")

DispatchFn = Callable[[str, str, str], Awaitable[None]]
# (platform, target_chat, text) -> None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_int(key: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(key, str(default))))
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


# ── Heuristique 1 : sondage sans tranche claire ────────────────────────────


def find_stalled_polls() -> list[dict]:
    """Retourne les sondages candidats à un nudge :
    - non clôturés (`closed_at IS NULL`)
    - créés il y a > NUDGE_POLL_AGE_HOURS
    - n'ont JAMAIS été nudgés (absent de `nudges_sent`)
    - ratio max/total des votes < NUDGE_POLL_TRANCHE_RATIO
      (ou pas de vote du tout — ratio = 0)

    Renvoie une liste de dicts : {id, group_id, question, total_votes,
    leader_label, leader_votes, options}.
    """
    age_h     = _env_int("NUDGE_POLL_AGE_HOURS", 24)
    ratio_max = _env_float("NUDGE_POLL_TRANCHE_RATIO", 0.6)

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=age_h)).isoformat()

    candidates: list[dict] = []
    with connection() as c:
        rows = c.execute(
            "SELECT p.id, p.group_id, p.question "
            "FROM polls p "
            "LEFT JOIN nudges_sent n "
            "  ON n.target_type='poll' AND n.target_id=p.id "
            "WHERE p.closed_at IS NULL "
            "  AND p.created_at <= ? "
            "  AND n.target_id IS NULL "
            "ORDER BY p.created_at ASC",
            (cutoff,),
        ).fetchall()

        for r in rows:
            poll_id  = r["id"]
            group_id = r["group_id"]
            question = r["question"]

            # Compte total + ventilation par option
            opts = c.execute(
                "SELECT po.option_index, po.label, "
                "  (SELECT COUNT(*) FROM poll_votes pv "
                "   WHERE pv.poll_id=po.poll_id "
                "     AND pv.option_index=po.option_index) AS votes "
                "FROM poll_options po "
                "WHERE po.poll_id=? "
                "ORDER BY votes DESC, po.option_index ASC",
                (poll_id,),
            ).fetchall()
            options = [{"label": o["label"], "votes": o["votes"]} for o in opts]
            total = sum(o["votes"] for o in options) if options else 0

            if total == 0:
                ratio = 0.0
                leader = options[0] if options else {"label": "?", "votes": 0}
            else:
                leader = options[0]
                ratio = leader["votes"] / total

            if ratio >= ratio_max:
                # Tranche claire : pas besoin de relancer.
                continue

            candidates.append({
                "id":            poll_id,
                "group_id":      group_id,
                "question":      question,
                "total_votes":   total,
                "leader_label":  leader["label"],
                "leader_votes":  leader["votes"],
                "options":       options,
            })

    return candidates


def mark_nudge_sent(target_type: str, target_id: str, group_id: str) -> None:
    """Note qu'un objet a été nudgé. Idempotent (PK)."""
    with connection() as c:
        c.execute(
            "INSERT OR IGNORE INTO nudges_sent "
            "(target_type, target_id, group_id, sent_at) "
            "VALUES (?, ?, ?, ?)",
            (target_type, target_id, group_id, _now()),
        )


# ── Génération du texte de relance ─────────────────────────────────────────


_NUDGE_SYSTEM_PROMPT = (
    "Tu es GAB, concierge-agent d'un groupe humain. On t'appelle pour "
    "relancer DISCRÈTEMENT une décision laissée en suspens. Ton message "
    "DOIT :\n"
    "- Être très court (1-2 phrases, pas de paragraphe).\n"
    "- Rappeler brièvement le sujet.\n"
    "- Inviter à trancher SANS forcer (préfère « vous voulez que… ? » à "
    "  « il faut… »).\n"
    "- Se terminer par une question fermée, pour que la réponse soit "
    "  binaire et facile.\n"
    "- Ne PAS lister toutes les options ni les chiffres en détail.\n"
    "- Ne PAS s'excuser, ne PAS être servile.\n"
    "Tu réponds UNIQUEMENT par le texte de relance, sans préfixe, sans "
    "guillemets, sans introduction. Le système ajoutera 💡 devant."
)


async def generate_poll_nudge(llm, poll: dict) -> str:
    """Demande au LLM un message de relance court pour un sondage abandonné.

    Le LLM ne touche PAS aux options ni aux votes — c'est une formulation
    pure. Si l'appel LLM échoue, on retombe sur un texte de fallback
    purement synthétisé en code (le bot doit fonctionner même LLM down).
    """
    options_str = ", ".join(o["label"] for o in poll["options"]) or "options inconnues"
    leader_str = (
        f"{poll['leader_label']} ({poll['leader_votes']}/{poll['total_votes']})"
        if poll["total_votes"] > 0
        else "personne n'a voté pour le moment"
    )
    user_msg = (
        f"Sondage en suspens depuis plus de 24h dans un groupe.\n"
        f"Question : « {poll['question'] or '(sans question)'} »\n"
        f"Options : {options_str}\n"
        f"État : {leader_str}.\n"
        f"Formule UNE relance courte, polie, qui invite le groupe à trancher "
        f"ou à laisser GAB clôturer sur l'option en tête."
    )
    try:
        result = await llm.chat(
            messages=[{"role": "user", "content": user_msg}],
            system=_NUDGE_SYSTEM_PROMPT,
        )
        text = (result.text or "").strip()
        if text:
            return text
    except Exception as exc:
        logger.warning("LLM indisponible pour nudge — fallback texte : %s", exc)

    # Fallback déterministe : pas de LLM, on forge.
    if poll["total_votes"] == 0:
        return (
            f"Le sondage *{poll['question'] or 'en cours'}* attend toujours "
            f"des votes — vous voulez qu'on le ferme ou vous tranchez ?"
        )
    return (
        f"Le sondage *{poll['question'] or 'en cours'}* n'est pas tranché "
        f"({poll['leader_label']} en tête). Je le clôture sur cette option ?"
    )


# ── Scheduler asyncio ──────────────────────────────────────────────────────


class NudgeScheduler:
    """Boucle asyncio qui poll périodiquement les heuristiques de nudge.

    `interval` : intervalle entre deux ticks en secondes (défaut 30 min).
    `dispatch` : callback (platform, target_chat, text) -> coroutine, qui
    envoie le texte au groupe via la plateforme idoine. Réutilisé du
    système de rappels.
    """

    def __init__(
        self,
        llm,
        settings: GroupSettings,
        dispatch: DispatchFn,
        interval: int | None = None,
        platform: str = "telegram",
    ):
        self.llm       = llm
        self.settings  = settings
        self.dispatch  = dispatch
        self.interval  = interval or _env_int("NUDGE_INTERVAL_SECONDS", 30 * 60)
        self.platform  = platform
        self._stop     = asyncio.Event()

    async def run(self) -> None:
        logger.info("💡 Scheduler de nudges démarré (poll toutes les %ds)", self.interval)
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception as exc:
                logger.exception("Tick nudge en erreur : %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass
        logger.info("💡 Scheduler de nudges arrêté")

    def stop(self) -> None:
        self._stop.set()

    async def _tick(self) -> None:
        candidates = find_stalled_polls()
        if not candidates:
            return
        logger.info("💡 %d sondage(s) candidat(s) au nudge", len(candidates))
        for poll in candidates:
            group_id = poll["group_id"]
            settings = self.settings.get(group_id)
            if not settings["intent_enabled"]:
                logger.info("💡 nudge skip %s : intent OFF", group_id)
                # On marque quand même sent pour ne pas re-tester chaque tick.
                mark_nudge_sent("poll", poll["id"], group_id)
                continue
            if not self.settings.cooldown_ok(group_id):
                logger.info("💡 nudge skip %s : cooldown actif", group_id)
                continue

            text = await generate_poll_nudge(self.llm, poll)
            full = f"💡 {text}"
            try:
                await self.dispatch(self.platform, group_id, full)
            except Exception as exc:
                logger.error("💡 dispatch nudge échoué pour %s : %s", group_id, exc)
                # On NE marque PAS sent → retry au prochain tick.
                continue

            mark_nudge_sent("poll", poll["id"], group_id)
            self.settings.mark_intent_fired(group_id)
            logger.info("💡 nudge envoyé : poll=%s group=%s", poll["id"], group_id)
