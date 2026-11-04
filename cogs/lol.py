"""Integração com a Riot API: perfil, partida ao vivo, vincular conta, ranking, alertas e resumo pós-partida."""
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

QUEUES = {420: "Ranqueada Solo/Duo", 440: "Ranqueada Flex", 400: "Normal (Escolha)", 430: "Normal (Às Cegas)",
          490: "Partida Rápida", 450: "ARAM", 1700: "Arena", 1900: "URF", 0: "Personalizada"}


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
        """Retorna (puuid, 'Nome#TAG') a partir do Riot ID digitado ou da conta vinculada."""
        if riot_id:
            parsed = util.parse_riot_id(riot_id)
            if not parsed:
                raise UserError("Use o formato `Nick#TAG` (ex.: `Faker#KR1`).")
            acc = await self.bot.riot.account_by_riot_id(*parsed)
            if not acc:
                raise UserError(f"Não encontrei a conta **{riot_id}**.")
            return acc["puuid"], f"{acc['gameName']}#{acc['tagLine']}"
        target = membro or interaction.user
        row = await self.bot.db.fetchone(
            "SELECT puuid, riot_id FROM accounts WHERE guild_id=? AND user_id=?", (interaction.guild_id, target.id))
        if not row:
            who = "Você não tem" if target == interaction.user else f"{target.display_name} não tem"
            raise UserError(f"{who} conta vinculada. Use `/vincular Nick#TAG` ou passe o Riot ID no comando.")
        return row["puuid"], row["riot_id"]

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
            raise UserError("Essa conta não tem perfil de LoL neste servidor (região) do bot.")

        await self.bot.ddragon.ensure()
        icon = random.choice([i for i in range(29) if i != summ.get("profileIconId")])
        nice_id = f"{acc['gameName']}#{acc['tagLine']}"
        embed = discord.Embed(
            title="🔐 Verificação de conta",
            description=(f"Pra provar que **{nice_id}** é sua, troque o **ícone de perfil** no cliente do LoL "
                         f"para o ícone abaixo (é um dos ícones grátis, todo mundo tem).\n\n"
                         f"Depois clique em **Já troquei o ícone**. Você tem 15 minutos."),
            color=0x0AC8B9)
        embed.set_image(url=self.bot.ddragon.profile_icon(icon))
        await interaction.followup.send(
            embed=embed, view=VerifyView(self, interaction.user.id, acc["puuid"], nice_id, icon), ephemeral=True)

    @app_commands.command(name="desvincular", description="Remove o vínculo da sua conta da Riot")
    async def desvincular(self, interaction: discord.Interaction):
        await self.bot.db.execute("DELETE FROM accounts WHERE guild_id=? AND user_id=?",
                                  (interaction.guild_id, interaction.user.id))
        await util.update_elo_role(interaction.guild, interaction.user, None)
        await interaction.response.send_message("✅ Conta desvinculada.", ephemeral=True)

    # ------------------------------------------------------------ /perfil
    @app_commands.command(name="perfil", description="Elo, winrate e maestrias de um jogador")
    @app_commands.describe(riot_id="Nick#TAG (vazio = sua conta vinculada)", membro="Membro com conta vinculada")
    async def perfil(self, interaction: discord.Interaction, riot_id: str | None = None,
                     membro: discord.Member | None = None):
        await interaction.response.defer(thinking=True)
        puuid, name = await self.resolve(interaction, riot_id, membro)
        await self.bot.ddragon.ensure()
        summ, entries, masteries = await asyncio.gather(
            self.bot.riot.summoner_by_puuid(puuid), self.bot.riot.league_entries(puuid),
            self.bot.riot.top_masteries(puuid, 3))

        embed = discord.Embed(title=name, color=0xC89B3C)
        if summ:
            embed.set_thumbnail(url=self.bot.ddragon.profile_icon(summ["profileIconId"]))
            embed.description = f"Nível **{summ['summonerLevel']}**"
        queues = {"RANKED_SOLO_5x5": "🏆 Solo/Duo", "RANKED_FLEX_SR": "👥 Flex"}
        for q, label in queues.items():
            e = next((x for x in entries if x["queueType"] == q), None)
            value = (f"**{util.elo_str(e['tier'], e['rank'], e['leaguePoints'])}**\n"
                     f"{util.winrate_str(e['wins'], e['losses'])}") if e else "Sem elo"
            embed.add_field(name=label, value=value, inline=True)
        if masteries:
            lines = [f"**{self.bot.ddragon.champ_name(m['championId'])}** — M{m['championLevel']} · "
                     f"{m['championPoints'] / 1000:,.0f}k pts" for m in masteries]
            embed.add_field(name="⭐ Mais jogados (maestria)", value="\n".join(lines), inline=False)
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------ /partida
    @app_commands.command(name="partida", description="Mostra a partida ao vivo de um jogador (scout!)")
    @app_commands.describe(riot_id="Nick#TAG (vazio = sua conta vinculada)", membro="Membro com conta vinculada")
    async def partida(self, interaction: discord.Interaction, riot_id: str | None = None,
                      membro: discord.Member | None = None):
        await interaction.response.defer(thinking=True)
        puuid, name = await self.resolve(interaction, riot_id, membro)
        game = await self.bot.riot.active_game(puuid)
        if not game:
            return await interaction.followup.send(f"😴 **{name}** não está em partida agora.")
        await self.bot.ddragon.ensure()
        dd = self.bot.ddragon
        parts = game["participants"]

        async def solo_or_none(p):
            if not p.get("puuid"):
                return None
            try:
                return await self.bot.riot.solo_entry(p["puuid"])
            except RiotError:
                return None

        leagues = await asyncio.gather(*(solo_or_none(p) for p in parts))
        teams = {100: [], 200: []}
        for p, e in zip(parts, leagues):
            elo = util.elo_str(e["tier"], e["rank"], e["leaguePoints"]) if e else "Sem elo"
            perks = p.get("perks") or {}
            keystone = dd.runes.get((perks.get("perkIds") or [0])[0], "?")
            spells = f"{dd.summoner_spells.get(p.get('spell1Id'), '?')}/{dd.summoner_spells.get(p.get('spell2Id'), '?')}"
            who = p.get("riotId") or "Jogador oculto"
            marker = "👉 " if p.get("puuid") == puuid else ""
            teams[p["teamId"]].append(
                f"{marker}**{dd.champ_name(p['championId'])}** · {who}\n└ {elo} · {keystone} · {spells}")

        minutes = max(game.get("gameLength", 0), 0) // 60
        embed = discord.Embed(
            title=f"🔴 Ao vivo: {name}",
            description=f"{QUEUES.get(game.get('gameQueueConfigId'), 'Partida')} · {minutes} min de jogo",
            color=0xE84057)
        embed.add_field(name="🔵 Time Azul", value="\n".join(teams[100]) or "—", inline=False)
        embed.add_field(name="🔴 Time Vermelho", value="\n".join(teams[200]) or "—", inline=False)
        bans = game.get("bannedChampions") or []
        for team, label in ((100, "🔵 Bans"), (200, "🔴 Bans")):
            names = [dd.champ_name(b["championId"]) for b in bans if b["teamId"] == team and b["championId"] > 0]
            if names:
                embed.add_field(name=label, value=", ".join(names), inline=True)
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------ /ranking
    @app_commands.command(name="ranking", description="Leaderboard de elo (Solo/Duo) do servidor")
    async def ranking(self, interaction: discord.Interaction):
        rows = await self.bot.db.fetchall("SELECT * FROM accounts WHERE guild_id=?", (interaction.guild_id,))
        if not rows:
            raise UserError("Ninguém vinculou conta ainda. Use `/vincular Nick#TAG`.")
        rows = sorted(rows, key=lambda r: util.elo_score(r["tier"], r["rank"], r["lp"]) or -1, reverse=True)
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, r in enumerate(rows[:20]):
            pos = medals[i] if i < 3 else f"`{i + 1:>2}.`"
            lines.append(f"{pos} <@{r['user_id']}> — **{util.elo_str(r['tier'], r['rank'], r['lp'])}** "
                         f"· {util.winrate_str(r['wins'], r['losses'])}")
        embed = discord.Embed(title="🏆 Ranking do servidor", description="\n".join(lines), color=0xC89B3C)
        embed.set_footer(text="Atualizado automaticamente a cada 10 minutos")
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    # ------------------------------------------------------------ rastreador automático
    @tasks.loop(minutes=10)
    async def tracker(self):
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

        if (tier, rank) != (row["tier"], row["rank"]) and tier:
            old = util.elo_score(row["tier"], row["rank"], row["lp"])
            new = util.elo_score(tier, rank, lp)
            if old is None:
                text = f"🎯 <@{row['user_id']}> terminou as MDs e caiu em **{util.elo_str(tier, rank, lp)}**!"
            elif new > old:
                text = f"🎉 <@{row['user_id']}> subiu pra **{util.elo_str(tier, rank, lp)}**! Bora!"
            else:
                text = f"💀 <@{row['user_id']}> caiu pra **{util.elo_str(tier, rank, lp)}**... F no chat."
            channel = await util.get_channel(self.bot, guild, "alertas")
            if channel:
                await channel.send(text)
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
                    await channel.send(embed=self.match_embed(match, row))

    def match_embed(self, match, row) -> discord.Embed:
        info = match["info"]
        p = next(x for x in info["participants"] if x["puuid"] == row["puuid"])
        dd = self.bot.ddragon
        champ = dd.by_key.get(p["championId"])
        minutes = max(info["gameDuration"] / 60, 1)
        cs = p["totalMinionsKilled"] + p["neutralMinionsKilled"]
        deaths = p["deaths"] or 1
        kda = (p["kills"] + p["assists"]) / deaths
        win = p["win"]
        embed = discord.Embed(
            title=f"{'✅ Vitória' if win else '❌ Derrota'} de {row['riot_id']}",
            description=f"<@{row['user_id']}> · {QUEUES.get(info['queueId'], 'Ranqueada')} · {minutes:.0f} min",
            color=0x2ECC71 if win else 0xE74C3C)
        if champ:
            embed.set_thumbnail(url=dd.champ_icon(champ["id"]))
        embed.add_field(name="Campeão", value=champ["name"] if champ else p["championName"])
        embed.add_field(name="KDA", value=f"{p['kills']}/{p['deaths']}/{p['assists']} ({kda:.2f})")
        embed.add_field(name="Dano em campeões", value=f"{p['totalDamageDealtToChampions']:,}".replace(",", "."))
        embed.add_field(name="CS", value=f"{cs} ({cs / minutes:.1f}/min)")
        embed.add_field(name="Visão", value=str(p.get("visionScore", 0)))
        if p.get("pentaKills"):
            embed.add_field(name="🔥", value="**PENTAKILL!**")
        return embed


async def setup(bot):
    await bot.add_cog(Lol(bot))
