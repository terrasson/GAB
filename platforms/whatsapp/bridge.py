"""
Adaptateur WhatsApp pour GAB.
Utilise l'API WhatsApp Business Cloud (Meta) via webhook HTTP.
Le serveur FastAPI (api/server.py) reçoit les webhooks et appelle send_message() ici.

Docs : https://developers.facebook.com/docs/whatsapp/cloud-api
"""

import logging
import httpx

from platforms.base import BasePlatform
from core.agent import GabAgent, Message

logger = logging.getLogger("GAB.whatsapp")

GRAPH_URL = "https://graph.facebook.com/v19.0"


class WhatsAppPlatform(BasePlatform):
    """
    Plateforme WhatsApp Business Cloud API.
    - La réception des messages passe par le webhook FastAPI.
    - L'envoi est fait directement vers l'API Graph de Meta.
    """

    name = "whatsapp"

    def __init__(self, agent: GabAgent, token: str, phone_id: str):
        super().__init__(agent)
        self._token    = token
        self._phone_id = phone_id
        self._client   = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        # WhatsApp fonctionne en mode webhook ; le démarrage est géré par le serveur FastAPI.
        logger.info("📱 WhatsApp — en attente des webhooks sur /webhook/whatsapp")

    async def stop(self) -> None:
        await self._client.aclose()
        logger.info("WhatsApp — arrêté.")

    # ── Point d'entrée appelé par le webhook ─────────────────────────────────

    async def on_webhook(self, payload: dict) -> None:
        """Appelé par api/server.py à chaque message entrant."""
        try:
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    for wa_msg in value.get("messages", []):
                        await self._handle_wa_message(wa_msg, value)
        except Exception as exc:
            logger.error("Erreur traitement webhook WhatsApp : %s", exc)

    async def _handle_wa_message(self, wa_msg: dict, value: dict) -> None:
        if wa_msg.get("type") != "text":
            return  # on ne traite que le texte pour l'instant

        user_id  = wa_msg["from"]
        text     = wa_msg["text"]["body"]

        # Récupération du nom du contact si disponible
        contacts = value.get("contacts", [])
        username = contacts[0]["profile"]["name"] if contacts else user_id

        msg = Message(
            platform = self.name,
            user_id  = user_id,
            username = username,
            text     = text,
        )

        response = await self.agent.handle(msg)
        await self.send_message(user_id, response.text)

    # ── Envoi de message ──────────────────────────────────────────────────────

    async def send_message(self, to: str, text: str) -> None:
        """Envoie un message texte via l'API Graph de Meta."""
        # WhatsApp ne supporte pas le Markdown Telegram ; on nettoie
        clean = text.replace("*", "").replace("`", "").replace("_", "")
        payload = {
            "messaging_product": "whatsapp",
            "to":                to,
            "type":              "text",
            "text":              {"body": clean[:4096]},
        }
        try:
            resp = await self._client.post(
                f"{GRAPH_URL}/{self._phone_id}/messages",
                json=payload,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("Erreur envoi WhatsApp %s : %s", exc.response.status_code, exc.response.text)
        except httpx.RequestError as exc:
            logger.error("Erreur réseau WhatsApp : %s", exc)

    # ── Gestion de groupe (via API Graph) ─────────────────────────────────────

    async def create_group(self, name: str, members: list[str]) -> str | None:
        """
        Crée un groupe WhatsApp via l'API Business Cloud.
        Retourne l'ID du groupe créé ou None en cas d'erreur.
        Note : nécessite le scope whatsapp_business_management.
        """
        payload = {
            "name":    name,
            "members": members,
        }
        try:
            resp = await self._client.post(
                f"{GRAPH_URL}/{self._phone_id}/groups",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            group_id = data.get("id")
            logger.info("Groupe WhatsApp '%s' créé : %s", name, group_id)
            return group_id
        except Exception as exc:
            logger.error("Impossible de créer le groupe WhatsApp : %s", exc)
            return None
