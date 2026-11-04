"""Riot API: perfil, partida ao vivo, vincular conta, ranking, alertas de elo e resumo pós-partida — tudo em cards."""
import asyncio
import logging
import random

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import util
from core.riot import RiotError
from core.util import UserError

log = logging.getLogger("bot.lol")

QUEUES = {420: "Ranqueada Solo/Duo", 440: "Ranqueada Flex", 400: "Normal Escolha", 430: "Normal às Cegas",
          490: "Partida Rápida", 450: "ARAM", 1700: "Arena", 1900: "URF", 0: "Personalizada"}


def png(buf, name: str) -> discord.File:
    return discord.File(buf, filename=f"{name}.png")


class VerifyView(util.BaseView):
    def __init__(self, cog, user_id: int, puuid: str, riot_id: str, icon_id: int):
        super().__init__(timeout=900)
        self.cog, self.user_id, self.puuid, self.riot_id, self.icon_id = cog, user_id, puuid, riot_id, icon_id

    @discord.ui.button(label="Já troquei o ícone", emoji="✅", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Esse botão não é pra você.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        summ = await self.cog.bot.riot.summoner_by_puuid(self.puuid)
        if not summ or summ.get("profileIconId") != self.icon_id:
            return await interaction.followup.send(
                "❌ O ícone ainda não mudou. Às vezes leva alguns segundos depois de trocar no cliente — "
                "tenta de novo.", ephemeral=True)
        await self.cog.save_account(interaction.guild, interaction.user, self.puuid, self.riot_id)
        self.stop()
        await interaction.followup.send(
            f"✅ Conta **{self.riot_id}** vinculada! Já pode voltar seu ícone pro normal.", ephemeral=True)


class Lol(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.tracker.start()

    async def cog_unload(self):
        self.tracker.cancel()

    # ------------------------------------------------------------ helpers
    async def resolve(self, interaction: discord.Interaction, riot_id: str | None, membro=None):
        """Retorna (puuid, nome, tag) a partir do Riot ID digitado ou da conta vinculada."""
        if riot_id:
            parsed = util.parse_riot_id(riot_id)
            if not parsed:
                raise UserError("Use o formato `Nick#TAG` (ex.: `Faker#KR1`).")
            acc = await self.bot.riot.account_by_riot_id(*parsed)
            if not acc:
                raise UserError(f"Não encontrei a conta **{riot_id}**.")
            return acc["puuid"], acc["gameName"], acc["tagLine"]
        target = membro or interaction.user
        row = await self.bot.db.fetchone(
            "SELECT puuid, riot_id FROM accounts WHERE guild_id=? AND user_id=?", (interaction.guild_id, target.id))
        if not row:
            who = "Você não tem" if target == interaction.user else f"{target.display_name} não tem"
            raise UserError(f"{who} conta vinculada. Use `/vincular Nick#TAG` ou passe o Riot ID no comando.")
        name, _, tag = row["riot_id"].rpartition("#")
        return row["puuid"], name, tag

    async def save_account(self, guild: discord.Guild, member: discord.Member, puuid: str, riot_id: str):
        solo = await self.bot.riot.solo_entry(puuid)
        ids = await self.bot.riot.match_ids(puuid, count=1, type="ranked")
        solo = solo or {}
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO accounts (guild_id, user_id, puuid, riot_id, tier, rank, lp, wins, losses,"
            " last_match) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (guild.id, member.id, puuid, riot_id, solo.get("tier"), solo.get("rank"), solo.get("leaguePoints"),
             solo.get("wins"), solo.get("losses"), ids[0] if ids else ""))
        await util.update_elo_role(guild, member, solo.get("tier"))

    # ------------------------------------------------------------ /vincular
    @app_commands.command(name="vincular", description="Vincula sua conta da Riot ao Discord (com verificação)")
    @app_commands.describe(riot_id="Seu Riot ID, ex.: Nick#BR1")
    @app_commands.guild_only()
    async def vincular(self, interaction: discord.Interaction, riot_id: str):
        parsed = util.parse_riot_id(riot_id)
        if not parsed:
            raise UserError("Use o formato `Nick#TAG` (ex.: `Nick#BR1`).")
        await interaction.response.defer(ephemeral=True, thinking=True)
        acc = await self.bot.riot.account_by_riot_id(*parsed)
        if not acc:
            raise UserError(f"Não encontrei a conta **{riot_id}**.")
        taken = await self.bot.db.fetchone(
            "SELECT user_id FROM accounts WHERE guild_id=? AND puuid=? AND user_id<>?",
            (interaction.guild_id, acc["puuid"], interaction.user.id))
        if taken:
            raise UserError("Essa conta já está vinculada a outra pessoa do servidor.")
        summ = await self.bot.riot.summoner_by_puuid(acc["puuid"])
        if not summ:
            raise UserError("Essa conta não tem perfil de LoL na região do bot.")

        await self.bot.ddragon.ensure()
        icon = random.choice([i for i in range(29) if i != summ.get("profileIconId")])
        nice_id = f"{acc['gameName']}#{acc['tagLine']}"
        embed = discord.Embed(
            title="🔐 Verificação de conta",
            description=(f"Pra provar que **{nice_id}** é sua, troque o **ícone de perfil** no cliente do LoL "
                         f"para o ícone abaixo (é um dos ícones grátis, todo mundo tem).\n\n"
                         f"Depois clique em **Já troquei o ícone**. Você tem 15 minutos."),
            color=0xC89B3C)
        embed.set_image(url=self.bot.ddragon.profile_icon(icon))
        await interaction.followup.send(
            embed=embed, view=VerifyView(self, interaction.user.id, acc["puuid"], nice_id, icon), ephemeral=True)

    @app_commands.command(name="desvincular", description="Remove o vínculo da sua conta da Riot")
    @app_commands.guild_only()
    async def desvincular(self, interaction: discord.Interaction):
        await self.bot.db.execute("DELETE FROM accounts WHERE guild_id=? AND user_id=?",
                                  (interaction.guild_id, interaction.user.id))
        await util.update_elo_role(interaction.guild, interaction.user, None)
        await interaction.response.send_message("✅ Conta desvinculada.", ephemeral=True)

    # ------------------------------------------------------------ /perfil
    @app_commands.command(name="perfil", description="Card com elo, winrate e campeões mais jogados")
    @app_commands.describe(riot_id="Nick#TAG (vazio = sua conta vinculada)", membro="Membro com conta vinculada")
    async def perfil(self, interaction: discord.Interaction, riot_id: str | None = None,
                     membro: discord.Member | None = None):
        await interaction.response.defer(thinking=True)
        puuid, name, tag = await self.resolve(interaction, riot_id, membro)
        await self.bot.ddragon.ensure()
        summ, entries, masteries = await asyncio.gather(
            self.bot.riot.summoner_by_puuid(puuid), self.bot.riot.league_entries(puuid),
            self.bot.riot.top_masteries(puuid, 3))
        if not summ:
            raise UserError("Essa conta não tem perfil de LoL na região do bot.")
        card = await self.bot.cards.profile(name, tag, summ["summonerLevel"], summ["profileIconId"],
                                            entries, masteries)
        await interaction.followup.send(file=png(card, "perfil"))

    # ------------------------------------------------------------ /partida
    @app_commands.command(name="partida", description="Card da partida ao vivo de um jogador (scout!)")
    @app_commands.describe(riot_id="Nick#TAG (vazio = sua conta vinculada)", membro="Membro com conta vinculada")
    async def partida(self, interaction: discord.Interaction, riot_id: str | None = None,
                      membro: discord.Member | None = None):
        await interaction.response.defer(thinking=True)
        puuid, name, tag = await self.resolve(interaction, riot_id, membro)
        game = await self.bot.riot.active_game(puuid)
        if not game:
            return await interaction.followup.send(f"😴 **{name}#{tag}** não está em partida agora.")
        await self.bot.ddragon.ensure()

        async def solo_or_none(p):
            if not p.get("puuid"):
                return None
            try:
                return await self.bot.riot.solo_entry(p["puuid"])
            except RiotError:
                return None

        leagues = await asyncio.gather(*(solo_or_none(p) for p in game["participants"]))
        queue = QUEUES.get(game.get("gameQueueConfigId"), "Partida")
        card = await self.bot.cards.live(game, list(leagues), puuid, queue)
        await interaction.followup.send(file=png(card, "partida"))

    # ------------------------------------------------------------ /ranking
    @app_commands.command(name="ranking", description="Ranking de elo (Solo/Duo) do servidor")
    @app_commands.guild_only()
    async def ranking(self, interaction: discord.Interaction):
        rows = await self.bot.db.fetchall("SELECT * FROM accounts WHERE guild_id=?", (interaction.guild_id,))
        if not rows:
            raise UserError("Ninguém vinculou conta ainda. Use `/vincular Nick#TAG`.")
        await interaction.response.defer(thinking=True)
        rows = sorted(rows, key=lambda r: util.elo_score(r["tier"], r["rank"], r["lp"]) or -1, reverse=True)[:15]
        data = [{"name": r["riot_id"].rpartition("#")[0], "tier": r["tier"], "rank": r["rank"], "lp": r["lp"],
                 "wins": r["wins"], "losses": r["losses"]} for r in rows]
        card = await self.bot.cards.ranking(data)
        await interaction.followup.send(file=png(card, "ranking"))

    # ------------------------------------------------------------ rastreador automático
    @tasks.loop(minutes=10)
    async def tracker(self):
        await self.bot.ddragon.ensure()
        rows = await self.bot.db.fetchall("SELECT * FROM accounts")
        for row in rows:
            try:
                await self.track_one(row)
            except RiotError as e:
                log.warning("Rastreador: %s", e)
                if e.status in (0, 401, 403):
                    return  # chave ausente/expirada: não adianta continuar
            except Exception:
                log.exception("Erro rastreando %s", row["riot_id"])

    @tracker.before_loop
    async def before_tracker(self):
        await self.bot.wait_until_ready()

    async def track_one(self, row):
        guild = self.bot.get_guild(row["guild_id"])
        if not guild:
            return
        riot = self.bot.riot
        solo = await riot.solo_entry(row["puuid"]) or {}
        tier, rank, lp = solo.get("tier"), solo.get("rank"), solo.get("leaguePoints")
        name = row["riot_id"].rpartition("#")[0]

        if (tier, rank) != (row["tier"], row["rank"]) and tier:
            old = util.elo_score(row["tier"], row["rank"], row["lp"])
            new = util.elo_score(tier, rank, lp)
            kind = "placed" if old is None else "up" if new > old else "down"
            channel = await util.get_channel(self.bot, guild, "alertas")
            if channel:
                msg = {"placed": "🎯 terminou as MDs!", "up": "🎉 subiu de elo! Bora!",
                       "down": "💀 caiu de elo... F no chat."}[kind]
                card = await self.bot.cards.rank_change(name, tier, rank, lp, kind)
                await channel.send(f"<@{row['user_id']}> {msg}", file=png(card, "elo"))
            try:
                member = guild.get_member(row["user_id"]) or await guild.fetch_member(row["user_id"])
                await util.update_elo_role(guild, member, tier)
            except discord.HTTPException:
                pass

        await self.bot.db.execute(
            "UPDATE accounts SET tier=?, rank=?, lp=?, wins=?, losses=? WHERE guild_id=? AND user_id=?",
            (tier, rank, lp, solo.get("wins"), solo.get("losses"), row["guild_id"], row["user_id"]))

        ids = await riot.match_ids(row["puuid"], count=1, type="ranked")
        if ids and ids[0] != row["last_match"]:
            await self.bot.db.execute("UPDATE accounts SET last_match=? WHERE guild_id=? AND user_id=?",
                                      (ids[0], row["guild_id"], row["user_id"]))
            channel = await util.get_channel(self.bot, guild, "partidas")
            if channel:
                match = await riot.match(ids[0])
                if match:
                    info = match["info"]
                    p = next(x for x in info["participants"] if x["puuid"] == row["puuid"])
                    card = await self.bot.cards.match(p, info, name, QUEUES.get(info["queueId"], "Ranqueada"))
                    await channel.send(f"<@{row['user_id']}>", file=png(card, "partida"),
                                       allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):
    await bot.add_cog(Lol(bot))
