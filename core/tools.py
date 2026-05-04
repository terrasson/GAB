"""Définitions des outils (tool calling / function calling) exposés au LLM.

Format OpenAI tools-calling. Les providers OpenAI-compatibles (DeepSeek,
OpenAI, Mistral, …) reconnaissent ces définitions nativement. Ollama et
Anthropic les ignorent pour le moment (les utilisateurs gardent les
commandes slash en fallback).

Règle d'or : la description d'un outil EST son contrat avec le LLM. C'est
elle qui décide quand il sera appelé et avec quels arguments. Toute règle
métier (« n'invente jamais d'options ») doit être dans la description.

Note d'ingénierie : on observe parfois que certains LLM "simulent" un
tool call en répondant en texte (« Liste créée : ... ») au lieu d'invoquer
réellement la fonction. Pour décourager ce comportement, chaque
description rappelle explicitement « tu DOIS invoquer cette fonction, pas
décrire l'appel en texte ».
"""

# Préambule commun rappelant qu'il faut INVOQUER, pas DÉCRIRE.
_INVOKE_RULE = (
    "IMPORTANT (contrat d'invocation) : pour utiliser cette fonction, tu DOIS "
    "l'invoquer réellement via le mécanisme tool-calling de l'API. Tu ne dois "
    "JAMAIS répondre en texte avec une phrase qui décrit l'appel "
    "(« Sondage créé : … », « J'ai créé la liste », « Voici votre rappel : … »). "
    "Le système GAB n'exécute aucune action à partir de ton texte — seul un vrai "
    "tool-call structuré déclenche la création de l'objet et l'affichage des "
    "boutons. Si tu hésites entre répondre en texte et invoquer la fonction, "
    "et que tu as toutes les informations nécessaires, INVOQUE.\n\n"
)

CREATE_POLL_TOOL = {
    "type": "function",
    "function": {
        "name": "create_poll",
        "description": (
            _INVOKE_RULE +
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

CREATE_REMINDER_TOOL = {
    "type": "function",
    "function": {
        "name": "create_reminder",
        "description": (
            _INVOKE_RULE +
            "Programme un rappel à envoyer dans le groupe (ou en DM si on est en "
            "conversation privée) à une date/heure précise. Utile quand un membre "
            "demande « rappelle-nous », « préviens-moi », « n'oublions pas que… ».\n\n"
            "RÈGLE ABSOLUE : tu n'inventes JAMAIS la date/heure ni le contenu du "
            "rappel. Les deux viennent UNIQUEMENT de ce que l'utilisateur a écrit "
            "dans l'échange en cours. Si la demande est ambiguë (« rappelle-nous » "
            "sans heure, ou « demain » sans précision d'heure), tu réponds en texte "
            "(pas d'appel à cette fonction) en demandant la précision manquante : "
            "« À quelle heure veux-tu que je rappelle ? » ou « Pour quelle date ? ».\n\n"
            "PÉRIMÈTRE TEMPOREL : la date et le contenu doivent venir de l'échange "
            "immédiat, pas de messages anciens piochés dans la mémoire du groupe. "
            "Si l'historique contient un sujet candidat mais qu'il n'est pas redonné "
            "maintenant, tu demandes confirmation avant d'appeler create_reminder.\n\n"
            "FORMAT DE LA DATE : tu convertis le langage naturel français (« demain "
            "19h », « vendredi 8h », « dans 2 heures », « le 8 mai à 19h ») en ISO "
            "8601 timezone-aware. Fuseau par défaut : Europe/Paris (`+02:00` en "
            "heure d'été — d'avril à octobre — sinon `+01:00`). Tu utilises la date "
            "ET l'heure courantes injectées dans le system prompt comme référence "
            "pour résoudre les expressions relatives.\n\n"
            "La date doit toujours être dans le futur. Si l'utilisateur donne une "
            "date passée, tu lui fais remarquer en texte sans appeler la fonction."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "fires_at": {
                    "type": "string",
                    "description": (
                        "Date/heure du rappel au format ISO 8601 timezone-aware. "
                        "Ex : « 2026-05-04T19:00:00+02:00 »."
                    ),
                },
                "message": {
                    "type": "string",
                    "description": (
                        "Texte court et clair du rappel, reprenant fidèlement ce "
                        "que l'utilisateur a demandé de rappeler. Ex : « RDV chez "
                        "Mario », « Anniversaire d'Audrey », « Réserver le train »."
                    ),
                },
            },
            "required": ["fires_at", "message"],
        },
    },
}


CREATE_LIST_TOOL = {
    "type": "function",
    "function": {
        "name": "create_list",
        "description": (
            _INVOKE_RULE +
            "Crée une liste partagée modifiable dans le groupe Telegram courant. "
            "Cas d'usage typiques : « qui amène quoi pour le BBQ ? », liste de "
            "courses, partage de tâches, qui paie quoi. Les membres cliquent sur "
            "un item pour se l'attribuer (claim). Un item ne peut être pris que "
            "par une seule personne ; le claimer peut le libérer en re-cliquant.\n\n"
            "RÈGLE ABSOLUE : tu n'inventes JAMAIS d'items. Les items viennent "
            "UNIQUEMENT de ce que les membres du groupe ont écrit dans la "
            "conversation. Si quelqu'un demande une liste sans préciser les items, "
            "tu réponds en texte (pas d'appel à cette fonction) en demandant : "
            "« Qu'est-ce qu'il faut mettre dans la liste ? ».\n\n"
            "PÉRIMÈTRE TEMPOREL : les items doivent provenir UNIQUEMENT du fil "
            "de discussion immédiat sur cette liste. Tu n'extrais JAMAIS d'items "
            "depuis des messages antérieurs au fil actuel, même si tu te souviens "
            "qu'un membre avait mentionné des choses similaires plus tôt. Si "
            "l'historique ancien contient des items candidats mais qu'ils n'ont "
            "pas été redonnés maintenant, tu DEMANDES à l'utilisateur de les "
            "confirmer ou redonner.\n\n"
            "Tu n'appelles cette fonction QUE quand au moins 1 item a été clairement "
            "exprimé par les humains DANS LE FIL ACTUEL (une liste à 1 seul item "
            "est OK — contrairement aux sondages qui en exigent 2). Tu peux "
            "reformuler les items pour qu'ils soient concis et clairs sur des "
            "boutons (« la salade composée du resto » → « Salade »), mais ne "
            "jamais en ajouter ni en retirer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": (
                        "Titre court de la liste, en français. Ex : « BBQ », "
                        "« Courses du week-end », « Pique-nique »."
                    ),
                },
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "description": (
                        "Liste des items proposés par les membres du groupe. "
                        "Au moins 1. Chaque item est un libellé court (1-4 mots)."
                    ),
                },
            },
            "required": ["title", "items"],
        },
    },
}


CREATE_EVENT_TOOL = {
    "type": "function",
    "function": {
        "name": "create_event",
        "description": (
            _INVOKE_RULE +
            "Ajoute un événement à l'agenda du groupe. À utiliser quand un "
            "membre annonce une sortie, un anniversaire, un rendez-vous ou "
            "toute date future que le groupe veut garder en mémoire (« on a "
            "un BBQ chez Marc samedi », « anniv d'Audrey vendredi 23 »).\n\n"
            "RÈGLE ABSOLUE : tu n'inventes JAMAIS la date, l'heure, le titre "
            "ni le lieu. Toutes ces infos viennent UNIQUEMENT de ce que les "
            "membres ont écrit dans la conversation. Si une info essentielle "
            "manque (date floue comme « bientôt », titre absent, etc.), tu "
            "réponds en texte (pas d'appel à cette fonction) en demandant la "
            "précision : « À quelle date exactement ? », « Comment veux-tu "
            "appeler cet événement ? ».\n\n"
            "PÉRIMÈTRE TEMPOREL : titre, date et lieu doivent venir de "
            "l'échange immédiat où l'événement est demandé. Tu n'extrais "
            "JAMAIS d'événement depuis des messages anciens du groupe sans "
            "que le membre le redonne maintenant.\n\n"
            "FORMAT DE LA DATE : tu convertis le langage naturel français "
            "(« samedi 19h », « le 15 mai à 19h », « dans 3 jours à midi ») "
            "en ISO 8601 timezone-aware. Fuseau par défaut : Europe/Paris "
            "(`+02:00` en heure d'été, `+01:00` en heure d'hiver). Tu utilises "
            "la date/heure courantes injectées dans le system prompt comme "
            "référence pour résoudre les expressions relatives.\n\n"
            "La date doit être dans le futur. Si l'utilisateur donne une date "
            "passée, tu lui fais remarquer en texte sans appeler la fonction.\n\n"
            "Le lieu (`location`) est OPTIONNEL — tu ne le passes que si le "
            "membre l'a explicitement mentionné. N'invente pas de lieu."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": (
                        "Titre court et descriptif de l'événement, en français. "
                        "Ex : « BBQ chez Marc », « Anniv Audrey », « Tournoi Mölkky »."
                    ),
                },
                "starts_at": {
                    "type": "string",
                    "description": (
                        "Date/heure de début au format ISO 8601 timezone-aware. "
                        "Ex : « 2026-05-15T19:00:00+02:00 »."
                    ),
                },
                "location": {
                    "type": "string",
                    "description": (
                        "Lieu de l'événement (optionnel). Ex : « chez Marc 12 rue X », "
                        "« Buttes-Chaumont », « Restau Mario ». Vide ou absent si "
                        "aucun lieu n'a été mentionné."
                    ),
                },
            },
            "required": ["title", "starts_at"],
        },
    },
}


# Outils exposés selon le contexte. En groupe : tout ; en DM : uniquement les
# outils qui ont du sens pour un user seul (sondages, listes et événements
# de groupe exigent un groupe).
GROUP_TOOLS: list[dict] = [
    CREATE_POLL_TOOL, CREATE_REMINDER_TOOL, CREATE_LIST_TOOL, CREATE_EVENT_TOOL,
]
DM_TOOLS:    list[dict] = [CREATE_REMINDER_TOOL]
