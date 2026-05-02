"""
GroupManager — registre des groupes natifs et virtuels (persisté en SQLite).

Un groupe peut être :
- Natif (Telegram/WhatsApp/Discord) : son `id` est le chat_id de la plateforme
- Virtuel (`/creategroup`) : son `id` est un uuid8

Les membres sont collectés passivement à mesure qu'ils s'expriment dans le
groupe, ou créés explicitement via `/creategroup`.

Données persistantes : survivent à `systemctl restart gab`.
"""

import uuid
import logging
from datetime import datetime, timezone

from core.storage import connection

logger = logging.getLogger("GAB.groups")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class GroupManager:
    """Registre des groupes connus de GAB."""

    # ── Création d'un groupe virtuel via /creategroup ────────────────────────

    def create(self, name: str, creator: str, platform: str) -> dict:
        gid = str(uuid.uuid4())[:8]
        now = _now()
        with connection() as c:
            c.execute(
                "INSERT INTO groups (id, name, platform, creator, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (gid, name, platform, creator, now),
            )
            c.execute(
                "INSERT INTO group_members (group_id, user_id, username, first_seen) "
                "VALUES (?, ?, ?, ?)",
                (gid, creator, "", now),
            )
        logger.info("Groupe '%s' (%s) créé par %s sur %s", name, gid, creator, platform)
        return self.get(gid)

    # ── Enregistrement passif d'un membre dans un groupe natif ───────────────

    def register_member(
        self,
        group_id: str,
        group_name: str,
        platform: str,
        user_id: str,
        username: str = "",
    ) -> bool:
        """Enregistre un membre. Auto-crée le groupe si absent.

        Retourne True si nouveau membre, False s'il existait déjà.
        """
        with connection() as c:
            row = c.execute("SELECT id FROM groups WHERE id=?", (group_id,)).fetchone()
            if not row:
                c.execute(
                    "INSERT INTO groups (id, name, platform, creator, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (group_id, group_name or f"Groupe {platform}", platform, user_id, _now()),
                )
                logger.info("Groupe natif enregistré : %s (%s) sur %s",
                            group_name, group_id, platform)

            existed = c.execute(
                "SELECT 1 FROM group_members WHERE group_id=? AND user_id=?",
                (group_id, user_id),
            ).fetchone()
            if existed:
                # Met à jour le username si on l'a maintenant
                if username:
                    c.execute(
                        "UPDATE group_members SET username=? "
                        "WHERE group_id=? AND user_id=? AND username=''",
                        (username, group_id, user_id),
                    )
                return False

            c.execute(
                "INSERT INTO group_members (group_id, user_id, username, first_seen) "
                "VALUES (?, ?, ?, ?)",
                (group_id, user_id, username, _now()),
            )
        logger.info("➕ Membre %s (id=%s) ajouté au groupe %s", username, user_id, group_id)
        return True

    def add_member(self, group_id: str, user_id: str) -> bool:
        """Ajoute un user_id à un groupe existant. Retourne True si succès."""
        with connection() as c:
            row = c.execute("SELECT id FROM groups WHERE id=?", (group_id,)).fetchone()
            if not row:
                return False
            c.execute(
                "INSERT OR IGNORE INTO group_members "
                "(group_id, user_id, username, first_seen) VALUES (?, ?, '', ?)",
                (group_id, user_id, _now()),
            )
        return True

    def remove_member(self, group_id: str, user_id: str) -> bool:
        with connection() as c:
            cur = c.execute(
                "DELETE FROM group_members WHERE group_id=? AND user_id=?",
                (group_id, user_id),
            )
        return cur.rowcount > 0

    # ── Lecture ──────────────────────────────────────────────────────────────

    def get(self, group_id: str) -> dict | None:
        with connection() as c:
            row = c.execute("SELECT * FROM groups WHERE id=?", (group_id,)).fetchone()
            if not row:
                return None
            members_rows = c.execute(
                "SELECT user_id, username, first_seen FROM group_members "
                "WHERE group_id=? ORDER BY first_seen ASC",
                (group_id,),
            ).fetchall()
        return self._to_dict(row, members_rows)

    def list_by_user(self, user_id: str, platform: str) -> list[dict]:
        with connection() as c:
            rows = c.execute(
                "SELECT g.id FROM groups g "
                "JOIN group_members m ON m.group_id = g.id "
                "WHERE m.user_id=? AND g.platform=?",
                (user_id, platform),
            ).fetchall()
        return [self.get(r["id"]) for r in rows]

    def all(self) -> list[dict]:
        with connection() as c:
            rows = c.execute("SELECT id FROM groups").fetchall()
        return [self.get(r["id"]) for r in rows]

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _to_dict(row, members_rows) -> dict:
        members = [m["user_id"] for m in members_rows]
        members_info = {m["user_id"]: {"username": m["username"]} for m in members_rows}
        return {
            "id":           row["id"],
            "name":         row["name"],
            "platform":     row["platform"],
            "creator":      row["creator"],
            "members":      members,
            "members_info": members_info,
            "created_at":   row["created_at"],
        }
