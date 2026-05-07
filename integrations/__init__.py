"""Intégrations externes (palier 3) — APIs tierces que GAB consulte
pour le compte du groupe.

Convention : un sous-dossier par fournisseur ou par catégorie. Chaque
intégration expose au moins :
- un dict `*_TOOL` au format OpenAI tools-calling, à enregistrer dans
  `core/tools.py::GROUP_TOOLS` ou `DM_TOOLS` selon l'usage ;
- une coroutine `execute(args: dict) -> str` qui retourne du texte
  *destiné au LLM* (pas au user final) — le LLM le reformule ensuite.

Principe directeur : *GAB consulte, l'utilisateur réserve*. Aucune
intégration ne doit faire de paiement ni d'action irréversible.
"""
