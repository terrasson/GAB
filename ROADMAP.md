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

- [ ] **Recherche restaurant/activité** (Google Places API, Yelp)
- [ ] **Tarifs train** (API SNCF Connect, Trainline)
- [ ] **Tarifs vol** (Skyscanner, Kayak, Amadeus)
- [ ] **Hébergement** (Booking, Airbnb)
- [ ] **Budget partagé** (façon Tricount)
- [ ] **Météo** pour les sorties extérieures

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
