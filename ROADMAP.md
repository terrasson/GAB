# GAB — Roadmap

> GAB n'est pas un simple chatbot. Sa vocation : être le **concierge-agent**
> d'un groupe humain qui organise une sortie, un voyage, un anniversaire,
> ou tout autre événement collectif.

## Vision : le rôle de GAB dans un groupe

1. **Organiser & planifier** — dates, lieux, réservations, logistique
2. **Animer & cohéser** — sondages, idées, rituels, médiation
3. **Communiquer** — centraliser l'info, rappeler les échéances
4. **Gérer les imprévus** — plans B, désaccords, sécurité
5. **Motiver & inspirer** — défis, valorisation, surprises
6. **Représenter** — négocier avec prestataires, soigner l'image du groupe

Le prompt système complet est dans [`prompts/system.md`](prompts/system.md).

---

## Paliers

### Palier 0 — MVP technique de base

- [x] Bot Telegram opérationnel (polling)
- [x] Architecture multi-plateformes (Telegram, WhatsApp, Discord)
- [x] LLM-agnostique : Ollama, OpenAI, DeepSeek, Claude, Mistral, Groq, Together
- [x] Collecte automatique des IDs membres dans un groupe (`ChatMemberHandler`)
- [x] Commande `/members` pour vérifier les IDs collectés
- [x] Prompt système chargé depuis un fichier éditable (`prompts/system.md`)
- [ ] Configuration BotFather effectuée (`/setjoingroups`, `/setprivacy`)
- [ ] Premier test réel sur un groupe Telegram avec plusieurs humains

### Palier 1 — Outils de coordination

- [ ] **Mémoire par groupe** (refacto de `core/memory.py`) — actuellement par user
- [ ] **`/sondage`** — `/sondage Restaurant vendredi ? Pizza | Sushis | Burger` → vote → comptage
- [ ] **`/rappel`** — programmer une notif (`/rappel J-1 19h RDV chez Mario`)
- [ ] **`/liste`** — liste partagée modifiable (qui amène quoi, qui paie quoi)
- [ ] **`/agenda`** — calendrier des événements du groupe
- [ ] **Mode écoute passive** — n'intervient que si mentionné `@GAB` ou commande explicite
- [ ] **Flux de bienvenue intelligent en groupe** — sur ajout du bot
  (`MyChatMemberHandler`), détecter si rejoint comme **simple membre** vs
  **admin** :
  - Membre simple → message d'onboarding avec lien magique de re-promotion
    (`?startgroup=true&admin=…`) et instructions pas-à-pas
  - Admin → message de confirmation et liste des commandes utiles
  → l'utilisateur lambda ne doit JAMAIS avoir à manipuler manuellement les
  permissions admin pour que GAB fonctionne pleinement.

### Palier 2 — Intelligence proactive

> **Pierre angulaire** : aujourd'hui GAB n'a qu'une mémoire **épisodique**
> (l'historique des messages). Conséquence : si un fait est dit puis corrigé
> plus tard, le LLM voit les deux versions et peut s'embrouiller. Le
> palier 2 introduit la **mémoire sémantique** — la connaissance "vraie
> maintenant" qui s'écrase quand on la corrige. C'est ce qui transforme
> GAB d'un chatbot conversationnel en agent qui retient vraiment.

#### 2.1 — Mémoire sémantique structurée (foundation)

> **Distinction clé** :
> - Mémoire épisodique = "ce qui a été dit et quand" (déjà en SQLite via
>   palier 1.1)
> - Mémoire sémantique = "ce qui est vrai actuellement" (à construire)

##### Architecture proposée

Nouvelle table SQLite `facts` :

```sql
CREATE TABLE facts (
    group_id    TEXT NOT NULL,
    key         TEXT NOT NULL,         -- ex : "event.dinner.date"
    value       TEXT NOT NULL,
    confidence  REAL NOT NULL DEFAULT 1.0,
    source      TEXT NOT NULL,         -- "user:<id>" ou "auto"
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (group_id, key)
);
```

Convention de clés hiérarchique : `event.<nom>.{date,place,time,attendees}`,
`member.<id>.{allergies,preferences}`, `group.{rules,language}`.

##### Workflow

1. **Extraction** : à chaque message en groupe, GAB détecte les faits
   nouveaux ou mis à jour via le LLM (instruction dédiée dans le system
   prompt + outputs structurés `extract_facts({...})`).
2. **Mise à jour** : un fait avec la même `key` **écrase** l'ancien
   (UPSERT). L'historique des changements peut être tracé via une table
   `facts_history` séparée si besoin.
3. **Injection** : à chaque requête LLM, les faits actuels du groupe sont
   ajoutés au system prompt sous forme structurée :
   ```
   ---
   Faits actuels du groupe Test2 :
   - event.dinner.date : vendredi 8 mai 2026
   - event.dinner.place : chez Mario
   - event.dinner.time : 21h (mis à jour il y a 5 minutes)
   ```
4. **Conflit** : si un user dit "on change pour samedi" alors qu'on avait
   "vendredi", GAB confirme avant d'écraser : *"On passe bien de
   vendredi à samedi ? Je mets à jour."*

##### Cases d'usage débloqués

- "Quand on dîne ?" → GAB regarde `event.dinner.date`, pas l'historique
- "On change le rdv pour 21h" → écrase, plus de pollution future
- "Audrey est allergique aux noix" → stocké dans `member.audrey.allergies`,
  réutilisé quand on parle restau
- "Le code wifi de l'airbnb c'est XYZ" → `event.trip.wifi`

##### Fichiers à créer / modifier

- `core/facts.py` (nouveau) : `FactStore` + `extract_facts_from_message()`
- `core/storage.py` : ajouter le schema de `facts` à `_SCHEMA`
- `core/agent.py::_build_system_prompt()` : injecter les faits du groupe
- `prompts/system.md` : ajouter une section "Comment retenir des faits"
- (optionnel) Commande `/facts` pour debug : afficher la sémantique
  actuelle d'un groupe

#### 2.2 — Détection d'intention en conversation

- [ ] « on pourrait aller au resto » → GAB propose un `/sondage` Restaurant
- [ ] « il faut qu'on rappelle Audrey jeudi » → propose un `/rappel`
- [ ] « on est combien ? » → consulte `/members` automatiquement

#### 2.3 — Personnalité "chef de groupe"

- [ ] GAB intervient au **bon moment** : pas trop bavard, pas absent quand
      on a besoin de lui
- [ ] Heuristique : intervient si silence prolongé sur une décision en
      attente, ou si une intention claire est détectée

#### 2.4 — Récap multi-jours / multi-membres

- [ ] `/recap` ou intervention spontanée : "voici ce qui s'est dit cette
      semaine, voici les décisions actées, voici ce qu'il reste à trancher"
- [ ] Utilise la mémoire sémantique (2.1) pour les décisions actées et
      l'épisodique pour le narratif

#### 2.5 — Médiation douce en cas de désaccord détecté

- [ ] Détection de tension (analyse de tonalité par le LLM)
- [ ] GAB propose un break, reformule le désaccord en termes neutres,
      suggère un sondage si besoin pour trancher

### Palier 3 — Outils du concierge (intégrations externes)

> **Principe directeur : GAB consulte, l'utilisateur réserve.**
> GAB cherche, compare, prépare la décision et fournit le **lien direct vers
> la page de réservation officielle**. La transaction (paiement, identité,
> billet) reste sur le site du prestataire. Ça nous évite tout le périmètre
> légal du voyage agréé (DSP2, RGPD voyage, agrément OTA, conformité IATA…)
> qui demanderait une équipe juridique et une société dédiée.

#### 3a — Recherche & comparaison (le LLM appelle des outils)

Prérequis technique : étendre `LLMClient.chat()` pour supporter le
**function calling** (format OpenAI tools). Manifest le supporte déjà.
Architecture : un dossier `tools/` avec un fichier par intégration,
chacun expose une fonction `execute(args) → str` documentée pour le LLM.

- [ ] **Météo** ([Open-Meteo](https://open-meteo.com), gratuit sans clé)
- [ ] **Restaurant / activité** (Google Places API, Yelp Fusion)
- [ ] **Tarifs train** (SNCF Connect API ; Trainline en B2B plus tard)
- [ ] **Tarifs vol** (Amadeus Self-Service ; Kiwi Tequila ; Skyscanner B2B plus tard)
- [ ] **Hébergement** (Booking Affiliate, Airbnb)
- [ ] Chaque outil renvoie systématiquement **le lien deep-link officiel**
      vers la page de réservation, pré-rempli avec les paramètres trouvés
- [ ] Affichage de l'**URL des CGV / règlement** du prestataire à côté du lien
      d'achat (engagement de transparence avant paiement)

#### 3b — Wallet de billets (post-réservation)

Une fois que l'utilisateur a acheté son billet sur le site officiel, il le
**transfère à GAB** (forward de mail, upload de PDF, photo de billet papier).
GAB extrait les infos et les conserve pour le compte de la personne et du
groupe.

- [ ] Module `core/wallet.py` + storage SQLite local (par instance self-hostée)
- [ ] Modèle `Ticket` : type (train/vol/hôtel/event), date, heure, référence,
      pièce jointe (PDF/image), propriétaire, événement / groupe associé
- [ ] **Ingestion** :
  - [ ] Forward d'email de confirmation → parsing texte (LLM en backup)
  - [ ] Upload de PDF → extraction `pypdf` puis enrichissement LLM
  - [ ] Photo de billet → OCR (vision multimodale du LLM)
- [ ] **Consultation** :
  - [ ] `/billets` → liste les billets du membre, triés par date
  - [ ] `/billets groupe` → vue agrégée du groupe (qui a quel billet pour
        quel trajet) — utile pour les voyages collectifs
- [ ] **Rappels automatiques** :
  - [ ] J-1 18h : "Demain RDV à 14h05 voie 5, voici ton billet"
  - [ ] H-2 le jour J : "Dans 2h, ton train. Gare de Lyon."
- [ ] **Coordination groupe** : "Vous êtes 6 sur le TGV 6815, voici la liste
      des sièges et des contacts"
- [ ] **Sécurité** : les billets contiennent du PII (nom, parfois pièce
      d'identité) → accès strict par `user_id`, suppression à la demande

#### 3c — Budget partagé

- [ ] **Tableau Tricount-like** : qui a payé quoi pour le groupe
- [ ] Calcul automatique de qui doit combien à qui (algo classique)
- [ ] Lien avec le wallet : un billet acheté pour 6 personnes → la dépense
      est automatiquement enregistrée dans le tricount du groupe

#### 3d — Capacité d'action vocale (GAB passe des appels)

> GAB compose un numéro et dialogue en temps réel avec un humain (ou un
> répondeur vocal IA) au nom du groupe : réserver une table, confirmer un
> hôtel, vérifier qu'un train est à l'heure, négocier un horaire avec un
> prestataire. Quand l'appel aboutit, le résultat est automatiquement
> consigné dans `/agenda` et le wallet (3b).

##### Cas d'usage

- [ ] **Réservation restau** : "GAB, réserve chez Mario vendredi 20h pour 6"
      → GAB appelle, dialogue, confirme, envoie le résumé au groupe.
- [ ] **Confirmation hôtel** : appel pour valider une demande spéciale
      (chambre adjacente, lit bébé, arrivée tardive).
- [ ] **Vérification logistique** : "Mon train est-il à l'heure ?" → appel
      au service client si l'API ne suffit pas.
- [ ] **Suivi post-réservation** : "Confirmer notre table de demain" la veille.
- [ ] **Fallback humain** : si le destinataire raccroche ou est confus, GAB
      arrête poliment et envoie le numéro au demandeur pour qu'il appelle.

##### Stack technique envisagée

- Plateformes voix-IA candidates : [Vapi](https://vapi.ai),
  [Bland](https://bland.ai), [Retell AI](https://retellai.com),
  [ElevenLabs Conversational AI](https://elevenlabs.io/conversational-ai).
- Architecture : LLM (Manifest) pour le cerveau de la conversation
  + STT/TTS temps réel + numéro virtuel rentable au mois.
- Fonctions exposées au LLM voix : `confirm_booking()`, `escalate_to_human()`,
  `record_outcome(success, details)` — pour clore l'appel proprement et
  écrire dans le wallet.
- Self-hosters : clé API du provider voix dans `.env`, facturation à la
  minute (typique 0.10–0.30 €/min tout compris).

##### Conformité légale (UE / France) — non négociable

- [ ] **Auto-identification IA** dès la première phrase, exigée par
      l'AI Act (art. 50) : *« Bonjour, je suis un assistant IA appelant pour
      le compte de M. Frédéric Terrasson… »*
- [ ] **Consentement à l'enregistrement** si l'appel est enregistré
      (loi française) — proposition par défaut : ne pas enregistrer, ne
      conserver que la transcription textuelle anonymisée.
- [ ] **Aucune action irréversible** sans validation humaine : GAB peut
      *demander* une réservation, mais si le restaurant exige un acompte
      CB, GAB raccroche et renvoie le lien à l'utilisateur.
- [ ] **Trace écrite systématique** envoyée dans le groupe : qui a été
      appelé, à quelle heure, quel résultat, quelle phrase d'engagement
      a été prise — pour que le groupe garde la main.

##### Risques et mitigations

| Risque | Mitigation |
|---|---|
| Restaurant raccroche en réalisant que c'est une IA | Voix très naturelle (ElevenLabs) + auto-identification claire mais brève + UX de fallback |
| Coût qui dérape (boucle d'appel) | Hard-cap durée par appel (3 min) + budget mensuel par instance |
| Erreur de réservation (mauvaise date, mauvais nombre) | Rappel de tous les paramètres en fin d'appel, log dans `/agenda` immédiatement |
| Hallucination du LLM en direct | Function calling strict, le LLM ne peut pas inventer un horaire — il doit appeler `confirm_booking()` |

#### Hors scope intentionnel (palier 6+ ou jamais)

- ❌ Réservation et paiement direct depuis GAB
- ❌ Agrégation de cartes bancaires / wallets (Apple Pay, etc.)
- ❌ Émission de billets par GAB (nécessite agrément + certificat IATA pour le vol)
- ❌ Faire passer GAB pour un humain au téléphone (interdit par l'AI Act)

### Palier 4 — Synchronisation multi-plateformes

- [ ] Un événement → suivi simultané Telegram + WhatsApp + Discord
- [ ] Identifier qu'un membre est la même personne sur plusieurs plateformes
- [ ] Pont de messages : ce qui est dit Telegram apparaît côté WhatsApp (option)

### Palier 5 — Distribution & SaaS

> **Le vrai défi de la distribution** : un bot Telegram doit tourner 24/7,
> donc il faut un dispositif always-on quelque part. Pour 95 % des
> utilisateurs, ce n'est ni leur Mac (qui se met en veille) ni leur box
> internet. Il faut donc proposer **plusieurs chemins** selon le profil de
> l'utilisateur : du purement open-source self-hosté (geek) au service géré
> clé-en-main (lambda user).

#### 5.1 — Documentation pour les hébergements bon marché (palier 5 standard)

- [ ] **README install pas-à-pas** pour self-hosters
- [ ] **Image Docker officielle** + `docker-compose.yml` prêt à l'emploi
- [ ] **Tests automatisés** (GitHub Actions : lint, type-check, tests unitaires)
- [ ] **CONTRIBUTING.md** + templates d'issues/PR
- [ ] **Script `install.sh`** qui installe GAB en 5 min sur un VPS Linux fresh
      (création du venv, install des deps, configuration systemd, création du
      `.env` interactif)

#### 5.2 — Guides d'hébergement par profil utilisateur

Pour chaque option, un fichier dédié dans `docs/hosting/` :

##### 🟢 VPS bon marché (~3-4 €/mois) — la voie standard
- [ ] Guide **Hetzner CX11** (3,79 €/mois — testé en prod par le créateur)
- [ ] Guide **Scaleway DEV1-S** (1,99 €/mois — le moins cher en EU)
- [ ] Guide **OVH VPS Starter** (3,50 €/mois — option française)
- [ ] Guide **Contabo VPS S** (4,50 €/mois pour 8 GB RAM — bon rapport qualité/prix)
- [ ] Lien d'affiliation par hébergeur (revenus passifs pour le projet)

##### 🟢 Cloud free tier — gratuit à vie
- [ ] Guide **Oracle Cloud Free Tier** : 4 vCPU + 24 GB RAM ARM gratuites pour
      toujours. Setup plus technique (CB requise pour vérification, pas de
      débit), mais c'est le saint Graal du self-hosted gratuit.

##### 🟡 Hébergement chez soi
- [ ] Guide **Raspberry Pi** : achat ~80 € one-shot, ~10 €/an d'électricité.
      Image SD-card ready-to-burn ou script Ansible.
- [ ] Guide **NAS Synology / QNAP** avec support Docker (Container Manager).
- [ ] Guide **Vieux PC / serveur maison** sous Ubuntu Server.

##### 🟡 Solutions geek
- [ ] Guide **Termux sur Android** (vieux téléphone reconverti en serveur).
- [ ] Guide **Tunnel Cloudflare / ngrok** pour exposer un GAB qui tourne sur
      une machine derrière un NAT (utile pour les webhooks WhatsApp).

##### 🔴 À éviter (documenter pourquoi)
- Render free tier, Fly.io free, Railway free → auto-sleep après inactivité,
  incompatible avec un bot Telegram en polling permanent.
- Heroku → plus de free tier depuis 2022.

#### 5.3 — GAB Cloud (version SaaS hébergée) — réponse à la cible lambda

> Pour les utilisateurs qui ne veulent rien installer ni payer un VPS, on
> propose un service géré clé-en-main : ils s'inscrivent, donnent leur token
> Telegram et c'est tout, leur instance GAB tourne sur notre infra mutualisée.

##### Modèle commercial proposé

- [ ] **Free tier** : 1 groupe Telegram, 100 messages LLM/mois → permet de
      tester sans engagement
- [ ] **Plan Personnel** : 2-3 €/mois, groupes illimités, 2000 messages/mois
- [ ] **Plan Famille** : 5 €/mois, plusieurs comptes liés, billets dans le
      wallet partagé
- [ ] **Plan Pro** (associations, entreprises) : 15 €/mois, intégrations
      avancées (calendrier d'équipe, budget partagé multi-événements)

##### Stack technique envisagée

- [ ] Multi-tenancy : un process GAB par tenant (isolation totale) OU un
      process partagé qui route par `chat_id` (mutualisation) — choix à faire
      selon le volume.
- [ ] Frontend d'inscription : Next.js + Auth (Clerk ou Supabase Auth).
- [ ] Backend de gestion : FastAPI + PostgreSQL + Stripe pour la facturation.
- [ ] Déploiement : Hetzner Cloud + Coolify (PaaS open source) ou Kubernetes
      léger (k3s) si volume.
- [ ] Tarification LLM : possibilité d'inclure une enveloppe Manifest dans
      l'abonnement (avec marge) OU permettre à l'utilisateur d'apporter sa
      propre clé (BYO key, modèle moins cher pour eux).

##### Conformité

- [ ] **RGPD** : DPO si on stocke des données EU, mentions légales, registre
      des traitements. Privacy by design : minimum de données, suppression
      sur demande.
- [ ] **Hébergement EU** : Hetzner / Scaleway / OVH plutôt que AWS/GCP pour
      la confiance des utilisateurs EU.
- [ ] **Conditions d'utilisation** : interdiction de spam / scraping / usage
      commercial non déclaré.

#### 5.4 — Communication & community building

- [ ] Page d'accueil **gab.terrasson.com** (ou autre domaine) avec démo,
      pricing, lien GitHub
- [ ] **Article de lancement** sur Hacker News, ProductHunt, Reddit
      r/selfhosted, r/telegram
- [ ] **Thread Twitter/X** détaillant la vision concierge-agent
- [ ] **Vidéo YouTube** : "Je code mon propre concierge IA" (vlog technique)
- [ ] **Réponse aux issues GitHub** dans les 48h pour les premiers contributeurs

---

## Idées en vrac (à classer plus tard)

- Vote pondéré (chacun a N voix à répartir)
- Détection de tension (ton agressif) → bot apaise / propose un break
- Profils membres : allergies, préférences alimentaires, dispos récurrentes
- Intégration calendrier perso (Google Calendar, ICS)
- Alertes prix vol/train (mode "économies")
- Mode "anniversaire surprise" : un membre admin pilote sans que les autres voient
- Compte-rendu automatique post-événement (« voici ce qui s'est passé »)
- Photos partagées : agréger les photos prises pendant la sortie
