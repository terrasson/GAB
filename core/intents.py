"""
Détection d'intention conversationnelle (palier 2.2).

Trois pièces :

1. **Pré-filtre regex** (`looks_like_intent`) — cheap, en mémoire, FR.
   Rejette ~95 % des messages anodins (« lol », « ok », « 😂ʼ ») sans
   appeler le LLM. Indispensable pour le coût : sans ce filtre, on
   appellerait le LLM sur chaque message du groupe (×10-50 vs aujourd'hui).

2. **Cooldown + opt-out par groupe** (`GroupSettings`) — table SQLite
   `group_settings (group_id, intent_enabled, last_intent_at)`. GAB
   n'intervient spontanément qu'au plus une fois par
   `INTENT_COOLDOWN_MINUTES` (env, défaut 60) par groupe. Désactivable
   via `/intent off` pour les groupes qui n'en veulent pas.

3. **Catégorie d'intention détectée** (`classify_intent_keywords`) — mappe
   le pré-filtre vers une étiquette (`poll | reminder | list | event |
   members | other`). Aide le LLM scan à se concentrer.

Le scan LLM lui-même (`_llm_scan_intent`) vit dans `core/agent.py` et
n'invoque cette détection qu'après que le pré-filtre a passé.
"""

import os
import re
import logging
from datetime import datetime, timezone, timedelta

from core.storage import connection

logger = logging.getLogger("GAB.intents")


# ── Pré-filtre regex FR ─────────────────────────────────────────────────────
#
# Chaque catégorie est une liste de patterns insensibles à la casse, déjà
# compilés. Un message qui matche au moins un pattern dans une catégorie
# est candidat au scan LLM.
#
# Règle de design : on préfère LARGE (faux positifs OK) à STRICT (rater
# une intention). Le LLM scan filtrera derrière. Les patterns sont volontairement
# courts pour matcher les variations (« on pourrait », « on pourra »,
# « pourquoi pas »).

_PATTERNS = {
    "poll": [
        r"\b(resto|restaurant|bouffe|manger|d[îi]ner|d[ée]jeuner|pizza|sushi|burger)\b",
        r"\b(on (h[ée]site|sait pas|d[ée]cide pas)|qu['e ]est-?ce qu'?on (fait|prend|choisit))\b",
        r"\b(vote|sondage|on (choisit|d[ée]cide))\b",
        r"\b(plut[ôo]t|ou)\s+\w+\s+\?",   # « pizza ou sushi ? »
    ],
    "reminder": [
        r"\brappel\w*\b",                # rappelle, rappelez, rappeler, rappelle-moi, …
        r"\b(n'?oubli|oubli)\w*\b",      # n'oublie, n'oubliez, oublier, …
        r"\b(faut pas oublier|penser? [aà])\b",
        r"\bpr[ée]vien\w*\b|\b(notif|alerte)\b",
    ],
    "event": [
        r"\b(rdv|rendez-?vous|on a (un|une|du)|on se (voit|retrouve)|on fait)\b.*\b(samedi|dimanche|lundi|mardi|mercredi|jeudi|vendredi|demain|ce soir|ce week-?end|le \d+)\b",
        r"\b(anniv|anniversaire|bbq|barbecue|sortie|voyage|week-?end)\b",
        r"\b(\d{1,2}h(\d{2})?|\d{1,2}:\d{2})\b",  # heure « 19h », « 19h30 », « 19:30 »
    ],
    "list": [
        r"\b(qui am[èe]ne|qui apporte|qui fait|qui s'occupe|qui prend en charge)\b",
        r"\b(liste|courses?|qui paie|qui paye|à apporter)\b",
    ],
    "members": [
        r"\b(on est combien|qui (vient|est l[àa]|est dispo|est ok|est partant))\b",
        r"\b(combien (on|nous) (sommes|serons|seront))\b",
    ],
    "suggestion": [
        # Marqueur générique d'une proposition collective — souvent prélude à
        # un sondage ou un événement.
        r"\b(on (pourrait|devrait|pourra|veut)|et si on|pourquoi pas|ça vous dit|ça vous tente)\b",
    ],
}

_COMPILED = {
    cat: [re.compile(p, re.IGNORECASE | re.UNICODE) for p in patterns]
    for cat, patterns in _PATTERNS.items()
}


def looks_like_intent(text: str) -> bool:
    """Pré-filtre cheap : True si le message ressemble à une intention
    actionnable. Aucun appel LLM, pure regex. Cible : 5-10 % de faux
    positifs (qui seront filtrés par le scan LLM derrière), 0 faux négatifs
    sur les vraies intentions. Sur message court (< 4 mots), on n'engage
    pas le scan : trop peu de signal."""
    if not text:
        return False
    t = text.strip()
    if len(t.split()) < 4:
        return False
    for patterns in _COMPILED.values():
        for p in patterns:
            if p.search(t):
                return True
    return False


def classify_intent_keywords(text: str) -> list[str]:
    """Renvoie les catégories qui matchent. Utile pour aiguiller le LLM
    scan (« voici les indices : poll, suggestion → suggère un sondage »)
    et pour les logs de débogage."""
    matched: list[str] = []
    if not text:
        return matched
    for cat, patterns in _COMPILED.items():
        for p in patterns:
            if p.search(text):
                matched.append(cat)
                break
    return matched


# ── GroupSettings — opt-out + cooldown par groupe ───────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cooldown_minutes() -> int:
    """Délai minimum entre deux interventions spontanées dans un même
    groupe. Tunable via env pour les tests, défaut 60 min."""
    try:
        return max(1, int(os.getenv("INTENT_COOLDOWN_MINUTES", "60")))
    except ValueError:
        return 60


class GroupSettings:
    """Préférences par groupe (intent_enabled + last_intent_at)."""

    def get(self, group_id: str) -> dict:
        """Retourne un dict avec les défauts si le groupe n'a pas encore
        de ligne (intent activé par défaut, jamais intervenu)."""
        with connection() as c:
            row = c.execute(
                "SELECT * FROM group_settings WHERE group_id=?",
                (group_id,),
            ).fetchone()
        if not row:
            return {
                "group_id":       group_id,
                "intent_enabled": True,
                "last_intent_at": None,
            }
        return {
            "group_id":       row["group_id"],
            "intent_enabled": bool(row["intent_enabled"]),
            "last_intent_at": row["last_intent_at"],
        }

    def set_intent_enabled(self, group_id: str, enabled: bool) -> None:
        with connection() as c:
            c.execute(
                "INSERT INTO group_settings (group_id, intent_enabled) VALUES (?, ?) "
                "ON CONFLICT(group_id) DO UPDATE SET intent_enabled=excluded.intent_enabled",
                (group_id, 1 if enabled else 0),
            )
        logger.info("intent_enabled[%s] = %s", group_id, enabled)

    def mark_intent_fired(self, group_id: str) -> None:
        """Note l'instant d'une intervention spontanée pour le cooldown."""
        with connection() as c:
            c.execute(
                "INSERT INTO group_settings (group_id, last_intent_at) VALUES (?, ?) "
                "ON CONFLICT(group_id) DO UPDATE SET last_intent_at=excluded.last_intent_at",
                (group_id, _now()),
            )

    def cooldown_ok(self, group_id: str) -> bool:
        """True si le cooldown est respecté (jamais intervenu, ou dernier
        intent > INTENT_COOLDOWN_MINUTES)."""
        s = self.get(group_id)
        if not s["last_intent_at"]:
            return True
        try:
            last = datetime.fromisoformat(s["last_intent_at"])
        except ValueError:
            return True
        delta = datetime.now(timezone.utc) - last
        return delta >= timedelta(minutes=_cooldown_minutes())
