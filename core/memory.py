"""
Mémoire conversationnelle persistante (SQLite).

Deux scopes distincts :
- En conversation privée (DM)  : historique par (platform, user_id)
- En groupe                    : historique partagé par (platform, group_id)
  → Les messages utilisateurs sont préfixés par leur auteur (`[Audrey] …`)
    pour que le LLM sache qui dit quoi.

Les données survivent à `systemctl restart gab` (contrairement à la version
précédente qui stockait en RAM).
"""

from datetime import datetime, timezone

from core.storage import connection


MAX_HISTORY = 20  # messages gardés par conversation (FIFO)


def _conv_key(user_id: str, group_id: str | None) -> str:
    if group_id:
        return f"group:{group_id}"
    return f"user:{user_id}"


class Conversation:
    """Vue persistée sur l'historique d'une conversation."""

    def __init__(self, platform: str, user_id: str, group_id: str | None):
        self.platform = platform
        self.user_id  = user_id
        self.group_id = group_id
        self._key     = _conv_key(user_id, group_id)

    def add(self, role: str, content: str, author: str = "") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with connection() as c:
            c.execute(
                "INSERT INTO messages (platform, conv_key, role, content, author, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (self.platform, self._key, role, content, author, now),
            )
            # Trim FIFO : on ne garde que les MAX_HISTORY plus récents
            c.execute(
                "DELETE FROM messages WHERE platform=? AND conv_key=? "
                "AND id NOT IN ("
                "  SELECT id FROM messages WHERE platform=? AND conv_key=? "
                "  ORDER BY id DESC LIMIT ?"
                ")",
                (self.platform, self._key, self.platform, self._key, MAX_HISTORY),
            )

    def get_history(self) -> list[dict]:
        with connection() as c:
            rows = c.execute(
                "SELECT role, content, author FROM messages "
                "WHERE platform=? AND conv_key=? "
                "ORDER BY id ASC",
                (self.platform, self._key),
            ).fetchall()
        history = []
        for row in rows:
            content = row["content"]
            # En groupe, préfixe le message user par l'auteur pour le LLM
            if self.group_id and row["role"] == "user" and row["author"]:
                content = f"[{row['author']}] {content}"
            history.append({"role": row["role"], "content": content})
        return history

    def clear(self) -> None:
        with connection() as c:
            c.execute(
                "DELETE FROM messages WHERE platform=? AND conv_key=?",
                (self.platform, self._key),
            )


class Memory:
    """Façade au-dessus de SQLite pour l'historique conversationnel."""

    def get(self, platform: str, user_id: str, group_id: str | None = None) -> Conversation:
        return Conversation(platform, user_id, group_id)

    def clear(self, platform: str, user_id: str, group_id: str | None = None) -> None:
        Conversation(platform, user_id, group_id).clear()
