"""
ReminderManager — rappels programmés persistés en SQLite.
ReminderScheduler — boucle asyncio qui déclenche les rappels à l'heure.

Modèle :
- Une ligne `reminders` par rappel : (id, platform, target_chat, creator_id,
  fires_at, message, created_at, sent_at, cancelled_at).
- `target_chat` : le chat_id Telegram du groupe ou de l'utilisateur (DM).
- `fires_at` : ISO 8601 avec fuseau horaire (timezone-aware).
- `sent_at` non-NULL = déjà envoyé. `cancelled_at` non-NULL = annulé.

Le scheduler tourne en arrière-plan dans la boucle asyncio principale.
Toutes les `interval` secondes, il interroge la DB pour les rappels dûs
non envoyés et appelle un callback `dispatch(platform, target_chat, text)`
qui s'occupe d'envoyer via la plateforme idoine.

Si l'envoi échoue, on ne marque pas `sent_at` → retry au prochain tick.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable

from core.storage import connection

logger = logging.getLogger("GAB.reminders")

DispatchFn = Callable[[str, str, str], Awaitable[None]]
# (platform, target_chat, text) -> None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> dict:
    return {
        "id":            row["id"],
        "platform":      row["platform"],
        "target_chat":   row["target_chat"],
        "creator_id":    row["creator_id"],
        "fires_at":      row["fires_at"],
        "message":       row["message"],
        "created_at":    row["created_at"],
        "sent_at":       row["sent_at"],
        "cancelled_at":  row["cancelled_at"],
    }


class ReminderManager:
    """CRUD des rappels en SQLite."""

    def create(
        self,
        platform: str,
        target_chat: str,
        creator_id: str,
        fires_at: datetime,
        message: str,
    ) -> dict:
        rid = str(uuid.uuid4())[:8]
        # On normalise en UTC pour le tri en DB. L'affichage humain sera reconverti.
        if fires_at.tzinfo is None:
            raise ValueError("fires_at doit être timezone-aware")
        fires_utc = fires_at.astimezone(timezone.utc).isoformat()
        with connection() as c:
            c.execute(
                "INSERT INTO reminders "
                "(id, platform, target_chat, creator_id, fires_at, message, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rid, platform, target_chat, creator_id, fires_utc, message, _now()),
            )
        logger.info("Rappel %s créé : %s @ %s — %r",
                    rid, target_chat, fires_utc, message[:60])
        return self.get(rid)

    def get(self, reminder_id: str) -> dict | None:
        with connection() as c:
            row = c.execute(
                "SELECT * FROM reminders WHERE id=?", (reminder_id,)
            ).fetchone()
        return _row_to_dict(row) if row else None

    def list_due(self, now: datetime | None = None) -> list[dict]:
        """Rappels dont l'heure est passée, non envoyés, non annulés."""
        if now is None:
            now = datetime.now(timezone.utc)
        cutoff = now.astimezone(timezone.utc).isoformat()
        with connection() as c:
            rows = c.execute(
                "SELECT * FROM reminders "
                "WHERE sent_at IS NULL AND cancelled_at IS NULL "
                "AND fires_at <= ? "
                "ORDER BY fires_at ASC",
                (cutoff,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def list_pending_for(self, platform: str, target_chat: str) -> list[dict]:
        """Rappels à venir pour un (groupe ou DM) donné."""
        with connection() as c:
            rows = c.execute(
                "SELECT * FROM reminders "
                "WHERE platform=? AND target_chat=? "
                "AND sent_at IS NULL AND cancelled_at IS NULL "
                "ORDER BY fires_at ASC",
                (platform, target_chat),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def mark_sent(self, reminder_id: str) -> None:
        with connection() as c:
            c.execute(
                "UPDATE reminders SET sent_at=? WHERE id=? AND sent_at IS NULL",
                (_now(), reminder_id),
            )

    def cancel(self, reminder_id: str) -> bool:
        with connection() as c:
            cur = c.execute(
                "UPDATE reminders SET cancelled_at=? "
                "WHERE id=? AND sent_at IS NULL AND cancelled_at IS NULL",
                (_now(), reminder_id),
            )
        return cur.rowcount > 0


class ReminderScheduler:
    """Boucle asyncio qui poll les rappels dûs et les dispatche."""

    def __init__(
        self,
        reminders: ReminderManager,
        dispatch: DispatchFn,
        interval: int = 30,
    ):
        self.reminders = reminders
        self.dispatch  = dispatch
        self.interval  = interval
        self._stop     = asyncio.Event()

    async def run(self) -> None:
        logger.info("⏰ Scheduler de rappels démarré (poll toutes les %ds)", self.interval)
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception as exc:
                logger.exception("Tick scheduler en erreur : %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass
        logger.info("⏰ Scheduler de rappels arrêté")

    def stop(self) -> None:
        self._stop.set()

    async def _tick(self) -> None:
        due = self.reminders.list_due()
        if not due:
            return
        logger.info("⏰ %d rappel(s) à envoyer", len(due))
        for r in due:
            try:
                text = f"⏰ *Rappel* : {r['message']}"
                await self.dispatch(r["platform"], r["target_chat"], text)
                self.reminders.mark_sent(r["id"])
                logger.info("⏰ Rappel %s envoyé à %s/%s",
                            r["id"], r["platform"], r["target_chat"])
            except Exception as exc:
                # On ne marque PAS sent_at → retry au prochain tick
                logger.error("⏰ Dispatch rappel %s échoué : %s — retry au prochain tick",
                             r["id"], exc)


def parse_rappel(arg: str, tz_name: str = "Europe/Paris") -> tuple[datetime | None, str, str | None]:
    """Parser strict de `/rappel YYYY-MM-DD HH:MM <message>`.

    Retourne (when_aware, message, error_text).
    Si error_text est non-None, c'est qu'on n'a pas pu parser → message destiné
    à l'utilisateur. Sinon, when_aware est timezone-aware (Europe/Paris par
    défaut) et message est le contenu du rappel.
    """
    from zoneinfo import ZoneInfo
    parts = arg.strip().split(maxsplit=2)
    if len(parts) < 3:
        return None, "", (
            "Usage : `/rappel YYYY-MM-DD HH:MM <message>`\n"
            "Exemple : `/rappel 2026-05-08 19:00 RDV chez Mario`"
        )
    date_str, time_str, message = parts
    try:
        naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None, "", (
            f"Date/heure illisible : `{date_str} {time_str}`. "
            f"Format attendu : `YYYY-MM-DD HH:MM` (ex : `2026-05-08 19:00`)."
        )
    aware = naive.replace(tzinfo=ZoneInfo(tz_name))
    if aware <= datetime.now(timezone.utc):
        return None, "", (
            f"Cette date est déjà passée. "
            f"Programme un rappel dans le futur."
        )
    if not message.strip():
        return None, "", "Message du rappel manquant."
    return aware, message.strip(), None


def format_fires_at_fr(iso_utc: str, tz_name: str = "Europe/Paris") -> str:
    """Convertit un ISO UTC en chaîne lisible 'mardi 4 mai 2026 à 19h00'."""
    from zoneinfo import ZoneInfo
    _WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
    _MONTHS   = ("", "janvier", "février", "mars", "avril", "mai", "juin",
                 "juillet", "août", "septembre", "octobre", "novembre", "décembre")
    dt = datetime.fromisoformat(iso_utc).astimezone(ZoneInfo(tz_name))
    return (
        f"{_WEEKDAYS[dt.weekday()]} {dt.day} {_MONTHS[dt.month]} {dt.year} "
        f"à {dt.hour:02d}h{dt.minute:02d}"
    )
