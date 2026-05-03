"""
PollManager — sondages de groupe persistés en SQLite.

Modèle de données :
- `polls`         : 1 ligne par sondage (question, créateur, état)
- `poll_options`  : N lignes par sondage (label des options)
- `poll_votes`    : 1 ligne par (sondage, user) — UPSERT pour changer de vote

Les sondages survivent à `systemctl restart gab`. Un user qui re-clique sur
une autre option change son vote (1 vote par user et par sondage).
"""

import uuid
import logging
from datetime import datetime, timezone

from core.storage import connection

logger = logging.getLogger("GAB.polls")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_sondage(arg: str) -> tuple[str, list[str]]:
    """Parse l'argument de `/sondage`.

    Format attendu :
        `<Question> ? <Opt1> | <Opt2> | <Opt3>`
        `<Question> : <Opt1> | <Opt2>`
        `<Opt1> | <Opt2>`                    (sans question explicite)

    Le `?` ou `:` (le plus à droite avant le premier `|`) sépare la
    question de la première option. Renvoie `("question", [opts])`.
    Une question vide signifie « pas de question explicite ».
    """
    arg = arg.strip()
    if not arg or "|" not in arg:
        return "", []

    first_pipe = arg.index("|")
    head, tail = arg[:first_pipe], arg[first_pipe + 1:]

    boundary = max(head.rfind("?"), head.rfind(":"))
    if boundary == -1:
        question = ""
        first_option = head.strip()
    else:
        question = head[: boundary + 1].strip()
        first_option = head[boundary + 1:].strip()

    other_options = [o.strip() for o in tail.split("|") if o.strip()]
    options = ([first_option] if first_option else []) + other_options
    return question, options


class PollManager:
    """Gestionnaire de sondages d'un groupe."""

    def create(
        self,
        group_id: str,
        creator_id: str,
        question: str,
        options: list[str],
    ) -> dict:
        pid = str(uuid.uuid4())[:8]
        now = _now()
        with connection() as c:
            c.execute(
                "INSERT INTO polls (id, group_id, creator_id, question, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (pid, group_id, creator_id, question, now),
            )
            for idx, label in enumerate(options):
                c.execute(
                    "INSERT INTO poll_options (poll_id, option_index, label) "
                    "VALUES (?, ?, ?)",
                    (pid, idx, label),
                )
        logger.info("Sondage %s créé dans %s par %s : %r (%d options)",
                    pid, group_id, creator_id, question, len(options))
        return self.get(pid)

    def vote(
        self,
        poll_id: str,
        user_id: str,
        option_index: int,
        username: str = "",
    ) -> dict | None:
        """Enregistre ou modifie le vote d'un user. UPSERT sur (poll_id, user_id)."""
        with connection() as c:
            poll_row = c.execute(
                "SELECT id, closed_at FROM polls WHERE id=?", (poll_id,)
            ).fetchone()
            if not poll_row:
                return None
            if poll_row["closed_at"]:
                return self.get(poll_id)  # sondage clos, on renvoie l'état figé
            opt = c.execute(
                "SELECT 1 FROM poll_options WHERE poll_id=? AND option_index=?",
                (poll_id, option_index),
            ).fetchone()
            if not opt:
                return self.get(poll_id)
            c.execute(
                "INSERT INTO poll_votes (poll_id, user_id, username, option_index, voted_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(poll_id, user_id) DO UPDATE SET "
                "  option_index=excluded.option_index, "
                "  username=excluded.username, "
                "  voted_at=excluded.voted_at",
                (poll_id, user_id, username, option_index, _now()),
            )
        return self.get(poll_id)

    def close(self, poll_id: str) -> dict | None:
        with connection() as c:
            cur = c.execute(
                "UPDATE polls SET closed_at=? WHERE id=? AND closed_at IS NULL",
                (_now(), poll_id),
            )
            if cur.rowcount == 0:
                return self.get(poll_id)
        return self.get(poll_id)

    def get(self, poll_id: str) -> dict | None:
        with connection() as c:
            poll = c.execute(
                "SELECT id, group_id, creator_id, question, created_at, closed_at "
                "FROM polls WHERE id=?",
                (poll_id,),
            ).fetchone()
            if not poll:
                return None
            opts = c.execute(
                "SELECT option_index, label FROM poll_options "
                "WHERE poll_id=? ORDER BY option_index ASC",
                (poll_id,),
            ).fetchall()
            votes = c.execute(
                "SELECT option_index, username FROM poll_votes WHERE poll_id=?",
                (poll_id,),
            ).fetchall()
        counts: dict[int, int] = {}
        voters: dict[int, list[str]] = {}
        for v in votes:
            idx = v["option_index"]
            counts[idx] = counts.get(idx, 0) + 1
            voters.setdefault(idx, []).append(v["username"] or "")
        options = [
            {
                "index":  o["option_index"],
                "label":  o["label"],
                "votes":  counts.get(o["option_index"], 0),
                "voters": voters.get(o["option_index"], []),
            }
            for o in opts
        ]
        return {
            "id":          poll["id"],
            "group_id":    poll["group_id"],
            "creator_id":  poll["creator_id"],
            "question":    poll["question"],
            "options":     options,
            "total_votes": sum(counts.values()),
            "closed":      poll["closed_at"] is not None,
            "created_at":  poll["created_at"],
        }

    @staticmethod
    def format_message(poll: dict) -> str:
        """Rend le corps texte du sondage. Les boutons sont rendus côté plateforme."""
        header = "📊 *" + (poll["question"] or "Sondage") + "*"
        if poll["closed"]:
            header += "  _(clos)_"
        leader = max((o["votes"] for o in poll["options"]), default=0)
        lines = [header, ""]
        for o in poll["options"]:
            mark = "  ✅" if leader > 0 and o["votes"] == leader else ""
            lines.append(f"• {o['label']} — {o['votes']}{mark}")
        lines.append("")
        lines.append(f"_Total : {poll['total_votes']} vote(s)_")
        return "\n".join(lines)
