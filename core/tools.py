"""Définitions des outils (tool calling / function calling) exposés au LLM.

Format OpenAI tools-calling. Les providers OpenAI-compatibles (DeepSeek,
OpenAI, Mistral, …) reconnaissent ces définitions nativement. Ollama et
Anthropic les ignorent pour le moment (les utilisateurs gardent les
commandes slash en fallback).

Règle d'or : la description d'un outil EST son contrat avec le LLM. C'est
elle qui décide quand il sera appelé et avec quels arguments. Toute règle
métier (« n'invente jamais d'options ») doit être dans la description.
"""

CREATE_POLL_TOOL = {
    "type": "function",
    "function": {
        "name": "create_poll",
        "description": (
            "Crée un sondage à choix multiples dans le groupe Telegram courant pour "
            "aider le groupe à décider entre plusieurs options proposées par ses membres "
            "(restaurant, sortie, date, activité, etc.).\n\n"
            "RÈGLE ABSOLUE : tu ne dois JAMAIS inventer d'options de toi-même. Les "
            "options viennent UNIQUEMENT de ce qu'ont écrit les membres du groupe dans "
            "la conversation. Si un membre demande un sondage sans préciser les options, "
            "ou n'en propose qu'une seule, tu réponds en texte (pas d'appel à cette "
            "fonction) en lui demandant : « Quelles options voulez-vous proposer ? ».\n\n"
            "PÉRIMÈTRE TEMPOREL : les options doivent provenir UNIQUEMENT du fil de "
            "discussion immédiat sur ce sondage — c'est-à-dire des messages échangés "
            "DEPUIS QUE quelqu'un a demandé un sondage maintenant. Tu n'extrais JAMAIS "
            "d'options depuis des messages antérieurs au fil actuel, même si tu te "
            "souviens qu'un membre avait mentionné des options similaires plus tôt dans "
            "la journée. Si tu vois des options dans l'historique ancien mais qu'elles "
            "n'ont pas été redonnées dans l'échange en cours, tu DEMANDES à l'utilisateur "
            "de les confirmer ou redonner. Le sondage est un acte délibéré, pas une "
            "extraction silencieuse depuis la mémoire du groupe.\n\n"
            "Tu n'appelles cette fonction QUE quand au moins 2 options claires ont été "
            "exprimées par les humains DANS LE FIL ACTUEL. Tu peux reformuler les options "
            "pour les rendre concises (ex : « pizza italienne du coin » → « Pizza »), "
            "mais ne jamais en ajouter ni en retirer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": (
                        "Question claire et concise du sondage, en français, terminée "
                        "par un point d'interrogation. Ex : « Restaurant vendredi ? », "
                        "« Quelle activité samedi ? »."
                    ),
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "description": (
                        "Liste des options proposées par les membres du groupe. "
                        "Au moins 2. Chaque option est un libellé court (1-4 mots)."
                    ),
                },
            },
            "required": ["question", "options"],
        },
    },
}

# Liste exposée par défaut en groupe (s'enrichira aux paliers suivants :
# create_reminder, create_list, create_event, …).
GROUP_TOOLS: list[dict] = [CREATE_POLL_TOOL]
