"""
Nudges — relance proactive des décisions abandonnées (palier 2.3).

Distinction avec le palier 2.2 (intent.py) :
- 2.2 = scan sur message en cours, GAB *propose* sur intention claire.
- 2.3 = scan PÉRIODIQUE sur l'état des objets du groupe (sondages, listes,
  événements), GAB *relance* sur décision pendante abandonnée.

Trois heuristiques implémentées :
- **2.3.a — Sondage sans tranche claire** : poll ouvert depuis plus de
  `NUDGE_POLL_AGE_HOURS` (défaut 24) avec ratio max/total <
  `NUDGE_POLL_TRANCHE_RATIO` (défaut 0.6).
- **2.3.b — Événement imminent** : event non annulé dont `starts_at` tombe
  dans `[now, now + NUDGE_EVENT_HORIZON_HOURS]` (défaut 24h). Ping de
  confirmation unique, l'anti-doublon `nudges_sent` garantit qu'on ne
  pingue qu'une fois par event.
- **2.3.c — Liste mi-claimée** : liste non close, créée il y a >
  `NUDGE_LIST_AGE_HOURS` (défaut 48), avec ratio claimed/total <
  `NUDGE_LIST_CLAIM_RATIO` (défaut 0.5).

Garde-fous (mêmes que 2.2 + un de plus) :
1. Le groupe doit être whitelisté (sinon GAB ne devrait pas y parler du tout).
2. `intent_enabled` ON (le `/intent off` désactive aussi les nudges).
3. Cooldown global respecté (`GroupSettings.cooldown_ok`).
4. **Anti-doublon** : un même objet n'est nudgé qu'UNE fois (table
   `nudges_sent`, PK = `(target_type, target_id)`). Sinon GAB harcellerait
   un poll abandonné toutes les 30 minutes.

Coût LLM : 1 appel par candidat (rare : ~0-3 par jour pour un groupe
actif, toutes heuristiques confondues). La détection elle-même est
purement SQL, gratuite.
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


# ── Heuristique 2 : événement imminent ─────────────────────────────────────


def find_imminent_events() -> list[dict]:
    """Retourne les événements candidats à un nudge de confirmation :
    - non annulés (`cancelled_at IS NULL`)
    - `starts_at` dans `[now, now + NUDGE_EVENT_HORIZON_HOURS]`
    - jamais nudgés (absent de `nudges_sent` avec target_type='event')

    Renvoie : {id, group_id, title, starts_at, location}.
    """
    horizon_h = _env_int("NUDGE_EVENT_HORIZON_HOURS", 24)
    now       = datetime.now(timezone.utc)
    now_iso   = now.isoformat()
    cutoff    = (now + timedelta(hours=horizon_h)).isoformat()

    with connection() as c:
        rows = c.execute(
            "SELECT e.id, e.group_id, e.title, e.starts_at, e.location "
            "FROM events e "
            "LEFT JOIN nudges_sent n "
            "  ON n.target_type='event' AND n.target_id=e.id "
            "WHERE e.cancelled_at IS NULL "
            "  AND e.starts_at >= ? "
            "  AND e.starts_at <= ? "
            "  AND n.target_id IS NULL "
            "ORDER BY e.starts_at ASC",
            (now_iso, cutoff),
        ).fetchall()

    return [
        {
            "id":         r["id"],
            "group_id":   r["group_id"],
            "title":      r["title"],
            "starts_at":  r["starts_at"],
            "location":   r["location"] or "",
        }
        for r in rows
    ]


_NUDGE_EVENT_SYSTEM_PROMPT = (
    "Tu es GAB, concierge-agent d'un groupe humain. On t'appelle pour "
    "confirmer un événement qui approche. Ton message DOIT :\n"
    "- Être très court (1-2 phrases).\n"
    "- Rappeler l'événement et son horaire.\n"
    "- Inviter à confirmer SANS forcer.\n"
    "- Se terminer par une question fermée (oui/non, tout le monde est OK ?).\n"
    "- Ne PAS être servile, ne PAS s'excuser.\n"
    "Tu réponds UNIQUEMENT par le texte, sans préfixe, sans guillemets. "
    "Le système ajoutera 💡 devant."
)


async def generate_event_nudge(llm, event: dict) -> str:
    """Demande au LLM un message de confirmation court pour un event imminent.

    Fallback déterministe si LLM down.
    """
    from core.events import format_event_when_fr
    when = format_event_when_fr(event["starts_at"])
    location_str = f", {event['location']}" if event["location"] else ""
    user_msg = (
        f"Événement à venir dans un groupe.\n"
        f"Titre : « {event['title']} »\n"
        f"Quand : {when}{location_str}.\n"
        f"Formule UN message court qui invite le groupe à confirmer que "
        f"tout le monde est toujours partant."
    )
    try:
        result = await llm.chat(
            messages=[{"role": "user", "content": user_msg}],
            system=_NUDGE_EVENT_SYSTEM_PROMPT,
        )
        text = (result.text or "").strip()
        if text:
            return text
    except Exception as exc:
        logger.warning("LLM indisponible pour event nudge — fallback : %s", exc)

    base = f"Rappel : *{event['title']}* {when}{location_str}."
    return f"{base} Tout le monde est toujours OK ?"


# ── Heuristique 3 : liste mi-claimée ───────────────────────────────────────


def find_unclaimed_lists() -> list[dict]:
    """Retourne les listes candidates à un nudge :
    - non closes (`closed_at IS NULL`)
    - créées il y a > `NUDGE_LIST_AGE_HOURS`
    - jamais nudgées (absent de `nudges_sent` avec target_type='list')
    - ratio claimed/total < `NUDGE_LIST_CLAIM_RATIO`
    - au moins 1 item libre (sinon rien à relancer)

    Renvoie : {id, group_id, title, total, claimed, free_labels}.
    """
    age_h     = _env_int("NUDGE_LIST_AGE_HOURS", 48)
    ratio_max = _env_float("NUDGE_LIST_CLAIM_RATIO", 0.5)
    cutoff    = (datetime.now(timezone.utc) - timedelta(hours=age_h)).isoformat()

    candidates: list[dict] = []
    with connection() as c:
        rows = c.execute(
            "SELECT l.id, l.group_id, l.title "
            "FROM lists l "
            "LEFT JOIN nudges_sent n "
            "  ON n.target_type='list' AND n.target_id=l.id "
            "WHERE l.closed_at IS NULL "
            "  AND l.created_at <= ? "
            "  AND n.target_id IS NULL "
            "ORDER BY l.created_at ASC",
            (cutoff,),
        ).fetchall()

        for r in rows:
            list_id  = r["id"]
            group_id = r["group_id"]
            title    = r["title"]

            items = c.execute(
                "SELECT label, claimer_id FROM list_items "
                "WHERE list_id=? ORDER BY item_index ASC",
                (list_id,),
            ).fetchall()
            total   = len(items)
            if total == 0:
                continue
            claimed = sum(1 for i in items if i["claimer_id"] is not None)
            ratio   = claimed / total
            if ratio >= ratio_max:
                continue
            free_labels = [i["label"] for i in items if i["claimer_id"] is None]
            if not free_labels:
                continue

            candidates.append({
                "id":          list_id,
                "group_id":    group_id,
                "title":       title or "Liste",
                "total":       total,
                "claimed":     claimed,
                "free_labels": free_labels,
            })

    return candidates


_NUDGE_LIST_SYSTEM_PROMPT = (
    "Tu es GAB, concierge-agent d'un groupe humain. On t'appelle pour "
    "relancer DISCRÈTEMENT une liste partagée à moitié vide. Ton message "
    "DOIT :\n"
    "- Être très court (1-2 phrases).\n"
    "- Rappeler le titre de la liste et qu'il reste des items à se "
    "  répartir (cite-en au plus 3, exactement comme fournis).\n"
    "- Inviter sans forcer (préfère « qui prend… ? » à « il faut… »).\n"
    "- Ne PAS inventer d'items qui ne sont pas dans la liste fournie.\n"
    "- Ne PAS s'excuser, ne PAS être servile.\n"
    "Tu réponds UNIQUEMENT par le texte, sans préfixe, sans guillemets. "
    "Le système ajoutera 💡 devant."
)


async def generate_list_nudge(llm, lst: dict) -> str:
    """Demande au LLM un message de relance court pour une liste mi-claimée.

    Fallback déterministe si LLM down.
    """
    free_preview = ", ".join(lst["free_labels"][:3])
    if len(lst["free_labels"]) > 3:
        free_preview += "…"
    user_msg = (
        f"Liste partagée à moitié vide dans un groupe.\n"
        f"Titre : « {lst['title']} »\n"
        f"État : {lst['claimed']}/{lst['total']} items pris.\n"
        f"Items encore libres (ne cite QUE ceux-là) : {free_preview}.\n"
        f"Formule UNE relance courte qui invite le groupe à se répartir "
        f"les items restants."
    )
    try:
        result = await llm.chat(
            messages=[{"role": "user", "content": user_msg}],
            system=_NUDGE_LIST_SYSTEM_PROMPT,
        )
        text = (result.text or "").strip()
        if text:
            return text
    except Exception as exc:
        logger.warning("LLM indisponible pour list nudge — fallback : %s", exc)

    remaining = lst["total"] - lst["claimed"]
    return (
        f"Sur la liste *{lst['title']}*, il reste {remaining} item"
        f"{'s' if remaining > 1 else ''} à se répartir "
        f"({free_preview}). Qui prend quoi ?"
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
        # 3 sources de candidats, dispatchées dans le même cycle. Tous les
        # garde-fous (intent_enabled, cooldown, anti-doublon) sont identiques.
        sources = (
            ("poll",  find_stalled_polls,    generate_poll_nudge),
            ("event", find_imminent_events,  generate_event_nudge),
            ("list",  find_unclaimed_lists,  generate_list_nudge),
        )
        for target_type, finder, generator in sources:
            candidates = finder()
            if not candidates:
                continue
            logger.info("💡 %d %s candidat(s) au nudge", len(candidates), target_type)
            for cand in candidates:
                await self._process_candidate(target_type, cand, generator)

    async def _process_candidate(self, target_type, cand, generator) -> None:
        group_id = cand["group_id"]
        settings = self.settings.get(group_id)
        if not settings["intent_enabled"]:
            logger.info("💡 nudge skip %s/%s : intent OFF", target_type, group_id)
            # On marque sent pour ne pas re-tester chaque tick.
            mark_nudge_sent(target_type, cand["id"], group_id)
            return
        if not self.settings.cooldown_ok(group_id):
            logger.info("💡 nudge skip %s/%s : cooldown actif", target_type, group_id)
            return

        text = await generator(self.llm, cand)
        full = f"💡 {text}"
        try:
            await self.dispatch(self.platform, group_id, full)
        except Exception as exc:
            logger.error("💡 dispatch nudge échoué (%s/%s) : %s",
                         target_type, group_id, exc)
            # On NE marque PAS sent → retry au prochain tick.
            return

        mark_nudge_sent(target_type, cand["id"], group_id)
        self.settings.mark_intent_fired(group_id)
        logger.info("💡 nudge envoyé : %s=%s group=%s",
                    target_type, cand["id"], group_id)
