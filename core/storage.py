"""
Stockage SQLite local pour GAB — persistance des groupes, des membres
et de l'historique des conversations.

Le fichier de base de données vit à `data/gab.db` dans le working directory
de GAB (donc `/root/GAB/data/gab.db` en prod sous systemd).

SQLite est intégré à la stdlib Python (`import sqlite3`) → zéro dépendance
externe, zéro coût d'infrastructure, parfait pour le modèle self-hosted.
"""

import sqlite3
import logging
from pathlib import Path
from contextlib import contextmanager

logger = logging.getLogger("GAB.storage")

_DB_PATH = Path("data") / "gab.db"
_INITIALIZED = False


_SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    platform    TEXT NOT NULL,
    creator     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS group_members (
    group_id    TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    username    TEXT NOT NULL DEFAULT '',
    first_seen  TEXT NOT NULL,
    PRIMARY KEY (group_id, user_id),
    FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    platform    TEXT NOT NULL,
    conv_key    TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    author      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conv
    ON messages(platform, conv_key, id);

CREATE TABLE IF NOT EXISTS polls (
    id          TEXT PRIMARY KEY,
    group_id    TEXT NOT NULL,
    creator_id  TEXT NOT NULL,
    question    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    closed_at   TEXT
);

CREATE TABLE IF NOT EXISTS poll_options (
    poll_id      TEXT NOT NULL,
    option_index INTEGER NOT NULL,
    label        TEXT NOT NULL,
    PRIMARY KEY (poll_id, option_index),
    FOREIGN KEY (poll_id) REFERENCES polls(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS poll_votes (
    poll_id      TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    username     TEXT NOT NULL DEFAULT '',
    option_index INTEGER NOT NULL,
    voted_at     TEXT NOT NULL,
    PRIMARY KEY (poll_id, user_id),
    FOREIGN KEY (poll_id) REFERENCES polls(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_polls_group
    ON polls(group_id, created_at DESC);
"""


def _ensure_db_path() -> Path:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _DB_PATH


def init_db() -> None:
    """Initialise la base si elle n'existe pas. Idempotent."""
    global _INITIALIZED
    if _INITIALIZED:
        return
    path = _ensure_db_path()
    with sqlite3.connect(path) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()
    _INITIALIZED = True
    logger.info("📦 Base SQLite prête : %s", path.resolve())


@contextmanager
def connection():
    """Fournit une connexion SQLite avec foreign keys activées et row_factory dict-like."""
    init_db()
    conn = sqlite3.connect(_ensure_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
