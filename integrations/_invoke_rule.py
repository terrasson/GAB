"""Préambule commun rappelant au LLM qu'il faut INVOQUER, pas décrire,
un tool-call. Extrait dans un module utilitaire sans dépendance pour
permettre aux intégrations externes (palier 3+) de le réutiliser sans
créer d'import circulaire avec `core.tools`.
"""

INVOKE_RULE = (
    "IMPORTANT (contrat d'invocation) : pour utiliser cette fonction, tu DOIS "
    "l'invoquer réellement via le mécanisme tool-calling de l'API. Tu ne dois "
    "JAMAIS répondre en texte avec une phrase qui décrit l'appel "
    "(« Sondage créé : … », « J'ai créé la liste », « Voici votre rappel : … »). "
    "Le système GAB n'exécute aucune action à partir de ton texte — seul un vrai "
    "tool-call structuré déclenche la création de l'objet et l'affichage des "
    "boutons. Si tu hésites entre répondre en texte et invoquer la fonction, "
    "et que tu as toutes les informations nécessaires, INVOQUE.\n\n"
)
