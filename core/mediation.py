"""
Médiation douce en cas de désaccord détecté (palier 2.5).

Pendant du palier 2.2 (intent positif) : 2.5 cherche le SIGNAL
DE TENSION dans un message, et fait passer la main au LLM scan
seulement si le pré-filtre matche. La cible est volontairement plus
serrée que 2.2 (~1-2 % des messages, contre ~5 % pour 2.2) car le
coût d'une intervention de médiation ratée est très élevé : un GAB
qui s'invite dans une discussion animée pour rien paraît sentencieux
ou maladroit.

Patterns retenus (FR, conservateurs) :
- **Insultes / mépris** explicites — « con », « débile », « ferme-la »,
  « ta gueule », « n'importe quoi », « tu plaisantes »
- **Désaccord vif** — « pas du tout », « absolument pas », « jamais
  de la vie », « hors de question »
- **Ponctuation excessive** — `!!!` ou `???` (≥ 3 d'affilée), signe
  d'agacement ou d'incrédulité
- **Caps dominant** — > 50 % des lettres en MAJUSCULES sur un message
  de ≥ 8 mots (cris)

Le scan LLM derrière (cf. `core/agent.py::scan_mediation`) tranchera :
- s'il s'agit d'humour / sarcasme entre amis → silence
- si désaccord factuel ≥ 2 personnes distinctes → on propose
  *uniquement* une reformulation/sondage, jamais de prendre parti

Garde-fous partagés avec 2.2/2.3 :
- whitelist groupe
- `intent_enabled` ON (cohérent avec opt-out global `/intent off`)
- cooldown global `GroupSettings.cooldown_ok` (60 min, partagé)
"""

import re
import logging

logger = logging.getLogger("GAB.mediation")


# Patterns volontairement courts pour matcher les variations.
_TENSION_PATTERNS = [
    # Insultes / mépris (formes courtes les plus communes en FR)
    r"\b(con(?:ne|nard|nasse)?|débile|idiot|crétin|imbécile|nul(?:le|lard)?)\b",
    r"\b(ferme[- ]la|ta gueule|tg|stfu)\b",
    r"\b(n['e ]importe quoi|tu plaisantes|tu rigoles|tu te fous de)\b",

    # Désaccord vif
    r"\b(pas du tout|absolument pas|jamais de la vie|hors de question)\b",
    r"\b(arrête (de|tes)|je m['e ]en fous|j['e ]en ai (marre|ras le bol))\b",

    # Ponctuation excessive (≥ 3 ! ou ? d'affilée)
    r"[!?]{3,}",
]

_COMPILED = [re.compile(p, re.IGNORECASE | re.UNICODE) for p in _TENSION_PATTERNS]


def _is_caps_dominant(text: str) -> bool:
    """True si le message est majoritairement en MAJUSCULES sur ≥ 8 mots
    (signature visuelle de cri). On ignore chiffres et ponctuation."""
    words = text.split()
    if len(words) < 8:
        return False
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 12:
        return False
    upper = sum(1 for ch in letters if ch.isupper())
    return upper / len(letters) > 0.5


def looks_like_tension(text: str) -> bool:
    """Pré-filtre cheap : True si le message porte des marqueurs de
    tension. Cible serrée (~1-2 % des messages) — mieux vaut rater un
    cas que faire une intervention de médiation maladroite. Sur
    message court (< 4 mots), pas assez de signal — on rejette.
    """
    if not text:
        return False
    t = text.strip()
    if len(t.split()) < 4:
        return False
    for p in _COMPILED:
        if p.search(t):
            return True
    return _is_caps_dominant(t)
