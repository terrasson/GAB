"""
Récap multi-jours / multi-membres (palier 2.4).

Combine les sources structurées (faits, polls, events, lists) avec une
synthèse narrative LLM des messages récents pour produire un message
markdown en 3 sections :

- ✅ *Acté* : sondages clos sur la fenêtre + events à venir + faits
  sémantiques du groupe (mémoire 2.1).
- 💬 *Discuté* : synthèse narrative LLM des échanges sur la fenêtre.
- ❓ *Reste à trancher* : sondages ouverts non tranchés + listes non
  closes mi-claimées + (events à venir non confirmés sont déjà dans
  Acté ; on ne double pas).

1 appel LLM par /recap (uniquement la synthèse narrative). Tout le
reste est SQL pur. Si LLM down, fallback sur un message court qui
indique le volume d'échanges sans synthèse.

Limite implicite : la mémoire conversationnelle (`core/memory.py`)
fait un trim FIFO à `MAX_HISTORY = 20` messages par conversation.
Le récap narratif se base donc sur les ~20 derniers messages
disponibles dans la fenêtre, peu importe la durée demandée. Pour
des groupes très actifs, on perd les messages anciens. À retravailler
si le besoin se confirme (cf. open_threads).
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from core.storage import connection
from core.facts import FactStore
from core.events import format_event_when_fr

logger = logging.getLogger("GAB.recap")


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


_RECAP_NARRATIVE_PROMPT = (
    "Tu es GAB, concierge-agent d'un groupe humain. On te demande une "
    "synthèse NARRATIVE des échanges récents du groupe. Ton message DOIT :\n"
    "- Être très court (3-4 phrases max).\n"
    "- Identifier les SUJETS principaux abordés, sans citer chaque message.\n"
    "- Mentionner qui a proposé quoi quand c'est notable.\n"
    "- Ne PAS lister les décisions actées ni les sujets en suspens "
    "  (le système les ajoute séparément).\n"
    "- Ne PAS halluciner : si peu de signal, dis-le brièvement « Peu "
    "  d'échange sur la période ».\n"
    "Tu réponds UNIQUEMENT par le texte du paragraphe, sans préfixe, "
    "sans titre, sans guillemets."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Lectures SQL ───────────────────────────────────────────────────────────


def _fetch_recent_messages(group_id: str, since_iso: str) -> list[dict]:
    """Messages user du groupe sur la fenêtre. Cap implicite à MAX_HISTORY."""
    conv_key = f"group:{group_id}"
    with connection() as c:
        rows = c.execute(
            "SELECT role, content, author, created_at FROM messages "
            "WHERE conv_key=? AND created_at >= ? AND role='user' "
            "ORDER BY id ASC",
            (conv_key, since_iso),
        ).fetchall()
    return [
        {
            "author":     r["author"] or "Anonyme",
            "content":    r["content"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def _fetch_closed_polls(group_id: str, since_iso: str) -> list[dict]:
    """Sondages clôturés sur la fenêtre, avec leur option gagnante."""
    result: list[dict] = []
    with connection() as c:
        rows = c.execute(
            "SELECT id, question FROM polls "
            "WHERE group_id=? AND closed_at IS NOT NULL "
            "  AND closed_at >= ? "
            "ORDER BY closed_at DESC",
            (group_id, since_iso),
        ).fetchall()
        for r in rows:
            opts = c.execute(
                "SELECT po.label, "
                "  (SELECT COUNT(*) FROM poll_votes pv "
                "   WHERE pv.poll_id=po.poll_id "
                "     AND pv.option_index=po.option_index) AS votes "
                "FROM poll_options po "
                "WHERE po.poll_id=? "
                "ORDER BY votes DESC, po.option_index ASC LIMIT 1",
                (r["id"],),
            ).fetchall()
            leader = opts[0]["label"] if opts else "?"
            result.append({"question": r["question"], "leader": leader})
    return result


def _fetch_open_polls(group_id: str) -> list[dict]:
    """Sondages encore ouverts (pas de clôture)."""
    result: list[dict] = []
    with connection() as c:
        rows = c.execute(
            "SELECT id, question FROM polls "
            "WHERE group_id=? AND closed_at IS NULL "
            "ORDER BY created_at DESC",
            (group_id,),
        ).fetchall()
        for r in rows:
            opts = c.execute(
                "SELECT po.label, "
                "  (SELECT COUNT(*) FROM poll_votes pv "
                "   WHERE pv.poll_id=po.poll_id "
                "     AND pv.option_index=po.option_index) AS votes "
                "FROM poll_options po "
                "WHERE po.poll_id=? "
                "ORDER BY po.option_index ASC",
                (r["id"],),
            ).fetchall()
            total = sum(o["votes"] for o in opts)
            result.append({
                "question":      r["question"],
                "total_votes":   total,
                "options_count": len(opts),
            })
    return result


def _fetch_upcoming_events(group_id: str) -> list[dict]:
    """Events à venir (non annulés)."""
    now_iso = _now().isoformat()
    with connection() as c:
        rows = c.execute(
            "SELECT title, starts_at, location FROM events "
            "WHERE group_id=? AND cancelled_at IS NULL "
            "  AND starts_at >= ? "
            "ORDER BY starts_at ASC LIMIT 10",
            (group_id, now_iso),
        ).fetchall()
    return [
        {
            "title":     r["title"],
            "starts_at": r["starts_at"],
            "location":  r["location"] or "",
        }
        for r in rows
    ]


def _fetch_open_lists(group_id: str) -> list[dict]:
    """Listes non closes, avec compteurs claimed/total."""
    result: list[dict] = []
    with connection() as c:
        rows = c.execute(
            "SELECT id, title FROM lists "
            "WHERE group_id=? AND closed_at IS NULL "
            "ORDER BY created_at DESC LIMIT 10",
            (group_id,),
        ).fetchall()
        for r in rows:
            items = c.execute(
                "SELECT claimer_id FROM list_items WHERE list_id=?",
                (r["id"],),
            ).fetchall()
            total   = len(items)
            claimed = sum(1 for i in items if i["claimer_id"] is not None)
            result.append({
                "title":   r["title"] or "Liste",
                "total":   total,
                "claimed": claimed,
            })
    return result


# ── Synthèse narrative ─────────────────────────────────────────────────────


async def _generate_narrative(llm, messages: list[dict], days: int) -> str:
    """Demande au LLM une synthèse narrative courte. Fallback si LLM down."""
    if not messages:
        return f"_Peu d'activité sur les {days} derniers jours._"

    excerpts = "\n".join(
        f"- [{m['author']}] {m['content'][:200]}"
        for m in messages[-30:]   # cap raisonnable pour le coût LLM
    )
    user_msg = (
        f"Voici les messages récents d'un groupe humain sur les {days} "
        f"derniers jours :\n\n{excerpts}\n\n"
        f"Synthétise les sujets principaux abordés en 3-4 phrases."
    )
    try:
        result = await llm.chat(
            messages=[{"role": "user", "content": user_msg}],
            system=_RECAP_NARRATIVE_PROMPT,
        )
        text = (result.text or "").strip()
        if text:
            return text
    except Exception as exc:
        logger.warning("LLM indisponible pour recap narratif — fallback : %s", exc)

    return f"_Synthèse indisponible. {len(messages)} message(s) échangé(s)._"


# ── Composition ────────────────────────────────────────────────────────────


def _format_acted_section(
    facts: list[dict],
    polls_closed: list[dict],
    events: list[dict],
) -> list[str]:
    lines: list[str] = []
    for p in polls_closed:
        lines.append(f"- 🗳 {p['question']} → *{p['leader']}*")
    for e in events:
        when = format_event_when_fr(e["starts_at"])
        loc  = f", {e['location']}" if e["location"] else ""
        lines.append(f"- 📅 {e['title']} — {when}{loc}")
    # On ne montre que les 8 faits les plus récents pour ne pas noyer.
    # Les faits sont déjà triés par clé ; pour cibler les récents, on
    # re-trie ici par updated_at desc.
    recent_facts = sorted(facts, key=lambda f: f["updated_at"], reverse=True)[:8]
    for f in recent_facts:
        lines.append(f"- 🧠 `{f['key']}` = {f['value']}")
    return lines


def _format_pending_section(
    polls_open: list[dict],
    lists_open: list[dict],
) -> list[str]:
    lines: list[str] = []
    for p in polls_open:
        if p["total_votes"] == 0:
            status = "0 vote"
        else:
            status = f"{p['total_votes']} votes / {p['options_count']} options"
        lines.append(f"- 🗳 {p['question']} _({status})_")
    for l in lists_open:
        if l["total"] == 0:
            continue
        if l["claimed"] < l["total"]:
            lines.append(
                f"- 📝 {l['title']} _({l['claimed']}/{l['total']} pris)_"
            )
    return lines


# ── Récap spontané (palier 2.4.b) ──────────────────────────────────────────


def _recap_window_now() -> tuple[bool, str | None]:
    """Si on est dans la fenêtre de tir hebdo (jour+heure cibles), retourne
    `(True, "YYYY-WW")` (tag ISO de la semaine en cours). Sinon
    `(False, None)`.

    Tunables :
    - `RECAP_AUTO_TZ`        (défaut Europe/Paris)
    - `RECAP_AUTO_WEEKDAY`   (défaut 6 = dimanche, convention Python : 0=lundi)
    - `RECAP_AUTO_HOUR_LOCAL`(défaut 19, on tire dès qu'on est ≥ cette heure)
    """
    tz_name        = os.getenv("RECAP_AUTO_TZ", "Europe/Paris")
    target_weekday = _env_int("RECAP_AUTO_WEEKDAY", 6)
    target_hour    = _env_int("RECAP_AUTO_HOUR_LOCAL", 19)

    try:
        now_local = datetime.now(ZoneInfo(tz_name))
    except Exception:
        now_local = datetime.now(timezone.utc)

    if now_local.weekday() != target_weekday:
        return (False, None)
    if now_local.hour < target_hour:
        return (False, None)
    iso = now_local.isocalendar()
    return (True, f"{iso.year:04d}-W{iso.week:02d}")


def find_due_recap_groups() -> list[dict]:
    """Si on est dimanche soir (configurable), retourne les groupes qui
    méritent un récap auto :
    - activité ≥ `RECAP_AUTO_MIN_MESSAGES` messages users sur 7 jours
    - pas encore récapés cette semaine ISO (anti-doublon `nudges_sent`
      avec `target_id = f"{group_id}:weekly:{YYYY-WW}"`)

    Renvoie : `[{id, group_id, platform, week_tag}, ...]`.
    Hors fenêtre de tir : liste vide.
    """
    in_window, week_tag = _recap_window_now()
    if not in_window or not week_tag:
        return []

    min_msg = _env_int("RECAP_AUTO_MIN_MESSAGES", 5)
    since   = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    candidates: list[dict] = []
    with connection() as c:
        rows = c.execute(
            "SELECT id, platform FROM groups ORDER BY id ASC"
        ).fetchall()

        for r in rows:
            group_id  = r["id"]
            platform  = r["platform"]
            target_id = f"{group_id}:weekly:{week_tag}"

            already = c.execute(
                "SELECT 1 FROM nudges_sent "
                "WHERE target_type='recap' AND target_id=?",
                (target_id,),
            ).fetchone()
            if already:
                continue

            count_row = c.execute(
                "SELECT COUNT(*) AS c FROM messages "
                "WHERE conv_key=? AND role='user' AND created_at>=?",
                (f"group:{group_id}", since),
            ).fetchone()
            if count_row["c"] < min_msg:
                continue

            candidates.append({
                "id":       target_id,
                "group_id": group_id,
                "platform": platform,
                "week_tag": week_tag,
            })

    return candidates


async def generate_weekly_recap(llm, cand: dict) -> str:
    """Adapter pour `_process_candidate` du `NudgeScheduler`. Construit
    un récap 7 jours pour le groupe candidat et préserve son préfixe
    📚 (sans ajout de 💡 — le scheduler skipera le préfixe pour
    `target_type='recap'`)."""
    return await build_recap(cand["group_id"], 7, llm)


async def build_recap(group_id: str, days: int, llm) -> str:
    """Construit un récap markdown des `days` derniers jours.

    1 appel LLM (synthèse narrative). Le reste est SQL pur. Bornes :
    1 ≤ days ≤ 90.
    """
    days  = max(1, min(days, 90))
    since = (_now() - timedelta(days=days)).isoformat()

    facts        = FactStore().list_for_group(group_id)
    polls_closed = _fetch_closed_polls(group_id, since)
    polls_open   = _fetch_open_polls(group_id)
    events       = _fetch_upcoming_events(group_id)
    lists_open   = _fetch_open_lists(group_id)
    messages     = _fetch_recent_messages(group_id, since)

    narrative = await _generate_narrative(llm, messages, days)

    out: list[str] = [f"📚 *Récap des {days} derniers jours*", ""]

    acted = _format_acted_section(facts, polls_closed, events)
    if acted:
        out += ["✅ *Acté*"] + acted + [""]

    out += ["💬 *Discuté*", narrative, ""]

    pending = _format_pending_section(polls_open, lists_open)
    if pending:
        out += ["❓ *Reste à trancher*"] + pending

    return "\n".join(out).rstrip()
