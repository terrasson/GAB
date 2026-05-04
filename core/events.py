"""
EventManager — agenda d'un groupe (événements futurs) persisté en SQLite.

Modèle :
- 1 ligne `events` par événement : (id, group_id, creator_id, title,
  starts_at, location, created_at, cancelled_at).
- `starts_at` : ISO 8601 UTC (timezone-aware).
- `cancelled_at` non-NULL = événement annulé, n'apparaît plus dans l'agenda.

Différence vs `/rappel` :
- `/rappel` = ping actif à l'heure dite (notification automatique).
- `/agenda` = liste descriptive consultable (planning du groupe).
Les deux peuvent coexister : un événement peut générer un rappel J-1
(intégration prévue mais hors scope v1).
"""

import uuid
import logging
from datetime import datetime, timezone, timedelta

from core.storage import connection

logger = logging.getLogger("GAB.events")

# Localisation FR sans dépendance de la locale système (cf. core/agent.py)
_WEEKDAYS_FR = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MONTHS_FR = (
    "", "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> dict:
    return {
        "id":            row["id"],
        "group_id":      row["group_id"],
        "creator_id":    row["creator_id"],
        "title":         row["title"],
        "starts_at":     row["starts_at"],
        "location":      row["location"] or "",
        "created_at":    row["created_at"],
        "cancelled_at":  row["cancelled_at"],
    }


def parse_agenda_add(arg: str, tz_name: str = "Europe/Paris"):
    """Parser de `/agenda <titre>, <YYYY-MM-DD HH:MM>, <lieu?>`.

    Retourne (when_aware, title, location, error_text).
    Si error_text est non-None, c'est qu'on n'a pas pu parser.
    Le lieu est optionnel ; si absent, on retourne "".
    """
    from zoneinfo import ZoneInfo
    parts = [p.strip() for p in arg.split(",")]
    if len(parts) < 2:
        return None, "", "", (
            "Usage : `/agenda <titre>, <YYYY-MM-DD HH:MM>, <lieu>`\n"
            "Le lieu est optionnel. Exemple :\n"
            "`/agenda BBQ chez Marc, 2026-05-15 19:00, chez Marc 12 rue X`"
        )
    title, date_str = parts[0], parts[1]
    location = parts[2] if len(parts) >= 3 else ""

    if not title:
        return None, "", "", "Titre de l'événement manquant."
    try:
        naive = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
    except ValueError:
        return None, "", "", (
            f"Date/heure illisible : `{date_str}`. "
            f"Format attendu : `YYYY-MM-DD HH:MM` (ex : `2026-05-15 19:00`)."
        )
    aware = naive.replace(tzinfo=ZoneInfo(tz_name))
    if aware <= datetime.now(timezone.utc):
        return None, "", "", "Cet événement est déjà passé. Programme une date future."
    return aware, title, location, None


def format_event_when_fr(iso_utc: str, tz_name: str = "Europe/Paris") -> str:
    """Convertit un ISO UTC en chaîne lisible 'jeudi 15 mai à 19h00'."""
    from zoneinfo import ZoneInfo
    dt = datetime.fromisoformat(iso_utc).astimezone(ZoneInfo(tz_name))
    return (
        f"{_WEEKDAYS_FR[dt.weekday()]} {dt.day} {_MONTHS_FR[dt.month]} "
        f"à {dt.hour:02d}h{dt.minute:02d}"
    )


class EventManager:
    """Gestionnaire de l'agenda d'un groupe."""

    def create(
        self,
        group_id: str,
        creator_id: str,
        title: str,
        starts_at: datetime,
        location: str = "",
    ) -> dict:
        if starts_at.tzinfo is None:
            raise ValueError("starts_at doit être timezone-aware")
        eid = str(uuid.uuid4())[:8]
        starts_utc = starts_at.astimezone(timezone.utc).isoformat()
        with connection() as c:
            c.execute(
                "INSERT INTO events "
                "(id, group_id, creator_id, title, starts_at, location, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (eid, group_id, creator_id, title, starts_utc, location, _now()),
            )
        logger.info("Événement %s créé dans %s : %r @ %s",
                    eid, group_id, title, starts_utc)
        return self.get(eid)

    def get(self, event_id: str) -> dict | None:
        with connection() as c:
            row = c.execute(
                "SELECT * FROM events WHERE id=?", (event_id,)
            ).fetchone()
        return _row_to_dict(row) if row else None

    def list_upcoming(
        self,
        group_id: str,
        days_ahead: int = 30,
        limit: int = 50,
    ) -> list[dict]:
        """Événements futurs (non passés, non annulés), triés par date croissante."""
        now = datetime.now(timezone.utc).isoformat()
        cutoff = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).isoformat()
        with connection() as c:
            rows = c.execute(
                "SELECT * FROM events "
                "WHERE group_id=? AND cancelled_at IS NULL "
                "AND starts_at >= ? AND starts_at <= ? "
                "ORDER BY starts_at ASC LIMIT ?",
                (group_id, now, cutoff, limit),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def cancel(self, event_id: str) -> dict | None:
        with connection() as c:
            c.execute(
                "UPDATE events SET cancelled_at=? "
                "WHERE id=? AND cancelled_at IS NULL",
                (_now(), event_id),
            )
        return self.get(event_id)

    @staticmethod
    def format_agenda(events: list[dict], days_ahead: int = 30) -> str:
        """Rend un agenda lisible. Les boutons d'annulation sont ajoutés
        séparément côté plateforme."""
        if not events:
            return f"📅 *Agenda* (prochains {days_ahead} jours)\n\n_Aucun événement prévu._"
        lines = [f"📅 *Agenda* (prochains {days_ahead} jours)", ""]
        for e in events:
            when = format_event_when_fr(e["starts_at"])
            line = f"🗓 *{when}*\n   {e['title']}"
            if e["location"]:
                line += f" — {e['location']}"
            lines.append(line)
        lines.append("")
        n = len(events)
        lines.append(f"_{n} événement{'s' if n > 1 else ''} prévu{'s' if n > 1 else ''}_")
        return "\n".join(lines)
