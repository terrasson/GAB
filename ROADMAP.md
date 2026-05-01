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

### Palier 2 — Intelligence proactive

- [ ] Détection d'intention en conversation (« on pourrait aller au resto » → propose un sondage)
- [ ] Personnalité "chef de groupe" : intervient au bon moment, pas trop bavard
- [ ] Récap multi-jours / multi-membres
- [ ] Médiation douce en cas de désaccord détecté

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

#### Hors scope intentionnel (palier 6+ ou jamais)

- ❌ Réservation et paiement direct depuis GAB
- ❌ Agrégation de cartes bancaires / wallets (Apple Pay, etc.)
- ❌ Émission de billets par GAB (nécessite agrément + certificat IATA pour le vol)

### Palier 4 — Synchronisation multi-plateformes

- [ ] Un événement → suivi simultané Telegram + WhatsApp + Discord
- [ ] Identifier qu'un membre est la même personne sur plusieurs plateformes
- [ ] Pont de messages : ce qui est dit Telegram apparaît côté WhatsApp (option)

### Palier 5 — Distribution & SaaS

- [ ] README install pas-à-pas pour self-hosters
- [ ] Image Docker officielle + `docker-compose.yml` prêt à l'emploi
- [ ] Tests automatisés (GitHub Actions)
- [ ] CONTRIBUTING.md
- [ ] Optionnel : version SaaS hébergée (modèle freemium / abonnement)

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
