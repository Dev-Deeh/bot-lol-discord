"""Ponto de entrada do bot. Rode com:  python main.py"""
import logging
import os

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from core.cards import CardMaker
from core.db import Database
from core.ddragon import DDragon
from core.riot import RiotAPI, RiotError
from core.util import UserError

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")

EXTENSIONS = ["cogs.geral", "cogs.lol", "cogs.servidor", "cogs.noticias"]


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
        # max_messages=None: não guarda mensagens em memória (o bot não precisa) — economiza RAM
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, tree_cls=Tree,
                         max_messages=None)
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
        self.cards = CardMaker(self.session, self.ddragon)
        try:
            version = await self.ddragon.refresh()
            log.info("Data Dragon carregado (versão %s)", version)
        except Exception:
            log.exception("Não consegui carregar o Data Dragon agora; tento de novo mais tarde.")

        for ext in EXTENSIONS:
            await self.load_extension(ext)

        # Comandos globais: funcionam em todos os servidores onde o bot estiver
        synced = await self.tree.sync()
        log.info("%d comandos sincronizados em todos os servidores", len(synced))

        # Versões antigas registravam os comandos só no servidor do GUILD_ID.
        # Limpa essa cópia para não aparecer cada comando duplicado lá.
        guild_id = os.getenv("GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.clear_commands(guild=guild)
            try:
                await self.tree.sync(guild=guild)
            except discord.HTTPException:
                pass

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
