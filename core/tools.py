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


SET_FACTS_TOOL = {
    "type": "function",
    "function": {
        "name": "set_facts",
        "description": (
            _INVOKE_RULE +
            "Mémorise dans la mémoire sémantique du groupe un ou plusieurs faits "
            "que tu viens d'apprendre dans la conversation, OU qui ont changé "
            "(une décision révisée écrase l'ancienne). Cette mémoire est "
            "distincte de l'historique des messages : elle représente ce qui "
            "est VRAI MAINTENANT pour ce groupe, et elle te sera réinjectée "
            "automatiquement dans toutes tes réponses futures.\n\n"
            "QUAND L'INVOQUER : tu invoques set_facts dans le MÊME tour que ta "
            "réponse à l'utilisateur, dès que tu détectes une information durable "
            "qui mérite d'être retenue (date d'un événement, lieu d'un rdv, "
            "préférence/allergie d'un membre, code wifi, règle du groupe, etc.). "
            "Tu peux invoquer set_facts EN PLUS de répondre en texte — les deux "
            "ne s'excluent pas.\n\n"
            "QUAND NE PAS L'INVOQUER : pour des informations purement "
            "conversationnelles, anecdotiques ou éphémères (« il fait beau », "
            "« j'ai faim », « lol »). La règle : si l'info aura encore du sens "
            "dans 3 jours pour le groupe, c'est un fait à retenir ; sinon non.\n\n"
            "ÉCRASEMENT (UPSERT) : si la `key` existe déjà, l'ancienne valeur "
            "est remplacée. Utilise toujours la même clé pour le même fait — "
            "c'est ce qui permet la mise à jour propre quand le groupe change "
            "d'avis. Exemple : si on avait « event.dinner.date = vendredi » et "
            "que le groupe dit « on change pour samedi », tu invoques set_facts "
            "avec [{key: \"event.dinner.date\", value: \"samedi 9 mai 2026\"}].\n\n"
            "CONVENTION DE CLÉS hiérarchique en snake_case ASCII :\n"
            "- event.<nom_court>.{date, time, place, attendees, notes}\n"
            "- member.<prénom_minuscule>.{allergies, preferences, role}\n"
            "- group.{rules, language, name, wifi_code}\n"
            "- trip.<destination>.{dates, accommodation, transport}\n"
            "Reste cohérent : si tu as déjà utilisé `event.diner.date`, "
            "n'utilise pas `event.dinner.date` ailleurs.\n\n"
            "VALEURS : courtes et lisibles en français naturel — pas de JSON "
            "imbriqué, pas de structure. Une valeur = une chaîne lisible "
            "(« samedi 9 mai 2026 », « chez Mario, 12 rue X », « noix, gluten »)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "facts": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": (
                                    "Clé hiérarchique en snake_case ASCII, "
                                    "ex : « event.dinner.date »."
                                ),
                            },
                            "value": {
                                "type": "string",
                                "description": (
                                    "Valeur courte et lisible en français, "
                                    "ex : « samedi 9 mai 2026 »."
                                ),
                            },
                        },
                        "required": ["key", "value"],
                    },
                    "description": (
                        "Liste des faits à mémoriser ou mettre à jour (batch). "
                        "1 entrée minimum."
                    ),
                },
            },
            "required": ["facts"],
        },
    },
}

FORGET_FACT_TOOL = {
    "type": "function",
    "function": {
        "name": "forget_fact",
        "description": (
            _INVOKE_RULE +
            "Supprime un fait de la mémoire sémantique du groupe. À utiliser "
            "quand un membre annonce explicitement qu'une info n'est plus "
            "valable et qu'aucune nouvelle valeur ne la remplace (« on annule "
            "le dîner », « finalement Audrey n'est plus allergique »).\n\n"
            "ATTENTION : si le membre REMPLACE une info par une nouvelle "
            "(« on change pour samedi »), n'utilise PAS forget_fact — utilise "
            "set_facts qui écrase automatiquement. forget_fact ne sert que "
            "quand on retire un fait sans le remplacer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": (
                        "Clé exacte du fait à oublier, telle qu'elle apparaît "
                        "dans la section « Faits actuels du groupe » du system "
                        "prompt."
                    ),
                },
            },
            "required": ["key"],
        },
    },
}


PROPOSE_INTENT_TOOL = {
    "type": "function",
    "function": {
        "name": "propose_intent",
        "description": (
            _INVOKE_RULE +
            "Outil RÉSERVÉ au mode SCAN d'intention (palier 2.2). Tu es appelé "
            "en mode silencieux pour examiner les derniers messages d'un groupe "
            "et juger si une intention claire et collective émerge — auquel cas "
            "tu invoques cet outil avec une suggestion courte que GAB enverra "
            "spontanément au groupe.\n\n"
            "RÈGLE D'OR — PARCIMONIE : tu n'invoques cet outil QUE si TOUS les "
            "critères suivants sont vrais :\n"
            "1. L'intention est CLAIRE (pas une vague allusion).\n"
            "2. Au moins 2 membres distincts en parlent dans le fil récent "
            "   (signe d'un sujet collectif, pas d'une remarque isolée).\n"
            "3. Une action concrète de GAB serait UTILE (lancer un sondage, "
            "   programmer un rappel, ouvrir une liste, ajouter un événement, "
            "   consulter les membres).\n"
            "4. Le groupe ne semble pas déjà en train de gérer le sujet "
            "   sans toi.\n"
            "Si le moindre critère manque, tu N'INVOQUES PAS l'outil et tu "
            "réponds en texte vide (le système comprend que tu te tais).\n\n"
            "EXEMPLES (extraits de conversation → décision) :\n"
            "  • « Marc: on pourrait aller au resto samedi ? / Audrey: oui ! / "
            "    Marc: pizza ou sushi ? » → INVOQUE avec action_type=poll, "
            "    suggestion='Je peux lancer un sondage pizza vs sushi pour "
            "    samedi soir ?'\n"
            "  • « Marc: il fait beau » → IGNORE (pas d'intention).\n"
            "  • « Marc: on devrait penser à réserver le train pour Lyon » → "
            "    si suivi par d'autres membres qui rebondissent : INVOQUE avec "
            "    action_type=reminder, suggestion='Je peux vous mettre un "
            "    rappel pour réserver le train ?'\n\n"
            "FORMAT DE LA SUGGESTION : une seule phrase courte, en français, "
            "qui se termine par un point d'interrogation pour inviter le "
            "groupe à dire oui ou non. JAMAIS d'action irréversible — tu "
            "PROPOSES, tu n'agis pas. Préfixe optionnellement par 💡 (déjà "
            "ajouté côté code).\n\n"
            "PAS DE BAVARDAGE : si tu hésites, tu te tais. Le coût d'une "
            "intervention spontanée raté est élevé (le groupe se sent harcelé) ; "
            "le coût d'une intervention loupée est faible (les membres "
            "demanderont à GAB d'eux-mêmes)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "enum": ["poll", "reminder", "list", "event", "members", "other"],
                    "description": (
                        "Type d'action que GAB suggérerait : poll (sondage), "
                        "reminder (rappel), list (liste partagée), event "
                        "(événement à l'agenda), members (consulter qui est là), "
                        "other (autre, à expliciter dans suggestion)."
                    ),
                },
                "suggestion": {
                    "type": "string",
                    "description": (
                        "Phrase courte (≤ 25 mots) terminée par « ? », à "
                        "envoyer telle quelle dans le groupe. Ex : « Je peux "
                        "lancer un sondage pizza vs sushi pour samedi soir ? »."
                    ),
                },
            },
            "required": ["action_type", "suggestion"],
        },
    },
}


# Outils exposés selon le contexte. En groupe : tout ; en DM : uniquement les
# outils qui ont du sens pour un user seul (sondages, listes, événements et
# faits de groupe exigent un groupe). PROPOSE_INTENT_TOOL n'est PAS dans
# GROUP_TOOLS — il est exposé séparément dans le mode scan d'intention,
# avec son propre system prompt.
GROUP_TOOLS: list[dict] = [
    CREATE_POLL_TOOL, CREATE_REMINDER_TOOL, CREATE_LIST_TOOL, CREATE_EVENT_TOOL,
    SET_FACTS_TOOL, FORGET_FACT_TOOL,
]
DM_TOOLS:    list[dict] = [CREATE_REMINDER_TOOL]
SCAN_TOOLS:  list[dict] = [PROPOSE_INTENT_TOOL]
