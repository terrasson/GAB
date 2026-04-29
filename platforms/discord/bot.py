"""
Adaptateur Discord pour GAB.
Utilise discord.py (bibliothèque officielle).
"""

import logging
import discord
from discord.ext import commands

from platforms.base import BasePlatform
from core.agent import GabAgent, Message

logger = logging.getLogger("GAB.discord")


class GabDiscordClient(commands.Bot):
    def __init__(self, agent: GabAgent):
        intents         = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="/", intents=intents, help_command=None)
        self.gab_agent  = agent

    async def on_ready(self) -> None:
        logger.info("🎮 Discord — connecté en tant que %s (id: %s)", self.user, self.user.id)
        await self.tree.sync()

    async def on_message(self, discord_msg: discord.Message) -> None:
        if discord_msg.author.bot:
            return

        # Mentionne le bot OU message privé → on répond
        mentioned = self.user in discord_msg.mentions
        is_dm     = isinstance(discord_msg.channel, discord.DMChannel)

        if not (mentioned or is_dm):
            return

        # Nettoyage du texte (retire la mention)
        text = discord_msg.content.replace(f"<@{self.user.id}>", "").strip()
        if not text:
            return

        async with discord_msg.channel.typing():
            msg = Message(
                platform   = "discord",
                user_id    = str(discord_msg.author.id),
                username   = discord_msg.author.display_name,
                text       = text,
                group_id   = str(discord_msg.guild.id)      if discord_msg.guild else None,
                group_name = discord_msg.guild.name          if discord_msg.guild else None,
            )
            response = await self.gab_agent.handle(msg)
            # Discord supporte le Markdown natif (légèrement différent)
            reply = response.text.replace("`", "``")
            await discord_msg.reply(reply[:2000])

            # Création de catégorie/channel si demandée
            if response.action == "create_group" and discord_msg.guild:
                await self._create_discord_channel(
                    discord_msg.guild,
                    response.action_data.get("name", "gab-group"),
                    discord_msg,
                )

    async def _create_discord_channel(
        self,
        guild: discord.Guild,
        name: str,
        origin_msg: discord.Message,
    ) -> None:
        """Crée un channel texte dans le serveur Discord courant."""
        try:
            safe_name = name.lower().replace(" ", "-")[:100]
            channel = await guild.create_text_channel(
                name  = safe_name,
                topic = f"Groupe créé par GAB pour {origin_msg.author.display_name}",
            )
            invite = await channel.create_invite(max_age=86400)
            await origin_msg.reply(
                f"✅ Channel **#{channel.name}** créé !\n🔗 Invitation : {invite.url}"
            )
        except discord.Forbidden:
            await origin_msg.reply("⚠️ Je n'ai pas les droits pour créer un channel ici.")
        except Exception as exc:
            logger.error("Erreur création channel Discord : %s", exc)


class DiscordPlatform(BasePlatform):
    """Plateforme Discord."""

    name = "discord"

    def __init__(self, agent: GabAgent, token: str):
        super().__init__(agent)
        self._token  = token
        self._client = GabDiscordClient(agent)

    async def start(self) -> None:
        logger.info("🎮 Discord — connexion…")
        await self._client.start(self._token)

    async def stop(self) -> None:
        await self._client.close()
        logger.info("Discord — arrêté.")
