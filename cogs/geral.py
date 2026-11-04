"""Comandos gerais. O /ping é o que garante a insígnia de Desenvolvedor Ativo."""
import discord
from discord import app_commands
from discord.ext import commands

AJUDA = {
    "🎮 Riot": "`/perfil` `/partida` `/vincular` `/desvincular` `/ranking`",
    "🏆 Time": "`/scrim marcar|resultado|historico|proximas|cancelar` · `/lineup definir|reserva|remover|ver` · "
              "`/vod adicionar|listar`",
    "🧠 Draft": "`/draft iniciar|escolher|cancelar` · `/pool adicionar|remover|ver|time|sugerir` · "
               "`/counter` `/build` `/patch`",
    "🎲 Diversão": "`/times` `/roleta` `/quiz` `/nivel` `/top` `/diario` · `/aposta criar|fechar|encerrar|cancelar`",
    "🔧 Utilidades": "`/lfg` · `/config canal|voz|cargo-nivel|ver` (admins)",
}


class Geral(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Testa se o bot está online")
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"🏓 Pong! `{self.bot.latency * 1000:.0f}ms`")

    @app_commands.command(name="ajuda", description="Lista todos os comandos do bot")
    async def ajuda(self, interaction: discord.Interaction):
        embed = discord.Embed(title="📖 Comandos", color=0xC89B3C)
        for name, value in AJUDA.items():
            embed.add_field(name=name, value=value, inline=False)
        embed.set_footer(text="Dica: admins usam /config para escolher os canais de alertas, patch, VODs etc.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Geral(bot))
