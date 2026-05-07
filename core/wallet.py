"""
WalletManager — billets de transport / hôtel / événement persistés en SQLite.

Modèle (v1.a) :
- 1 ligne `tickets` par billet : (id, owner_id, group_id, shared_in_group,
  kind, title, when_at, location_from, location_to, reference, seat,
  raw_excerpt, file_path, reminder_id_1, reminder_id_2, platform,
  created_at, deleted_at).
- `owner_id` : c'est l'utilisateur qui possède le billet (privacy by default).
  `group_id` peut être renseigné si le billet a été ajouté depuis un groupe
  (pour faciliter le partage v1.c) mais `shared_in_group=0` tant que le
  propriétaire ne l'a pas partagé explicitement.
- `when_at` : ISO 8601 UTC timezone-aware (départ pour train/vol, heure de
  l'événement pour event, check-in pour hôtel).
- Suppression logique uniquement (`deleted_at`), pas d'auto-cleanup —
  un billet sert aussi de preuve/archive.

Différence vs `events` :
- `events` est un objet de groupe (visible par tous).
- `tickets` est un objet personnel (visible par owner uniquement en v1.a).

Les rappels J-1 18h locale et H-2 sont créés automatiquement à la création
du billet via `ReminderManager`. Leurs IDs sont stockés dans la ligne ticket
pour pouvoir les annuler proprement quand le billet est supprimé.
"""

import os
import uuid
import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from core.storage import connection

logger = logging.getLogger("GAB.wallet")

_TZ_PARIS = ZoneInfo("Europe/Paris")
_WEEKDAYS_FR = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MONTHS_FR = (
    "", "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)

_KIND_EMOJI = {
    "train":  "🚆",
    "flight": "✈️",
    "hotel":  "🏨",
    "event":  "🎟",
    "other":  "🎫",
}
_KIND_LABEL = {
    "train":  "Train",
    "flight": "Vol",
    "hotel":  "Hôtel",
    "event":  "Événement",
    "other":  "Billet",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> dict:
    return {
        "id":              row["id"],
        "owner_id":        row["owner_id"],
        "group_id":        row["group_id"],
        "shared_in_group": int(row["shared_in_group"]),
        "kind":            row["kind"],
        "title":           row["title"],
        "when_at":         row["when_at"],
        "location_from":   row["location_from"] or "",
        "location_to":     row["location_to"] or "",
        "reference":       row["reference"] or "",
        "seat":            row["seat"] or "",
        "raw_excerpt":     row["raw_excerpt"] or "",
        "file_path":       row["file_path"],
        "reminder_id_1":   row["reminder_id_1"],
        "reminder_id_2":   row["reminder_id_2"],
        "platform":        row["platform"] or "",
        "created_at":      row["created_at"],
        "deleted_at":      row["deleted_at"],
    }


def format_ticket_when_fr(iso_utc: str, tz_name: str = "Europe/Paris") -> str:
    """Convertit un ISO UTC en chaîne lisible 'jeudi 15 mai à 19h00'."""
    dt = datetime.fromisoformat(iso_utc).astimezone(ZoneInfo(tz_name))
    return (
        f"{_WEEKDAYS_FR[dt.weekday()]} {dt.day} {_MONTHS_FR[dt.month]} "
        f"à {dt.hour:02d}h{dt.minute:02d}"
    )


def kind_label(kind: str) -> str:
    emoji = _KIND_EMOJI.get(kind, _KIND_EMOJI["other"])
    label = _KIND_LABEL.get(kind, _KIND_LABEL["other"])
    return f"{emoji} {label}"


class WalletManager:
    """CRUD des billets en SQLite."""

    def create(
        self,
        owner_id: str,
        kind: str,
        title: str,
        when_at: datetime,
        group_id: str | None = None,
        platform: str = "",
        location_from: str = "",
        location_to: str = "",
        reference: str = "",
        seat: str = "",
        raw_excerpt: str = "",
        file_path: str | None = None,
    ) -> dict:
        if when_at.tzinfo is None:
            raise ValueError("when_at doit être timezone-aware")
        tid = str(uuid.uuid4())[:8]
        when_utc = when_at.astimezone(timezone.utc).isoformat()
        with connection() as c:
            c.execute(
                "INSERT INTO tickets "
                "(id, owner_id, group_id, shared_in_group, kind, title, "
                " when_at, location_from, location_to, reference, seat, "
                " raw_excerpt, file_path, platform, created_at) "
                "VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    tid, owner_id, group_id, kind, title,
                    when_utc, location_from, location_to, reference, seat,
                    raw_excerpt[:500], file_path, platform, _now(),
                ),
            )
        logger.info("Billet %s créé : owner=%s kind=%s @ %s — %r",
                    tid, owner_id, kind, when_utc, title[:60])
        return self.get(tid)

    def get(self, ticket_id: str) -> dict | None:
        with connection() as c:
            row = c.execute(
                "SELECT * FROM tickets WHERE id=?", (ticket_id,)
            ).fetchone()
        return _row_to_dict(row) if row else None

    def list_for_owner(self, owner_id: str, upcoming_only: bool = True) -> list[dict]:
        """Billets du propriétaire, triés par date de départ croissante."""
        sql = (
            "SELECT * FROM tickets "
            "WHERE owner_id=? AND deleted_at IS NULL "
        )
        params: tuple = (owner_id,)
        if upcoming_only:
            sql += "AND when_at >= ? "
            params = (owner_id, _now())
        sql += "ORDER BY when_at ASC"
        with connection() as c:
            rows = c.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    def list_for_group_shared(self, group_id: str, upcoming_only: bool = True) -> list[dict]:
        """Billets partagés dans le groupe (v1.c). En v1.a la liste est vide
        car aucun billet n'est jamais marqué shared_in_group=1."""
        sql = (
            "SELECT * FROM tickets "
            "WHERE group_id=? AND shared_in_group=1 AND deleted_at IS NULL "
        )
        params: tuple = (group_id,)
        if upcoming_only:
            sql += "AND when_at >= ? "
            params = (group_id, _now())
        sql += "ORDER BY when_at ASC"
        with connection() as c:
            rows = c.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    def cancel(self, ticket_id: str) -> dict | None:
        """Suppression logique. Retourne la ligne après update (avec
        deleted_at renseigné) pour permettre à l'appelant d'annuler les
        rappels associés."""
        with connection() as c:
            c.execute(
                "UPDATE tickets SET deleted_at=? "
                "WHERE id=? AND deleted_at IS NULL",
                (_now(), ticket_id),
            )
        return self.get(ticket_id)

    def attach_reminders(
        self,
        ticket_id: str,
        reminder_id_1: str | None,
        reminder_id_2: str | None,
    ) -> None:
        """Lie les IDs des 2 rappels auto au billet pour pouvoir les
        annuler quand le billet est supprimé."""
        with connection() as c:
            c.execute(
                "UPDATE tickets SET reminder_id_1=?, reminder_id_2=? WHERE id=?",
                (reminder_id_1, reminder_id_2, ticket_id),
            )


def compute_reminder_times(
    when_at: datetime,
    days_before: int,
    hours_before: int,
    day_hour_local: int = 18,
    tz_name: str = "Europe/Paris",
) -> tuple[datetime | None, datetime | None]:
    """Calcule (J-D 18h locale, H-H avant when_at). Retourne None pour les
    rappels qui sont déjà passés (à ne pas programmer).

    `days_before <= 0` ou `hours_before <= 0` désactive le rappel
    correspondant.
    """
    tz = ZoneInfo(tz_name)
    now = datetime.now(timezone.utc)

    day_reminder: datetime | None = None
    if days_before > 0:
        local_when = when_at.astimezone(tz)
        day_local = (local_when - timedelta(days=days_before)).replace(
            hour=day_hour_local, minute=0, second=0, microsecond=0
        )
        if day_local > now:
            day_reminder = day_local

    hour_reminder: datetime | None = None
    if hours_before > 0:
        candidate = when_at - timedelta(hours=hours_before)
        if candidate > now:
            hour_reminder = candidate

    return day_reminder, hour_reminder


def build_reminder_message(
    ticket: dict,
    kind_of_reminder: str,
    hours_before: int = 2,
) -> str:
    """Compose le texte d'un rappel automatique pour un billet.

    `kind_of_reminder` ∈ {"day", "hour"} pour distinguer J-D vs H-H.
    """
    when_label = format_ticket_when_fr(ticket["when_at"])
    bits = [kind_label(ticket["kind"]), ticket["title"]]
    head = " — ".join(bits)

    extras: list[str] = []
    if ticket["location_from"] and ticket["location_to"]:
        extras.append(f"{ticket['location_from']} → {ticket['location_to']}")
    elif ticket["location_to"]:
        extras.append(ticket["location_to"])
    elif ticket["location_from"]:
        extras.append(ticket["location_from"])
    if ticket["seat"]:
        extras.append(f"place {ticket['seat']}")
    if ticket["reference"]:
        extras.append(f"réf. {ticket['reference']}")

    if kind_of_reminder == "day":
        prefix = "Demain"
    else:
        prefix = f"Dans {hours_before}h" if hours_before > 0 else "Bientôt"
    body = f"{prefix} : {head} le {when_label}"
    if extras:
        body += f" ({', '.join(extras)})"
    return body


def get_reminder_tunables() -> tuple[int, int]:
    """Retourne (days_before, hours_before) lus depuis l'environnement.
    Défauts : 1 jour, 2 heures."""
    try:
        days = int(os.getenv("WALLET_REMINDER_DAYS_BEFORE", "1"))
    except ValueError:
        days = 1
    try:
        hours = int(os.getenv("WALLET_REMINDER_HOURS_BEFORE", "2"))
    except ValueError:
        hours = 2
    return days, hours


def format_billets_message(tickets: list[dict], scope: str = "tes prochains") -> str:
    """Rend une liste de billets en markdown lisible.
    `scope` est inséré dans le titre — ex : « tes prochains », « du groupe »."""
    if not tickets:
        return f"🎫 *Billets* ({scope})\n\n_Aucun billet à venir._"
    lines = [f"🎫 *Billets* ({scope})", ""]
    for t in tickets:
        when = format_ticket_when_fr(t["when_at"])
        line = f"{kind_label(t['kind'])} *{t['title']}* — {when}"
        details: list[str] = []
        if t["location_from"] and t["location_to"]:
            details.append(f"{t['location_from']} → {t['location_to']}")
        elif t["location_to"]:
            details.append(t["location_to"])
        if t["seat"]:
            details.append(f"place {t['seat']}")
        if t["reference"]:
            details.append(f"réf. {t['reference']}")
        if details:
            line += f"\n   {' · '.join(details)}"
        line += f"\n   `id: {t['id']}`"
        lines.append(line)
    lines.append("")
    n = len(tickets)
    lines.append(f"_{n} billet{'s' if n > 1 else ''}_  •  "
                 f"`/billets supprimer <id>` pour retirer un billet")
    return "\n".join(lines)
