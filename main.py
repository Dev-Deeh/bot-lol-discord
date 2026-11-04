"""Ponto de entrada do bot. Rode com:  python main.py"""
import logging
import os

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from core.db import Database
from core.ddragon import DDragon
from core.riot import RiotAPI, RiotError
from core.util import UserError

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")

EXTENSIONS = ["cogs.geral", "cogs.lol", "cogs.equipe", "cogs.draft", "cogs.diversao", "cogs.utilidades"]


class Tree(app_commands.CommandTree):
    async def on_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        original = getattr(error, "original", error)
        if isinstance(original, UserError):
            msg = f"⚠️ {original}"
        elif isinstance(original, RiotError):
            msg = f"⚠️ Riot API: {original.message}"
        elif isinstance(error, app_commands.MissingPermissions):
            msg = "🚫 Você não tem permissão para usar esse comando."
        elif isinstance(error, app_commands.CommandOnCooldown):
            msg = f"⏳ Calma! Tenta de novo em {error.retry_after:.0f}s."
        else:
            log.exception("Erro no comando %s", interaction.command and interaction.command.name,
                          exc_info=original)
            msg = "❌ Deu algum erro aqui. Tenta de novo."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            pass


class LolBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()  # nenhum intent privilegiado é necessário
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, tree_cls=Tree)
        self.db = Database(os.getenv("DATABASE_PATH", "bot.db"))
        self.session: aiohttp.ClientSession | None = None
        self.riot: RiotAPI | None = None
        self.ddragon: DDragon | None = None

    async def setup_hook(self):
        await self.db.connect()
        self.session = aiohttp.ClientSession()
        self.riot = RiotAPI(self.session, os.getenv("RIOT_API_KEY", ""),
                            os.getenv("RIOT_PLATFORM", "br1"), os.getenv("RIOT_REGION", "americas"))
        self.ddragon = DDragon(self.session)
        try:
            version = await self.ddragon.refresh()
            log.info("Data Dragon carregado (versão %s)", version)
        except Exception:
            log.exception("Não consegui carregar o Data Dragon agora; tento de novo mais tarde.")

        for ext in EXTENSIONS:
            await self.load_extension(ext)

        guild_id = os.getenv("GUILD_ID")
        if guild_id:  # sincroniza na hora no seu servidor (o global pode levar até 1h)
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            try:
                synced = await self.tree.sync(guild=guild)
            except discord.Forbidden:
                raise SystemExit(
                    "\n❌ O bot não está no servidor do GUILD_ID (ou o ID está errado).\n"
                    "   Convide o bot pelo link do OAuth2 (veja o README) e confira o GUILD_ID no .env.\n")
        else:
            synced = await self.tree.sync()
        log.info("%d comandos sincronizados", len(synced))

    async def on_ready(self):
        log.info("Logado como %s (id %s)", self.user, self.user.id)
        await self.change_presence(activity=discord.Game("League of Legends | /ajuda"))

    async def close(self):
        await super().close()
        if self.session:
            await self.session.close()
        await self.db.close()


def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Coloque o DISCORD_TOKEN no arquivo .env (veja o README).")
    LolBot().run(token, log_handler=None)


if __name__ == "__main__":
    main()
