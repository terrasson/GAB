"""
FactStore — mémoire sémantique d'un groupe persistée en SQLite.

Distinction clé avec la mémoire épisodique (`core/memory.py`) :
- Épisodique = "ce qui a été dit et quand" (historique brut des messages).
- Sémantique = "ce qui est vrai actuellement" (la décision finale, écrasée
  quand le groupe la révise).

Modèle : 1 ligne `facts` par (group_id, key). UPSERT à l'écriture : un fait
avec la même clé écrase l'ancien. Convention de clés hiérarchique :
- event.<nom>.{date,place,time,attendees}
- member.<id|prénom>.{allergies,preferences}
- group.{rules,language}

Le LLM invoque `set_facts` pendant qu'il répond à l'utilisateur (extraction
active, dans le même appel) ; pas d'appel LLM dédié à l'extraction.
"""

import logging
from datetime import datetime, timezone

from core.storage import connection

logger = logging.getLogger("GAB.facts")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> dict:
    return {
        "group_id":   row["group_id"],
        "key":        row["key"],
        "value":      row["value"],
        "confidence": row["confidence"],
        "source":     row["source"],
        "updated_at": row["updated_at"],
    }


class FactStore:
    """Stockage des faits sémantiques d'un groupe."""

    def set(
        self,
        group_id: str,
        key: str,
        value: str,
        source: str,
        confidence: float = 1.0,
    ) -> dict:
        """UPSERT d'un fait. Écrase l'ancienne valeur si la clé existe déjà."""
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise ValueError("key et value ne peuvent pas être vides")
        with connection() as c:
            c.execute(
                "INSERT INTO facts (group_id, key, value, confidence, source, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(group_id, key) DO UPDATE SET "
                "value=excluded.value, confidence=excluded.confidence, "
                "source=excluded.source, updated_at=excluded.updated_at",
                (group_id, key, value, confidence, source, _now()),
            )
        logger.info("Fait %s/%s = %r (source=%s)", group_id, key, value, source)
        return self.get(group_id, key)

    def set_many(
        self,
        group_id: str,
        facts: list[dict],
        source: str,
    ) -> list[dict]:
        """Batch UPSERT. Chaque entrée doit contenir au moins `key` et `value`.
        Les entrées invalides sont silencieusement ignorées (le LLM peut
        bavoter et on ne veut pas tout faire échouer)."""
        saved = []
        for entry in facts:
            key = (entry.get("key") or "").strip()
            value = (entry.get("value") or "").strip()
            if not key or not value:
                continue
            confidence = entry.get("confidence", 1.0)
            try:
                saved.append(self.set(group_id, key, value, source, confidence))
            except Exception as exc:
                logger.warning("set_many : entrée ignorée %r — %s", entry, exc)
        return saved

    def get(self, group_id: str, key: str) -> dict | None:
        with connection() as c:
            row = c.execute(
                "SELECT * FROM facts WHERE group_id=? AND key=?",
                (group_id, key),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def list_for_group(self, group_id: str) -> list[dict]:
        """Tous les faits d'un groupe, triés par clé alphabétique pour un
        affichage stable dans le prompt et dans /facts."""
        with connection() as c:
            rows = c.execute(
                "SELECT * FROM facts WHERE group_id=? ORDER BY key ASC",
                (group_id,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def forget(self, group_id: str, key: str) -> bool:
        """Supprime un fait. Retourne True s'il existait."""
        with connection() as c:
            cur = c.execute(
                "DELETE FROM facts WHERE group_id=? AND key=?",
                (group_id, key),
            )
            return cur.rowcount > 0

    @staticmethod
    def format_for_prompt(facts: list[dict]) -> str:
        """Rend les faits sous forme injectable dans le system prompt.

        Format intentionnellement compact : 1 ligne par fait, `key : value`.
        Les méta (source, confidence, updated_at) ne sont pas montrées au LLM
        pour ne pas polluer son raisonnement — il a juste besoin de la
        connaissance "vraie maintenant"."""
        if not facts:
            return ""
        lines = ["Faits actuels du groupe (vérité présente, à jour) :"]
        for f in facts:
            lines.append(f"- {f['key']} : {f['value']}")
        return "\n".join(lines)

    @staticmethod
    def format_for_debug(facts: list[dict]) -> str:
        """Rend lisible pour la commande /facts debug."""
        if not facts:
            return "🧠 *Mémoire sémantique* : vide.\n\n_Aucun fait retenu pour ce groupe._"
        lines = ["🧠 *Mémoire sémantique du groupe*", ""]
        for f in facts:
            updated = f["updated_at"][:16].replace("T", " ")
            lines.append(f"• `{f['key']}` → {f['value']}  _(maj {updated})_")
        return "\n".join(lines)
