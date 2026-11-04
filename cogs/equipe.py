"""Gestão do time: scrims (agenda + presença + lembretes + histórico), line-up e VOD review."""
import time
from collections import defaultdict

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import util
from core.util import UserError

LANE_CHOICES = [app_commands.Choice(name=n, value=v) for n, v in util.LANES]
RSVP = {"sim": "✅ Vão", "talvez": "🤔 Talvez", "nao": "❌ Não vão"}


async def scrim_embed(bot, scrim) -> discord.Embed:
    rows = await bot.db.fetchall("SELECT user_id, status FROM scrim_rsvp WHERE scrim_id=?", (scrim["id"],))
    groups = defaultdict(list)
    for r in rows:
        groups[r["status"]].append(f"<@{r['user_id']}>")
    ts = scrim["start_ts"]
    embed = discord.Embed(title=f"⚔️ Scrim vs {scrim['opponent']}",
                          description=f"📅 <t:{ts}:F> (<t:{ts}:R>)", color=0x5865F2)
    for key, label in RSVP.items():
        embed.add_field(name=f"{label} ({len(groups[key])})", value="\n".join(groups[key]) or "—", inline=True)
    if scrim["result"]:
        res = "🏆 Vitória" if scrim["result"] == "vitoria" else "💔 Derrota"
        embed.add_field(name="Resultado", value=f"{res} {scrim['score'] or ''}", inline=False)
    embed.set_footer(text=f"Scrim #{scrim['id']} · lembrete automático 30 min antes")
    return embed


class ScrimView(util.BaseView):
    """View persistente: os botões continuam funcionando mesmo depois de reiniciar o bot."""

    def __init__(self):
        super().__init__(timeout=None)

    async def _rsvp(self, interaction: discord.Interaction, status: str):
        bot = interaction.client
        scrim = await bot.db.fetchone("SELECT * FROM scrims WHERE message_id=?", (interaction.message.id,))
        if not scrim:
            return await interaction.response.send_message("Essa scrim não existe mais.", ephemeral=True)
        await bot.db.execute("INSERT OR REPLACE INTO scrim_rsvp (scrim_id, user_id, status) VALUES (?,?,?)",
                             (scrim["id"], interaction.user.id, status))
        await interaction.response.edit_message(embed=await scrim_embed(bot, scrim))

    @discord.ui.button(label="Vou", emoji="✅", style=discord.ButtonStyle.success, custom_id="scrim:sim")
    async def sim(self, interaction, button):
        await self._rsvp(interaction, "sim")

    @discord.ui.button(label="Talvez", emoji="🤔", style=discord.ButtonStyle.secondary, custom_id="scrim:talvez")
    async def talvez(self, interaction, button):
        await self._rsvp(interaction, "talvez")

    @discord.ui.button(label="Não vou", emoji="❌", style=discord.ButtonStyle.danger, custom_id="scrim:nao")
    async def nao(self, interaction, button):
        await self._rsvp(interaction, "nao")


class Equipe(commands.Cog):
    scrim = app_commands.Group(name="scrim", description="Agenda e histórico de scrims", guild_only=True)
    lineup = app_commands.Group(name="lineup", description="Line-up do time", guild_only=True)
    vod = app_commands.Group(name="vod", description="VOD review", guild_only=True)

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(ScrimView())
        self.reminders.start()

    async def cog_unload(self):
        self.reminders.cancel()

    async def get_scrim(self, guild_id: int, scrim_id: int):
        row = await self.bot.db.fetchone("SELECT * FROM scrims WHERE id=? AND guild_id=?", (scrim_id, guild_id))
        if not row:
            raise UserError(f"Não achei a scrim #{scrim_id}.")
        return row

    # ============================================================ SCRIM
    @scrim.command(name="marcar", description="Marca uma scrim com confirmação de presença")
    @app_commands.describe(adversario="Nome do time adversário", data="hoje, amanhã, sexta, 25/12...",
                           hora="20h, 20:30...")
    async def scrim_marcar(self, interaction: discord.Interaction, adversario: str, data: str, hora: str):
        when = util.parse_when(data, hora)
        channel = await util.get_channel(self.bot, interaction.guild, "scrims") or interaction.channel
        scrim_id = await self.bot.db.execute(
            "INSERT INTO scrims (guild_id, channel_id, opponent, start_ts, created_by) VALUES (?,?,?,?,?)",
            (interaction.guild_id, channel.id, adversario, int(when.timestamp()), interaction.user.id))
        scrim = await self.get_scrim(interaction.guild_id, scrim_id)
        msg = await channel.send(embed=await scrim_embed(self.bot, scrim), view=ScrimView())
        await self.bot.db.execute("UPDATE scrims SET message_id=? WHERE id=?", (msg.id, scrim_id))
        await interaction.response.send_message(f"✅ Scrim #{scrim_id} marcada em {channel.mention}!",
                                                ephemeral=channel != interaction.channel)

    @scrim.command(name="resultado", description="Registra o resultado de uma scrim")
    @app_commands.describe(id="Número da scrim", placar="Ex.: 2x1 (opcional)")
    @app_commands.choices(resultado=[app_commands.Choice(name="Vitória", value="vitoria"),
                                     app_commands.Choice(name="Derrota", value="derrota")])
    async def scrim_resultado(self, interaction: discord.Interaction, id: int,
                              resultado: app_commands.Choice[str], placar: str | None = None):
        scrim = await self.get_scrim(interaction.guild_id, id)
        await interaction.response.defer()
        first_time = scrim["result"] is None
        await self.bot.db.execute("UPDATE scrims SET result=?, score=? WHERE id=?", (resultado.value, placar, id))
        scrim = await self.get_scrim(interaction.guild_id, id)
        # atualiza a mensagem original
        channel = interaction.guild.get_channel(scrim["channel_id"])
        if channel and scrim["message_id"]:
            try:
                msg = await channel.fetch_message(scrim["message_id"])
                await msg.edit(embed=await scrim_embed(self.bot, scrim))
            except discord.HTTPException:
                pass
        # XP pra quem confirmou presença
        if first_time:
            for r in await self.bot.db.fetchall(
                    "SELECT user_id FROM scrim_rsvp WHERE scrim_id=? AND status='sim'", (id,)):
                try:
                    member = (interaction.guild.get_member(r["user_id"])
                              or await interaction.guild.fetch_member(r["user_id"]))
                except discord.NotFound:
                    continue
                await util.give_xp(self.bot, interaction.guild, member, 50, 25, interaction.channel)
        emoji = "🏆" if resultado.value == "vitoria" else "💔"
        await interaction.followup.send(
            f"{emoji} Resultado registrado: **{resultado.name}** vs {scrim['opponent']} {placar or ''}\n"
            f"(+50 XP e +25 moedas pra quem confirmou presença)")

    @scrim.command(name="historico", description="Histórico e winrate de scrims")
    @app_commands.describe(adversario="Filtrar por time (opcional)")
    async def scrim_historico(self, interaction: discord.Interaction, adversario: str | None = None):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM scrims WHERE guild_id=? AND result IS NOT NULL ORDER BY start_ts DESC",
            (interaction.guild_id,))
        if adversario:
            rows = [r for r in rows if util.normalize(adversario) in util.normalize(r["opponent"])]
        if not rows:
            raise UserError("Nenhuma scrim com resultado registrado ainda.")
        wins = sum(r["result"] == "vitoria" for r in rows)
        embed = discord.Embed(
            title=f"📊 Histórico de scrims{' vs ' + adversario if adversario else ''}",
            description=f"**{wins}V {len(rows) - wins}D** · winrate **{wins / len(rows) * 100:.0f}%**",
            color=0x5865F2)
        per_team = defaultdict(lambda: [0, 0])
        for r in rows:
            per_team[r["opponent"]][0 if r["result"] == "vitoria" else 1] += 1
        table = [f"**{t}** — {w}V {l}D ({w / (w + l) * 100:.0f}%)"
                 for t, (w, l) in sorted(per_team.items(), key=lambda x: -sum(x[1]))[:10]]
        embed.add_field(name="Por adversário", value="\n".join(table), inline=False)
        recent = [f"{'✅' if r['result'] == 'vitoria' else '❌'} <t:{r['start_ts']}:d> vs {r['opponent']} "
                  f"{r['score'] or ''}" for r in rows[:8]]
        embed.add_field(name="Últimas", value="\n".join(recent), inline=False)
        await interaction.response.send_message(embed=embed)

    @scrim.command(name="proximas", description="Lista as próximas scrims")
    async def scrim_proximas(self, interaction: discord.Interaction):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM scrims WHERE guild_id=? AND start_ts>? ORDER BY start_ts LIMIT 10",
            (interaction.guild_id, int(time.time())))
        if not rows:
            raise UserError("Nenhuma scrim marcada. Use `/scrim marcar`.")
        lines = []
        for r in rows:
            n = await self.bot.db.fetchone(
                "SELECT COUNT(*) AS c FROM scrim_rsvp WHERE scrim_id=? AND status='sim'", (r["id"],))
            lines.append(f"`#{r['id']}` <t:{r['start_ts']}:F> vs **{r['opponent']}** · ✅ {n['c']}")
        await interaction.response.send_message(
            embed=discord.Embed(title="📅 Próximas scrims", description="\n".join(lines), color=0x5865F2))

    @scrim.command(name="cancelar", description="Cancela uma scrim")
    async def scrim_cancelar(self, interaction: discord.Interaction, id: int):
        scrim = await self.get_scrim(interaction.guild_id, id)
        await self.bot.db.execute("DELETE FROM scrims WHERE id=?", (id,))
        await self.bot.db.execute("DELETE FROM scrim_rsvp WHERE scrim_id=?", (id,))
        channel = interaction.guild.get_channel(scrim["channel_id"])
        if channel and scrim["message_id"]:
            try:
                msg = await channel.fetch_message(scrim["message_id"])
                await msg.edit(content=f"🚫 **Scrim vs {scrim['opponent']} cancelada.**", embed=None, view=None)
            except discord.HTTPException:
                pass
        await interaction.response.send_message(f"🚫 Scrim #{id} cancelada.")

    @tasks.loop(minutes=1)
    async def reminders(self):
        now = int(time.time())
        rows = await self.bot.db.fetchall(
            "SELECT * FROM scrims WHERE reminded=0 AND start_ts>? AND start_ts<=?", (now, now + 30 * 60))
        for s in rows:
            await self.bot.db.execute("UPDATE scrims SET reminded=1 WHERE id=?", (s["id"],))
            channel = self.bot.get_channel(s["channel_id"])
            if not channel:
                continue
            people = await self.bot.db.fetchall(
                "SELECT user_id, status FROM scrim_rsvp WHERE scrim_id=? AND status IN ('sim','talvez')", (s["id"],))
            sim = " ".join(f"<@{p['user_id']}>" for p in people if p["status"] == "sim") or "ninguém confirmou 😬"
            talvez = " ".join(f"<@{p['user_id']}>" for p in people if p["status"] == "talvez")
            text = f"⏰ **Scrim vs {s['opponent']}** começa <t:{s['start_ts']}:R>!\n✅ {sim}"
            if talvez:
                text += f"\n🤔 Confirmem aí: {talvez}"
            await channel.send(text)

    @reminders.before_loop
    async def before_reminders(self):
        await self.bot.wait_until_ready()

    # ============================================================ LINE-UP
    @lineup.command(name="definir", description="Define o titular de uma rota")
    @app_commands.choices(rota=LANE_CHOICES)
    async def lineup_definir(self, interaction: discord.Interaction, rota: app_commands.Choice[str],
                             membro: discord.Member):
        await self.bot.db.execute("DELETE FROM lineup WHERE guild_id=? AND role=? AND is_sub=0",
                                  (interaction.guild_id, rota.value))
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO lineup (guild_id, user_id, role, is_sub) VALUES (?,?,?,0)",
            (interaction.guild_id, membro.id, rota.value))
        await interaction.response.send_message(
            f"{util.LANE_EMOJI[rota.value]} {membro.mention} agora é o titular do **{rota.name}**.")

    @lineup.command(name="reserva", description="Adiciona um reserva (sub)")
    @app_commands.choices(rota=LANE_CHOICES)
    async def lineup_reserva(self, interaction: discord.Interaction, membro: discord.Member,
                             rota: app_commands.Choice[str] | None = None):
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO lineup (guild_id, user_id, role, is_sub) VALUES (?,?,?,1)",
            (interaction.guild_id, membro.id, rota.value if rota else None))
        await interaction.response.send_message(
            f"🔁 {membro.mention} adicionado como reserva{' de ' + rota.name if rota else ''}.")

    @lineup.command(name="remover", description="Remove alguém da line-up")
    async def lineup_remover(self, interaction: discord.Interaction, membro: discord.Member):
        await self.bot.db.execute("DELETE FROM lineup WHERE guild_id=? AND user_id=?",
                                  (interaction.guild_id, membro.id))
        await interaction.response.send_message(f"👋 {membro.mention} removido da line-up.")

    @lineup.command(name="ver", description="Mostra a line-up do time")
    async def lineup_ver(self, interaction: discord.Interaction):
        rows = await self.bot.db.fetchall("SELECT * FROM lineup WHERE guild_id=?", (interaction.guild_id,))
        starters = {r["role"]: r["user_id"] for r in rows if not r["is_sub"]}
        lines = [f"{util.LANE_EMOJI[v]} **{n}** — " + (f"<@{starters[v]}>" if v in starters else "*vaga aberta*")
                 for n, v in util.LANES]
        subs = [f"<@{r['user_id']}>" + (f" ({util.LANE_NAME[r['role']]})" if r["role"] else "")
                for r in rows if r["is_sub"]]
        embed = discord.Embed(title="📋 Line-up", description="\n".join(lines), color=0xC89B3C)
        embed.add_field(name="🔁 Reservas", value="\n".join(subs) or "—", inline=False)
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    # ============================================================ VOD
    @vod.command(name="adicionar", description="Salva um VOD/replay com tags")
    @app_commands.describe(link="Link do vídeo", tags="Separadas por vírgula: erro de draft, teamfight boa",
                           descricao="Comentário (opcional)")
    async def vod_adicionar(self, interaction: discord.Interaction, link: str, tags: str,
                            descricao: str | None = None):
        if not link.startswith(("http://", "https://")):
            raise UserError("O link precisa começar com http:// ou https://")
        tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()]
        vod_id = await self.bot.db.execute(
            "INSERT INTO vods (guild_id, url, tags, description, author_id, created_ts) VALUES (?,?,?,?,?,?)",
            (interaction.guild_id, link, ",".join(tag_list), descricao, interaction.user.id, int(time.time())))
        embed = discord.Embed(title=f"🎬 VOD #{vod_id}", url=link, description=descricao or "", color=0x9B59B6)
        embed.add_field(name="Tags", value=" ".join(f"`{t}`" for t in tag_list) or "—")
        embed.set_footer(text=f"Enviado por {interaction.user.display_name}")
        channel = await util.get_channel(self.bot, interaction.guild, "vod")
        if channel and channel != interaction.channel:
            await channel.send(embed=embed)
            await interaction.response.send_message(f"✅ VOD salvo e postado em {channel.mention}.", ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed)

    @vod.command(name="listar", description="Lista VODs salvos (filtra por tag)")
    async def vod_listar(self, interaction: discord.Interaction, tag: str | None = None):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM vods WHERE guild_id=? ORDER BY id DESC", (interaction.guild_id,))
        if tag:
            rows = [r for r in rows if tag.strip().lower() in r["tags"].split(",")]
        if not rows:
            raise UserError("Nenhum VOD encontrado.")
        lines = [f"`#{r['id']}` [{(r['description'] or 'VOD')[:50]}]({r['url']}) · "
                 + " ".join(f"`{t}`" for t in r["tags"].split(",") if t) for r in rows[:15]]
        all_tags = defaultdict(int)
        for r in await self.bot.db.fetchall("SELECT tags FROM vods WHERE guild_id=?", (interaction.guild_id,)):
            for t in r["tags"].split(","):
                if t:
                    all_tags[t] += 1
        embed = discord.Embed(title=f"🎬 VODs{' · ' + tag if tag else ''}", description="\n".join(lines),
                              color=0x9B59B6)
        embed.add_field(name="Tags usadas",
                        value=" ".join(f"`{t}` ({n})" for t, n in sorted(all_tags.items(), key=lambda x: -x[1])[:20]))
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Equipe(bot))
