"""Draft e estratégia: simulador de pick/ban, pool de campeões, counters/builds e patch notes."""
import asyncio
import logging
import random
import time

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import util
from core.ddragon import patch_of
from core.util import UserError

log = logging.getLogger("bot.draft")
LANE_CHOICES = [app_commands.Choice(name=n, value=v) for n, v in util.LANES]

# Ordem oficial do draft competitivo (fase de bans 1, picks 1, bans 2, picks 2)
SEQUENCE = [("blue", "ban"), ("red", "ban"), ("blue", "ban"), ("red", "ban"), ("blue", "ban"), ("red", "ban"),
            ("blue", "pick"), ("red", "pick"), ("red", "pick"), ("blue", "pick"), ("blue", "pick"), ("red", "pick"),
            ("red", "ban"), ("blue", "ban"), ("red", "ban"), ("blue", "ban"),
            ("red", "pick"), ("blue", "pick"), ("blue", "pick"), ("red", "pick")]
SIDE = {"blue": "🔵", "red": "🔴"}

STAT_PT = {"hp": "Vida", "hpperlevel": "Vida/nível", "mp": "Mana", "mpperlevel": "Mana/nível",
           "movespeed": "Velocidade", "armor": "Armadura", "armorperlevel": "Armadura/nível",
           "spellblock": "Resist. Mágica", "spellblockperlevel": "RM/nível", "attackrange": "Alcance",
           "hpregen": "Regen. vida", "hpregenperlevel": "Regen. vida/nível", "mpregen": "Regen. mana",
           "attackdamage": "Dano de ataque", "attackdamageperlevel": "AD/nível",
           "attackspeed": "Vel. de ataque", "attackspeedperlevel": "Vel. ataque/nível"}
SLUG_FIX = {"MonkeyKing": "wukong"}


def slug(champ: dict) -> str:
    return SLUG_FIX.get(champ["id"], champ["id"].lower())


class DraftState:
    def __init__(self, cog, channel, blue, red, blue_cap, red_cap, seconds):
        self.cog, self.channel = cog, channel
        self.names = {"blue": blue, "red": red}
        self.captains = {"blue": blue_cap, "red": red_cap}
        self.seconds = seconds
        self.step = 0
        self.picks = {"blue": [], "red": []}
        self.bans = {"blue": [], "red": []}
        self.used: set[str] = set()
        self.message: discord.Message | None = None
        self.timer: asyncio.Task | None = None
        self.deadline = 0
        self.lock = asyncio.Lock()

    @property
    def done(self):
        return self.step >= len(SEQUENCE)

    def embed(self) -> discord.Embed:
        e = discord.Embed(title=f"🧠 Draft: {self.names['blue']} vs {self.names['red']}", color=0xC89B3C)
        for side in ("blue", "red"):
            e.add_field(name=f"{SIDE[side]} Bans {self.names[side]}",
                        value=" · ".join(self.bans[side]) or "—", inline=True)
        e.add_field(name="​", value="​", inline=False)
        for side in ("blue", "red"):
            e.add_field(name=f"{SIDE[side]} Picks {self.names[side]}",
                        value="\n".join(f"{i + 1}. {c}" for i, c in enumerate(self.picks[side])) or "—", inline=True)
        if self.done:
            e.description = "✅ **Draft finalizado!** GLHF"
        else:
            side, action = SEQUENCE[self.step]
            cap = self.captains[side]
            who = f" ({cap.mention})" if cap else ""
            e.description = (f"Vez de {SIDE[side]} **{self.names[side]}**{who} — **{action.upper()}** "
                             f"· ⏱️ <t:{self.deadline}:R>\nUse `/draft escolher`")
        e.set_footer(text=f"Etapa {min(self.step + 1, len(SEQUENCE))}/{len(SEQUENCE)}")
        return e

    def start_timer(self):
        if self.timer and not self.timer.done() and self.timer is not asyncio.current_task():
            self.timer.cancel()
        self.deadline = int(time.time()) + self.seconds
        self.timer = asyncio.create_task(self._countdown(self.step))

    async def _countdown(self, step):
        await asyncio.sleep(self.seconds)
        async with self.lock:
            if self.step != step or self.done:
                return
            self.timer = None
            await self.apply(None)

    async def apply(self, champ: str | None):
        """Registra a escolha atual (None = tempo esgotado). Chamar com o lock."""
        side, action = SEQUENCE[self.step]
        target = self.picks if action == "pick" else self.bans
        target[side].append(champ or "⏳ *sem escolha*")
        if champ:
            self.used.add(champ)
        self.step += 1
        if self.done:
            if self.timer and self.timer is not asyncio.current_task():
                self.timer.cancel()
            self.cog.drafts.pop(self.channel.id, None)
        else:
            self.start_timer()
        try:
            await self.message.edit(embed=self.embed())
        except discord.HTTPException:
            pass


class Draft(commands.Cog):
    draft = app_commands.Group(name="draft", description="Simulador de draft (pick/ban)", guild_only=True)
    pool = app_commands.Group(name="pool", description="Pool de campeões do time", guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.drafts: dict[int, DraftState] = {}

    async def cog_load(self):
        self.patch_watcher.start()

    async def cog_unload(self):
        self.patch_watcher.cancel()
        for d in self.drafts.values():
            if d.timer:
                d.timer.cancel()

    async def champ_autocomplete(self, interaction: discord.Interaction, current: str):
        await self.bot.ddragon.ensure()
        return [app_commands.Choice(name=n, value=n) for n in self.bot.ddragon.search(current)]

    async def find_champ(self, text: str) -> dict:
        await self.bot.ddragon.ensure()
        champ = self.bot.ddragon.find(text)
        if not champ:
            raise UserError(f"Não conheço o campeão **{text}**.")
        return champ

    # ============================================================ DRAFT
    @draft.command(name="iniciar", description="Começa um draft com timer neste canal")
    @app_commands.describe(time_azul="Nome do time azul", time_vermelho="Nome do time vermelho",
                           capitao_azul="Só ele escolhe pelo azul (opcional)",
                           capitao_vermelho="Só ele escolhe pelo vermelho (opcional)",
                           tempo="Segundos por escolha (10 a 120)")
    async def draft_iniciar(self, interaction: discord.Interaction, time_azul: str = "Azul",
                            time_vermelho: str = "Vermelho", capitao_azul: discord.Member | None = None,
                            capitao_vermelho: discord.Member | None = None,
                            tempo: app_commands.Range[int, 10, 120] = 30):
        if interaction.channel_id in self.drafts:
            raise UserError("Já tem um draft rolando neste canal. Use `/draft cancelar` antes.")
        await self.bot.ddragon.ensure()
        state = DraftState(self, interaction.channel, time_azul, time_vermelho, capitao_azul, capitao_vermelho, tempo)
        self.drafts[interaction.channel_id] = state
        await interaction.response.send_message("🎮 Draft começando!")
        state.start_timer()
        state.message = await interaction.channel.send(embed=state.embed())

    @draft.command(name="escolher", description="Escolhe/bane um campeão na sua vez")
    @app_commands.autocomplete(campeao=champ_autocomplete)
    async def draft_escolher(self, interaction: discord.Interaction, campeao: str):
        state = self.drafts.get(interaction.channel_id)
        if not state:
            raise UserError("Não tem draft neste canal. Use `/draft iniciar`.")
        champ = await self.find_champ(campeao)
        async with state.lock:
            if state.done:
                raise UserError("O draft já terminou.")
            side, action = SEQUENCE[state.step]
            cap = state.captains[side]
            if cap and interaction.user.id != cap.id:
                raise UserError(f"Agora é a vez de {cap.display_name} ({SIDE[side]}).")
            if champ["name"] in state.used:
                raise UserError(f"**{champ['name']}** já foi escolhido ou banido.")
            await state.apply(champ["name"])
        verb = "banido" if action == "ban" else "escolhido"
        await interaction.response.send_message(f"{SIDE[side]} **{champ['name']}** {verb}!", ephemeral=True)

    @draft.command(name="cancelar", description="Cancela o draft deste canal")
    async def draft_cancelar(self, interaction: discord.Interaction):
        state = self.drafts.pop(interaction.channel_id, None)
        if not state:
            raise UserError("Não tem draft neste canal.")
        if state.timer:
            state.timer.cancel()
        await interaction.response.send_message("🛑 Draft cancelado.")

    # ============================================================ POOL
    @pool.command(name="adicionar", description="Adiciona um campeão ao seu pool")
    @app_commands.autocomplete(campeao=champ_autocomplete)
    @app_commands.choices(rota=LANE_CHOICES)
    async def pool_adicionar(self, interaction: discord.Interaction, campeao: str, rota: app_commands.Choice[str]):
        champ = await self.find_champ(campeao)
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO pools (guild_id, user_id, champion, role) VALUES (?,?,?,?)",
            (interaction.guild_id, interaction.user.id, champ["name"], rota.value))
        await interaction.response.send_message(
            f"✅ **{champ['name']}** adicionado ao seu pool de {util.LANE_EMOJI[rota.value]} {rota.name}.",
            ephemeral=True)

    @pool.command(name="remover", description="Remove um campeão do seu pool")
    @app_commands.autocomplete(campeao=champ_autocomplete)
    async def pool_remover(self, interaction: discord.Interaction, campeao: str):
        champ = await self.find_champ(campeao)
        await self.bot.db.execute("DELETE FROM pools WHERE guild_id=? AND user_id=? AND champion=?",
                                  (interaction.guild_id, interaction.user.id, champ["name"]))
        await interaction.response.send_message(f"🗑️ **{champ['name']}** removido do seu pool.", ephemeral=True)

    @pool.command(name="ver", description="Mostra o pool de alguém")
    async def pool_ver(self, interaction: discord.Interaction, membro: discord.Member | None = None):
        membro = membro or interaction.user
        rows = await self.bot.db.fetchall("SELECT champion, role FROM pools WHERE guild_id=? AND user_id=?",
                                          (interaction.guild_id, membro.id))
        if not rows:
            raise UserError(f"{membro.display_name} ainda não cadastrou campeões. Use `/pool adicionar`.")
        embed = discord.Embed(title=f"🗂️ Pool de {membro.display_name}", color=0x0AC8B9)
        for name, lane in util.LANES:
            champs = [r["champion"] for r in rows if r["role"] == lane]
            if champs:
                embed.add_field(name=f"{util.LANE_EMOJI[lane]} {name}", value=", ".join(champs), inline=False)
        await interaction.response.send_message(embed=embed)

    @pool.command(name="time", description="Visão geral do pool do time, com alertas")
    async def pool_time(self, interaction: discord.Interaction):
        lineup = await self.bot.db.fetchall("SELECT * FROM lineup WHERE guild_id=? AND is_sub=0",
                                            (interaction.guild_id,))
        if not lineup:
            raise UserError("Defina a line-up primeiro com `/lineup definir`.")
        embed = discord.Embed(title="🗂️ Pool do time", color=0x0AC8B9)
        alerts = []
        starters = {r["role"]: r["user_id"] for r in lineup}
        for name, lane in util.LANES:
            uid = starters.get(lane)
            if not uid:
                alerts.append(f"⚠️ Sem titular no **{name}**")
                continue
            rows = await self.bot.db.fetchall(
                "SELECT champion FROM pools WHERE guild_id=? AND user_id=? AND role=?",
                (interaction.guild_id, uid, lane))
            champs = [r["champion"] for r in rows]
            embed.add_field(name=f"{util.LANE_EMOJI[lane]} {name}",
                            value=f"<@{uid}>: " + (", ".join(champs) or "*nenhum*"), inline=False)
            if len(champs) < 3:
                alerts.append(f"⚠️ <@{uid}> tem só **{len(champs)}** campeão(ões) de {name} — fácil de banir!")
        if alerts:
            embed.add_field(name="🚨 Alertas", value="\n".join(alerts), inline=False)
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @pool.command(name="sugerir", description="Sugere picks do pool pra uma rota (ignora o que já saiu no draft)")
    @app_commands.choices(rota=LANE_CHOICES)
    async def pool_sugerir(self, interaction: discord.Interaction, rota: app_commands.Choice[str]):
        players = await self.bot.db.fetchall(
            "SELECT user_id FROM lineup WHERE guild_id=? AND (role=? OR role IS NULL)",
            (interaction.guild_id, rota.value))
        ids = [p["user_id"] for p in players]
        if ids:
            q = ",".join("?" * len(ids))
            rows = await self.bot.db.fetchall(
                f"SELECT * FROM pools WHERE guild_id=? AND role=? AND user_id IN ({q})",
                (interaction.guild_id, rota.value, *ids))
        else:
            rows = await self.bot.db.fetchall("SELECT * FROM pools WHERE guild_id=? AND role=?",
                                              (interaction.guild_id, rota.value))
        state = self.drafts.get(interaction.channel_id)
        used = state.used if state else set()
        options = [r for r in rows if r["champion"] not in used]
        if not options:
            raise UserError(f"Nenhum campeão disponível no pool de {rota.name}. 😬 Hora de treinar uns novos!")
        random.shuffle(options)
        lines = [f"• **{r['champion']}** (<@{r['user_id']}>)" for r in options[:8]]
        note = "\n\n*Já tirei os campeões usados no draft deste canal.*" if state else ""
        await interaction.response.send_message(
            embed=discord.Embed(title=f"💡 Sugestões pro {util.LANE_EMOJI[rota.value]} {rota.name}",
                                description="\n".join(lines) + note, color=0x0AC8B9),
            allowed_mentions=discord.AllowedMentions.none())

    # ============================================================ COUNTER / BUILD
    async def _guide(self, interaction, campeao: str, kind: str):
        champ = await self.find_champ(campeao)
        s = slug(champ)
        if kind == "counter":
            links = {"U.GG": f"https://u.gg/lol/champions/{s}/counter",
                     "OP.GG": f"https://www.op.gg/champions/{s}/counters",
                     "Lolalytics": f"https://lolalytics.com/lol/{s}/counters/"}
            title = f"⚔️ Counters de {champ['name']}"
        else:
            links = {"U.GG": f"https://u.gg/lol/champions/{s}/build",
                     "OP.GG": f"https://www.op.gg/champions/{s}/build",
                     "Lolalytics": f"https://lolalytics.com/lol/{s}/build/"}
            title = f"🛠️ Build de {champ['name']}"
        embed = discord.Embed(title=title, description=f"*{champ['title']}* · {', '.join(champ['tags'])}",
                              color=0xC89B3C)
        embed.set_thumbnail(url=self.bot.ddragon.champ_icon(champ["id"]))
        embed.add_field(name="Dados atualizados do patch",
                        value="\n".join(f"🔗 [{n}]({u})" for n, u in links.items()), inline=False)
        embed.set_footer(text=f"Patch {patch_of(self.bot.ddragon.version)} · a Riot não tem API oficial de "
                              f"counters/builds, então os links levam aos sites de estatística")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="counter", description="Counters de um campeão")
    @app_commands.autocomplete(campeao=champ_autocomplete)
    async def counter(self, interaction: discord.Interaction, campeao: str):
        await self._guide(interaction, campeao, "counter")

    @app_commands.command(name="build", description="Build de um campeão")
    @app_commands.autocomplete(campeao=champ_autocomplete)
    async def build(self, interaction: discord.Interaction, campeao: str):
        await self._guide(interaction, campeao, "build")

    # ============================================================ PATCH
    async def champion_changes(self, champ_id: str, old_v: str, new_v: str) -> list[str]:
        dd = self.bot.ddragon
        try:
            old = await dd.champion_detail(champ_id, old_v)
        except aiohttp.ClientResponseError:
            return ["🆕 Campeão novo!"]
        new = await dd.champion_detail(champ_id, new_v)
        changes = []
        for k, v in new["stats"].items():
            if old["stats"].get(k) != v:
                changes.append(f"{STAT_PT.get(k, k)}: {old['stats'].get(k)} → {v}")
        for key, os_, ns in zip("QWER", old["spells"], new["spells"]):
            for field, label in (("cooldownBurn", "recarga"), ("costBurn", "custo"), ("rangeBurn", "alcance")):
                if os_.get(field) != ns.get(field):
                    changes.append(f"{key} ({ns['name']}) {label}: {os_.get(field)} → {ns.get(field)}")
        return changes

    async def patch_embed(self, guild_id: int) -> discord.Embed:
        dd = self.bot.ddragon
        new_v, old_v = dd.versions[0], dd.previous_patch_version()
        embed = discord.Embed(
            title=f"📜 Patch {patch_of(new_v)}",
            url="https://www.leagueoflegends.com/pt-br/news/tags/patch-notes/",
            description="Notas completas no link acima. Abaixo, mudanças de **status base e "
                        "recarga/custo de habilidades** detectadas nos campeões do pool do time:",
            color=0xC89B3C)
        rows = await self.bot.db.fetchall("SELECT DISTINCT champion FROM pools WHERE guild_id=?", (guild_id,))
        found = 0
        for r in rows:
            champ = dd.find(r["champion"])
            if not champ or not old_v:
                continue
            changes = await self.champion_changes(champ["id"], old_v, new_v)
            if changes and found < 20:
                found += 1
                text = "\n".join(changes[:6]) + ("\n…" if len(changes) > 6 else "")
                embed.add_field(name=f"🔧 {champ['name']}", value=text[:1024], inline=False)
        if not rows:
            embed.add_field(name="—", value="Ninguém cadastrou pool ainda (`/pool adicionar`).")
        elif not found:
            embed.add_field(name="✅", value="Nenhuma mudança numérica nos campeões do pool (pode ter mudanças "
                                            "de mecânica — confira as notas).")
        return embed

    @app_commands.command(name="patch", description="Resumo do patch atual pros campeões do pool do time")
    async def patch(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        await self.bot.ddragon.ensure()
        await interaction.followup.send(embed=await self.patch_embed(interaction.guild_id))

    @tasks.loop(hours=3)
    async def patch_watcher(self):
        try:
            version = await self.bot.ddragon.refresh()
        except Exception:
            log.exception("Falha ao checar patch")
            return
        current = patch_of(version)
        last = await self.bot.db.get_meta("last_patch")
        await self.bot.db.set_meta("last_patch", current)
        if last is None or last == current:
            return
        rows = await self.bot.db.fetchall("SELECT guild_id, value FROM guild_config WHERE key='canal:patch'")
        for r in rows:
            channel = self.bot.get_channel(int(r["value"]))
            if channel:
                try:
                    await channel.send("🚨 **Patch novo no ar!**", embed=await self.patch_embed(r["guild_id"]))
                except Exception:
                    log.exception("Falha ao postar patch")

    @patch_watcher.before_loop
    async def before_patch(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Draft(bot))
