"""
ListManager — listes partagées modifiables persistées en SQLite.

Cas d'usage typiques :
- BBQ : qui amène quoi ? (Steaks → Frédéric, Salade → Audrey, …)
- Courses : items à acheter avec qui s'en charge
- Co-location : qui paie quelle facture

Modèle :
- 1 ligne `lists` par liste (id, group_id, creator_id, title, created_at, closed_at)
- N lignes `list_items` (list_id, item_index, label, claimer_id, claimer_name)
- Un item est « libre » quand `claimer_id IS NULL`, sinon assigné à un user.

Règle de claim :
- Item libre → on peut claimer
- Item claimé par soi-même → on peut le libérer (toggle)
- Item claimé par quelqu'un d'autre → bloqué (silence ou alerte côté UI)
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Literal

from core.storage import connection

logger = logging.getLogger("GAB.lists")

ClaimOutcome = Literal["claimed", "unclaimed", "blocked", "not_found"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_liste(arg: str) -> tuple[str, list[str]]:
    """Parse l'argument de `/liste`.

    Format attendu :
        `<Titre> : <Item1> | <Item2> | <Item3>`
        `<Item1> | <Item2> | <Item3>`              (sans titre explicite)

    Le `:` (le plus à droite avant le premier `|`) sépare le titre du premier
    item. Renvoie `("titre", [items])`. Titre vide = pas de titre explicite,
    sera remplacé par "Liste" à l'affichage.
    """
    arg = arg.strip()
    if not arg or "|" not in arg:
        return "", []

    first_pipe = arg.index("|")
    head, tail = arg[:first_pipe], arg[first_pipe + 1:]

    boundary = head.rfind(":")
    if boundary == -1:
        title = ""
        first_item = head.strip()
    else:
        title = head[:boundary].strip()
        first_item = head[boundary + 1:].strip()

    other_items = [o.strip() for o in tail.split("|") if o.strip()]
    items = ([first_item] if first_item else []) + other_items
    return title, items


class ListManager:
    """Gestionnaire de listes partagées d'un groupe."""

    def create(
        self,
        group_id: str,
        creator_id: str,
        title: str,
        items: list[str],
    ) -> dict:
        lid = str(uuid.uuid4())[:8]
        now = _now()
        with connection() as c:
            c.execute(
                "INSERT INTO lists (id, group_id, creator_id, title, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (lid, group_id, creator_id, title or "Liste", now),
            )
            for idx, label in enumerate(items):
                c.execute(
                    "INSERT INTO list_items (list_id, item_index, label) "
                    "VALUES (?, ?, ?)",
                    (lid, idx, label),
                )
        logger.info("Liste %s créée dans %s par %s : %r (%d items)",
                    lid, group_id, creator_id, title, len(items))
        return self.get(lid)

    def claim(
        self,
        list_id: str,
        item_index: int,
        user_id: str,
        user_name: str,
    ) -> tuple[dict | None, ClaimOutcome]:
        """Tente de claimer (ou unclaimer) un item.

        Logique :
        - Item libre → claim par l'appelant
        - Item claimé par l'appelant → unclaim
        - Item claimé par quelqu'un d'autre → bloqué, pas de modification
        """
        with connection() as c:
            row = c.execute(
                "SELECT claimer_id, claimer_name FROM list_items "
                "WHERE list_id=? AND item_index=?",
                (list_id, item_index),
            ).fetchone()
            if not row:
                return None, "not_found"

            current_claimer = row["claimer_id"]
            if current_claimer is None:
                # Libre → on claim
                c.execute(
                    "UPDATE list_items SET claimer_id=?, claimer_name=? "
                    "WHERE list_id=? AND item_index=?",
                    (user_id, user_name or "", list_id, item_index),
                )
                outcome: ClaimOutcome = "claimed"
            elif current_claimer == user_id:
                # Claimé par moi → unclaim
                c.execute(
                    "UPDATE list_items SET claimer_id=NULL, claimer_name='' "
                    "WHERE list_id=? AND item_index=?",
                    (list_id, item_index),
                )
                outcome = "unclaimed"
            else:
                # Claimé par quelqu'un d'autre → bloqué
                outcome = "blocked"
        return self.get(list_id), outcome

    def close(self, list_id: str) -> dict | None:
        with connection() as c:
            c.execute(
                "UPDATE lists SET closed_at=? WHERE id=? AND closed_at IS NULL",
                (_now(), list_id),
            )
        return self.get(list_id)

    def get(self, list_id: str) -> dict | None:
        with connection() as c:
            row = c.execute(
                "SELECT id, group_id, creator_id, title, created_at, closed_at "
                "FROM lists WHERE id=?",
                (list_id,),
            ).fetchone()
            if not row:
                return None
            items_rows = c.execute(
                "SELECT item_index, label, claimer_id, claimer_name "
                "FROM list_items WHERE list_id=? ORDER BY item_index ASC",
                (list_id,),
            ).fetchall()
        items = [
            {
                "index":        i["item_index"],
                "label":        i["label"],
                "claimer_id":   i["claimer_id"],
                "claimer_name": i["claimer_name"] or "",
            }
            for i in items_rows
        ]
        claimed = sum(1 for i in items if i["claimer_id"] is not None)
        return {
            "id":          row["id"],
            "group_id":    row["group_id"],
            "creator_id":  row["creator_id"],
            "title":       row["title"],
            "items":       items,
            "claimed":     claimed,
            "total":       len(items),
            "closed":      row["closed_at"] is not None,
            "created_at":  row["created_at"],
        }

    @staticmethod
    def format_message(lst: dict) -> str:
        """Rend le corps texte de la liste. Les boutons sont rendus côté plateforme."""
        header = "📝 *" + (lst["title"] or "Liste") + "*"
        if lst["closed"]:
            header += "  _(close)_"
        lines = [header, ""]
        for it in lst["items"]:
            if it["claimer_id"]:
                marker = f" — {it['claimer_name'] or '?'} ✅"
            else:
                marker = " — _libre_"
            lines.append(f"• {it['label']}{marker}")
        lines.append("")
        lines.append(f"_{lst['claimed']}/{lst['total']} pris_")
        return "\n".join(lines)
