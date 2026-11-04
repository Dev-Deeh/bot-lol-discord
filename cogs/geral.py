"""Comandos gerais: /ping, /ajuda e /config (admins)."""
import discord
from discord import app_commands
from discord.ext import commands

CHANNEL_KINDS = [
    app_commands.Choice(name="Alertas de elo (subiu/caiu)", value="alertas"),
    app_commands.Choice(name="Resumo pós-partida", value="partidas"),
]


class Geral(commands.Cog):
    config = app_commands.Group(name="config", description="Configurações do bot (admins)", guild_only=True,
                                default_permissions=discord.Permissions(manage_guild=True))

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Testa se o bot está online")
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"🏓 Pong! `{self.bot.latency * 1000:.0f}ms`")

    @app_commands.command(name="ajuda", description="Lista os comandos do bot")
    async def ajuda(self, interaction: discord.Interaction):
        embed = discord.Embed(title="📖 Comandos", color=0xC89B3C, description=(
            "**/vincular** `Nick#TAG` — liga sua conta da Riot (ganha cargo de elo)\n"
            "**/perfil** — card com elo, winrate e campeões mais jogados\n"
            "**/partida** — card da partida ao vivo, com o elo dos 10 jogadores\n"
            "**/ranking** — ranking de elo do servidor\n"
            "**/desvincular** — remove sua conta\n\n"
            "🔔 **Automático:** alerta quando alguém sobe/cai de elo e card de cada ranked jogada.\n"
            "⚙️ **Admins:** `/config canal` escolhe onde os avisos aparecem."))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @config.command(name="canal", description="Escolhe o canal de um tipo de aviso automático")
    @app_commands.choices(tipo=CHANNEL_KINDS)
    @app_commands.describe(canal="Deixe vazio para desativar")
    async def config_canal(self, interaction: discord.Interaction, tipo: app_commands.Choice[str],
                           canal: discord.TextChannel | None = None):
        await self.bot.db.set_config(interaction.guild_id, f"canal:{tipo.value}", canal.id if canal else None)
        text = f"em {canal.mention}" if canal else "**desativado**"
        await interaction.response.send_message(f"✅ {tipo.name}: {text}", ephemeral=True)

    @config.command(name="ver", description="Mostra a configuração atual")
    async def config_ver(self, interaction: discord.Interaction):
        lines = []
        for c in CHANNEL_KINDS:
            value = await self.bot.db.get_config(interaction.guild_id, f"canal:{c.value}")
            lines.append(f"**{c.name}:** " + (f"<#{value}>" if value else "—"))
        await interaction.response.send_message(
            embed=discord.Embed(title="⚙️ Configuração", description="\n".join(lines), color=0x95A5A6),
            ephemeral=True)


async def setup(bot):
    await bot.add_cog(Geral(bot))
