<p align="center">
  <img src="assets/logo.png" alt="GAB — Concierge IA" width="240"/>
</p>

# 🎩 GAB — Grand Assistant de Bureau

> **Concierge-agent IA pour groupes humains** — multi-plateforme (Telegram, WhatsApp, Discord), LLM-agnostique (Ollama, OpenAI, DeepSeek, Mistral, Claude, Manifest…).

GAB rejoint vos **groupes de discussion** et vous aide à organiser sorties, voyages, anniversaires, événements collectifs. Il anime, planifie, rappelle, propose. Voir [`ROADMAP.md`](ROADMAP.md) pour la vision complète et [`prompts/system.md`](prompts/system.md) pour son rôle exact.

---

## 🚀 Essayer GAB tout de suite (instance de démo)

> ⚠️ Cette instance est gérée par le mainteneur du projet à titre de démo et de validation.
> Pour un usage régulier, **[self-hostez votre propre GAB](#-self-hoster-son-propre-gab-recommandé)** — c'est gratuit, privé, et vous contrôlez tout.

[**➡️ Ajouter GAB à un groupe Telegram (pré-configuré admin)**](https://t.me/Gab_Concierge_Bot?startgroup=true&admin=delete_messages+pin_messages+invite_users+manage_chat)

[**💬 Ou lui écrire en privé**](https://t.me/Gab_Concierge_Bot)

---

## 🏠 Self-hoster son propre GAB (recommandé)

Chaque utilisateur lance sa propre instance : aucune dépendance à un service tiers, vie privée totale, vos données restent chez vous.

### 1. Prérequis

- **Python 3.12+**
- **Un LLM** (au choix) :
  - 🆓 **Ollama local** — gratuit, auto-hébergé : installez [Ollama](https://ollama.com) puis `ollama pull qwen3:8b`
  - ☁️ **API cloud** — clé personnelle Manifest, OpenAI, DeepSeek, Mistral, Claude, Groq, Together…
- **Un compte Telegram** (et/ou WhatsApp Business, et/ou Discord)

### 2. Installation

```bash
git clone https://github.com/terrasson/GAB.git
cd GAB
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Éditez .env avec vos tokens (voir sections plateformes & LLM ci-dessous)
```

### 3. Créer votre bot Telegram

1. Sur Telegram, ouvrez [@BotFather](https://t.me/BotFather) et tapez `/newbot`
2. Choisissez un nom et un username (ex. `MonGAB_Bot`) — vous recevez **votre token**
3. Collez le token dans `.env` → `TELEGRAM_BOT_TOKEN=...`
4. **Toujours chez @BotFather**, configurez les permissions essentielles :
   - `/setjoingroups` → votre bot → **Enable** (autorise l'ajout en groupe)
   - `/setprivacy` → votre bot → **Disable** (lui permet de voir tous les messages, indispensable pour la coordination)
5. (Optionnel) `/setuserpic` pour uploader [`assets/logo.png`](assets/logo.png) comme avatar du bot

### 4. Lancement

```bash
python main.py
```

GAB détecte automatiquement les plateformes configurées dans `.env`.

### 5. Votre lien magique d'invitation en groupe

Une fois votre bot opérationnel, partagez **votre** lien magique pour que vos amis l'ajoutent en groupe en un seul clic, **déjà admin** :

```
https://t.me/MonGAB_Bot?startgroup=true&admin=delete_messages+pin_messages+invite_users+manage_chat
```

Remplacez `MonGAB_Bot` par le username **de votre propre bot** (créé à l'étape 3).

---

## ✨ Commandes disponibles

| Commande            | Description                                              |
|---------------------|----------------------------------------------------------|
| `/start`            | Message de bienvenue                                     |
| `/ask <question>`   | Poser une question explicite au LLM                      |
| `/creategroup <nom>`| Créer un groupe / générer un lien d'invitation           |
| `/invite <user>`    | Inviter un membre dans le groupe courant                 |
| `/members`          | Lister les IDs des membres connus du groupe              |
| `/summary`          | Résumé IA de la conversation récente                     |
| `/clear`            | Effacer l'historique de la conversation                  |
| `/status`           | État du LLM et des plateformes actives                   |
| _(message libre)_   | Conversation directe avec GAB                            |

---

## 🏗️ Architecture

```
GAB/
├── main.py                       # Point d'entrée — démarre toutes les plateformes
├── config.py                     # Configuration centralisée (.env)
├── prompts/
│   └── system.md                 # Prompt système éditable (rôle, ton, limites)
├── core/
│   ├── agent.py                  # Cerveau de GAB (routage commandes + LLM)
│   ├── group_manager.py          # Gestion cross-plateforme des groupes
│   └── memory.py                 # Historique des conversations
├── llm/
│   ├── base.py                   # Interface abstraite LLMClient
│   ├── ollama_client.py          # Client Ollama (local)
│   ├── openai_compat_client.py   # Client OpenAI / DeepSeek / Mistral / Manifest / …
│   ├── anthropic_client.py       # Client Claude (Anthropic)
│   └── __init__.py               # Factory : sélectionne le client selon LLM_PROVIDER
├── platforms/
│   ├── base.py                   # Interface abstraite commune
│   ├── telegram/bot.py           # Adaptateur Telegram (polling)
│   ├── whatsapp/bridge.py        # Adaptateur WhatsApp (Meta Cloud API + webhook)
│   └── discord/bot.py            # Adaptateur Discord (gateway)
├── api/
│   └── server.py                 # Serveur FastAPI (webhooks + /health)
├── assets/
│   └── logo.png                  # Logo officiel
└── utils/
    └── helpers.py                # Décorateurs et utilitaires partagés
```

---

## 🐳 Docker

```bash
cp .env.example .env  # remplissez .env
docker compose up -d
```

> Le service `ollama` démarre automatiquement.
> Pour charger un modèle dans le container : `docker exec gab-ollama ollama pull qwen3:8b`

---

## 📡 Configuration des plateformes

### Telegram
Voir la [section Self-hoster](#3-créer-votre-bot-telegram) ci-dessus.

### WhatsApp (Meta Business Cloud API)
1. Créez une app sur [Meta for Developers](https://developers.facebook.com)
2. Activez **WhatsApp Business Cloud API**
3. Renseignez `WA_TOKEN`, `WA_PHONE_ID`, `WA_VERIFY_TOKEN` dans `.env`
4. Configurez le webhook Meta → `https://votre-domaine.com/webhook/whatsapp`

### Discord
1. Créez une application sur [Discord Developer Portal](https://discord.com/developers/applications)
2. Créez un Bot, activez les intents **Message Content** et **Server Members**
3. Copiez le token dans `.env` → `DISCORD_TOKEN=...`
4. Mentionnez `@GAB` dans un serveur ou écrivez-lui en DM

---

## 🤖 LLM — providers supportés

GAB est **LLM-agnostique** : choisissez le backend qui vous convient via `LLM_PROVIDER` dans `.env`.

| Provider              | `LLM_PROVIDER` | Exemple `LLM_MODEL`           | Clé API ?            |
|-----------------------|----------------|-------------------------------|----------------------|
| Ollama local          | `ollama`       | `qwen3:8b`, `llama3.1:8b`     | non (auto-hébergé)   |
| OpenAI                | `openai`       | `gpt-4o-mini`, `gpt-4o`       | oui                  |
| DeepSeek              | `deepseek`     | `deepseek-chat`               | oui                  |
| Mistral               | `mistral`      | `mistral-large-latest`        | oui                  |
| Groq                  | `groq`         | `llama-3.1-70b-versatile`     | oui                  |
| Together              | `together`     | `meta-llama/Llama-3-70b-…`    | oui                  |
| Anthropic             | `anthropic`    | `claude-sonnet-4-6`           | oui                  |
| **Manifest** _(routeur multi-modèles)_ | `openai` | `manifest/auto`     | oui (`mnfst_…`)      |

### Exemples de configuration

**Ollama local (gratuit, défaut)**
```env
LLM_PROVIDER=ollama
LLM_MODEL=qwen3:8b
```

**Manifest (routeur intelligent multi-modèles)**
```env
LLM_PROVIDER=openai
LLM_MODEL=manifest/auto
LLM_BASE_URL=https://app.manifest.build
LLM_API_KEY=mnfst_xxxxxxxxxxxxxxxx
```

**DeepSeek**
```env
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
LLM_API_KEY=sk-xxxxxxxxxxxxxxxx
```

**Claude (Anthropic)**
```env
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-6
LLM_API_KEY=sk-ant-xxxxxxxxxxxxxxxx
```

**Endpoint custom** (vLLM, LM Studio, ollama-openai…) — utilisez `openai` comme provider et précisez `LLM_BASE_URL`.

---

## 🛣️ Roadmap

Voir [`ROADMAP.md`](ROADMAP.md) pour la vision complète :

- 🟩 **Palier 0** — MVP technique (Telegram, multi-LLM, collecte d'IDs membres)
- 🟨 **Palier 1** — Outils de coordination (`/sondage`, `/rappel`, `/agenda`, mode passif)
- 🟥 **Palier 2** — Intelligence proactive (détection d'intentions, médiation douce)
- 🟦 **Palier 3** — Concierge complet : recherche train / vol / restau, **wallet de billets**, **capacité d'appel vocal**
- 🟪 **Paliers 4-5** — Sync multi-plateformes, distribution open source / SaaS

---

## 📄 Licence

MIT — utilisez, modifiez, redistribuez librement.

---

## 🤝 Contribuer

Les contributions sont les bienvenues. Ouvrez une **issue** pour discuter d'une idée, ou une **pull request** pour proposer un changement.
