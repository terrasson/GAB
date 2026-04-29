"""
Serveur FastAPI de GAB.
Gère les webhooks WhatsApp (Meta) et expose une API REST interne.
"""

import logging
from fastapi import FastAPI, Request, Response, HTTPException, Query

logger = logging.getLogger("GAB.api")


def build_app(whatsapp_platform=None, verify_token: str = "") -> FastAPI:
    """
    Construit l'application FastAPI.
    whatsapp_platform : instance de WhatsAppPlatform (optionnel).
    """
    app = FastAPI(title="GAB — Grand Assistant de Bureau", version="1.0.0")

    # ── Webhook WhatsApp ──────────────────────────────────────────────────────

    @app.get("/webhook/whatsapp")
    async def wa_verify(
        hub_mode: str             = Query(default="", alias="hub.mode"),
        hub_challenge: str        = Query(default="", alias="hub.challenge"),
        hub_verify_token: str     = Query(default="", alias="hub.verify_token"),
    ):
        """Vérification du webhook par Meta (challenge)."""
        if hub_mode == "subscribe" and hub_verify_token == verify_token:
            logger.info("Webhook WhatsApp vérifié ✅")
            return Response(content=hub_challenge, media_type="text/plain")
        raise HTTPException(status_code=403, detail="Token de vérification invalide")

    @app.post("/webhook/whatsapp")
    async def wa_webhook(request: Request):
        """Réception des messages WhatsApp entrants."""
        if not whatsapp_platform:
            raise HTTPException(status_code=503, detail="WhatsApp non configuré")
        payload = await request.json()
        await whatsapp_platform.on_webhook(payload)
        return {"status": "ok"}

    # ── Health check ──────────────────────────────────────────────────────────

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "GAB"}

    # ── Infos plateformes ─────────────────────────────────────────────────────

    @app.get("/platforms")
    async def platforms_info():
        return {
            "whatsapp": whatsapp_platform is not None,
        }

    return app
