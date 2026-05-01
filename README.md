# 🎩 GAB — Grand Assistant de Bureau

> Majordome virtuel multi-plateforme, propulsé par le LLM **Hermes** (Ollama).

GAB est un agent IA qui organise des **groupes de discussion** et assiste vos utilisateurs sur **Telegram, WhatsApp et Discord** — depuis un seul service unifié.

> **Vision** : GAB est conçu comme un **concierge-agent** pour groupes humains
> (sortie, voyage, anniversaire). Voir [`ROADMAP.md`](ROADMAP.md) pour les paliers
> de développement, et [`prompts/system.md`](prompts/system.md) pour le rôle
> exact qu'il joue dans chaque conversation.

---

## ✨ Fonctionnalités

| Commande           | Description                                              |
|--------------------|----------------------------------------------------------|
| `/start`           | Message de bienvenue                                     |
| `/ask <question>`  | Poser une question au LLM Hermes                         |
| `/creategroup <nom>` | Créer un groupe / générer un lien d'invitation         |
| `/invite <user>`   | Inviter un membre dans le groupe courant                 |
| `/summary`         | Résumé IA de la conversation récente                     |
| `/clear`           | Effacer l'historique de la conversation                  |
| `/status`          | État du LLM et des plateformes actives                   |
| _(message libre)_  | Conversation directe avec Hermes                         |

---

## 🏗️ Architecture

```
GAB/
├── main.py                  # Point d'entrée — démarre toutes les plateformes
├── config.py                # Configuration centralisée (.env)
├── core/
│   ├── agent.py             # Cerveau de GAB (routage commandes + LLM)
│   ├── group_manager.py     # Gestion cross-plateforme des groupes
│   └── memory.py            # Historique des conversations par utilisateur
├── llm/
│   └── hermes.py            # Client Ollama async (chat + streaming)
├── platforms/
│   ├── base.py              # Interface abstraite commune
│   ├── telegram/bot.py      # Adaptateur Telegram (polling)
│   ├── whatsapp/bridge.py   # Adaptateur WhatsApp (Meta Cloud API + webhook)
│   └── discord/bot.py       # Adaptateur Discord (gateway)
├── api/
│   └── server.py            # Serveur FastAPI (webhooks + /health)
└── utils/
    └── helpers.py           # Décorateurs et utilitaires partagés
```

---

## 🚀 Démarrage rapide

### 1. Prérequis

- Python 3.12+
- [Ollama](https://ollama.com) installé et le modèle Hermes téléchargé :
  ```bash
  ollama pull nous-hermes2
  ```

### 2. Installation

```bash
git clone https://github.com/VOTRE_USER/GAB.git
cd GAB
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Éditez .env avec vos tokens
```

### 3. Lancement

```bash
python main.py
```

GAB détecte automatiquement quelles plateformes sont configurées dans `.env`.

---

## 🐳 Docker

```bash
cp .env.example .env  # remplissez .env
docker compose up -d
```

> Le service `ollama` démarre automatiquement.
> Pour charger Hermes dans le container : `docker exec gab-ollama ollama pull nous-hermes2`

---

## 📡 Configuration des plateformes

### Telegram
1. Créez un bot via [@BotFather](https://t.me/BotFather)
2. Copiez le token dans `TELEGRAM_BOT_TOKEN`

### WhatsApp (Meta Business Cloud API)
1. Créez une app sur [Meta for Developers](https://developers.facebook.com)
2. Activez **WhatsApp Business Cloud API**
3. Renseignez `WA_TOKEN`, `WA_PHONE_ID`, `WA_VERIFY_TOKEN`
4. Configurez le webhook Meta → `https://votre-domaine.com/webhook/whatsapp`

### Discord
1. Créez une application sur [Discord Developer Portal](https://discord.com/developers/applications)
2. Créez un Bot, activez les intents **Message Content** et **Server Members**
3. Copiez le token dans `DISCORD_TOKEN`
4. Mentionnez `@GAB` dans un serveur ou écrivez-lui en DM

---

## 🤖 LLM — providers supportés

GAB est **LLM-agnostique** : choisissez le backend qui vous convient via `LLM_PROVIDER` dans `.env`.

| Provider     | `LLM_PROVIDER` | Exemple `LLM_MODEL`         | Clé API ?            |
|--------------|----------------|-----------------------------|----------------------|
| Ollama local | `ollama`       | `qwen3:8b`, `llama3.1:8b`   | non (auto-hébergé)   |
| OpenAI       | `openai`       | `gpt-4o-mini`, `gpt-4o`     | oui                  |
| DeepSeek     | `deepseek`     | `deepseek-chat`             | oui                  |
| Mistral      | `mistral`      | `mistral-large-latest`      | oui                  |
| Groq         | `groq`         | `llama-3.1-70b-versatile`   | oui                  |
| Together     | `together`     | `meta-llama/Llama-3-70b-…`  | oui                  |
| Anthropic    | `anthropic`    | `claude-sonnet-4-6`         | oui                  |

### Exemples de configuration

**Ollama local (défaut)**
```env
LLM_PROVIDER=ollama
LLM_MODEL=qwen3:8b
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

## 📄 Licence

MIT
