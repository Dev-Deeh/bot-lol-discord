"""Tier list de cada jogador, bonitinha.

- Print postado no próprio canal de tier list (📝・nome): o bot reposta num card com o nome, a foto e o elo do
  jogador e apaga a mensagem crua. Também organiza prints antigos a cada 10 minutos.
- /tierlist criar: o jogador escreve os campeões de cada nível e o bot gera a imagem com os ícones.
- Texto no formato "S: Jinx, Ahri" (uma linha por nível) postado no canal também vira card.
"""
import io
import logging
import re

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import util
from core.cards_tier import render
from core.util import UserError

log = logging.getLogger("bot.tierlist")
COLOR = 0xE6EDF5
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")
POSITION_ROLES = ("👑 Capitão", "🎓 Coach", "🛡️ Titular", "🔁 Reserva")


class TierModal(discord.ui.Modal, title="Monte sua tier list"):
    s = discord.ui.TextInput(label="Tier S (campeões separados por vírgula)", style=discord.TextStyle.paragraph,
                             required=False, max_length=400, placeholder="Jinx, Ahri, Thresh")
    a = discord.ui.TextInput(label="Tier A", style=discord.TextStyle.paragraph, required=False, max_length=400)
    b = discord.ui.TextInput(label="Tier B", style=discord.TextStyle.paragraph, required=False, max_length=400)
    c = discord.ui.TextInput(label="Tier C", style=discord.TextStyle.paragraph, required=False, max_length=400)
    d = discord.ui.TextInput(label="Tier D", style=discord.TextStyle.paragraph, required=False, max_length=400)

    def __init__(self, cog, channel):
        super().__init__()
        self.cog, self.channel = cog, channel

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        tiers = [(n, f.value) for n, f in zip("SABCD", (self.s, self.a, self.b, self.c, self.d))]
        unknown = await self.cog.post_card(self.channel, interaction.user, tiers)
        msg = f"✅ Tier list publicada em {self.channel.mention}!"
        if unknown:
            msg += f"\n⚠️ Não reconheci: {', '.join(unknown[:15])}"
        await interaction.followup.send(msg, ephemeral=True)


class TierList(commands.Cog):
    tierlist = app_commands.Group(name="tierlist", description="Sua tier list de campeões", guild_only=True)

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.tidy.start()

    async def cog_unload(self):
        self.tidy.cancel()

    # ------------------------------------------------------------ helpers
    async def owner_of(self, channel_id: int):
        row = await self.bot.db.fetchone("SELECT owner_id FROM tier_channels WHERE channel_id=?", (channel_id,))
        return row["owner_id"] if row else None

    async def channel_of(self, guild_id: int, user_id: int):
        row = await self.bot.db.fetchone("SELECT channel_id FROM tier_channels WHERE guild_id=? AND owner_id=?",
                                         (guild_id, user_id))
        return self.bot.get_channel(row["channel_id"]) if row else None

    async def subtitle(self, member: discord.Member) -> str:
        parts = [r.name.split(" ", 1)[-1] for r in member.roles if r.name in POSITION_ROLES]
        acc = await self.bot.db.fetchone("SELECT tier, rank, lp FROM accounts WHERE guild_id=? AND user_id=?",
                                         (member.guild.id, member.id))
        if acc and acc["tier"]:
            parts.append(util.elo_str(acc["tier"], acc["rank"], acc["lp"]))
        return " · ".join(parts)

    def base_embed(self, member: discord.Member, subtitle: str) -> discord.Embed:
        e = discord.Embed(title=f"📝 Tier list de {member.display_name}", description=subtitle or None, color=COLOR)
        e.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        e.set_footer(text="Bloom White • reaja pra comentar")
        return e

    async def post_image(self, channel, member: discord.Member, data: bytes, ext: str, when=None):
        e = self.base_embed(member, await self.subtitle(member))
        name = f"tierlist{ext}"
        e.set_image(url=f"attachment://{name}")
        if when:
            e.timestamp = when
        msg = await channel.send(embed=e, file=discord.File(io.BytesIO(data), filename=name))
        for emoji in ("🔥", "👏", "🤔"):
            try:
                await msg.add_reaction(emoji)
            except discord.HTTPException:
                pass

    async def post_card(self, channel, member: discord.Member, tiers_text: list[tuple[str, str]]) -> list[str]:
        await self.bot.ddragon.ensure()
        tiers, unknown = [], []
        for name, text in tiers_text:
            champs = []
            for raw in re.split(r"[,;\n/]+", text or ""):
                raw = raw.strip()
                if not raw:
                    continue
                champ = self.bot.ddragon.find(raw)
                if champ is None:
                    unknown.append(raw)
                elif champ not in champs:
                    champs.append(champ)
            tiers.append((name, champs))
        while tiers and not tiers[-1][1]:
            tiers.pop()
        if not any(c for _, c in tiers):
            raise UserError("Não reconheci nenhum campeão. Escreva os nomes separados por vírgula.")
        card = await render(self.bot.cards, member.display_name, await self.subtitle(member), tiers)
        await self.post_image(channel, member, card.getvalue(), ".jpg")
        return unknown

    # ------------------------------------------------------------ mensagens no canal de tier list
    async def handle_message(self, message: discord.Message) -> bool:
        if message.author.bot or not message.guild:
            return False
        owner_id = await self.owner_of(message.channel.id)
        if owner_id is None:
            return False
        member = message.guild.get_member(owner_id) or message.author
        images = [a for a in message.attachments if a.filename.lower().endswith(IMAGE_EXT)
                  or (a.content_type or "").startswith("image/")]
        if images:
            for a in images:
                ext = "." + (a.content_type or "image/png").split("/")[-1].replace("jpeg", "jpg")
                await self.post_image(message.channel, member, await a.read(), ext, message.created_at)
        elif re.search(r"^\s*\w[\w +\-]{0,20}\s*[:=-]\s*\S", message.content or "", re.M):
            tiers = []
            for line in message.content.splitlines():
                m = re.match(r"^\s*([\w +\-]{1,20}?)\s*[:=-]\s*(.+)$", line)
                if m:
                    tiers.append((m.group(1), m.group(2)))
            try:
                await self.post_card(message.channel, member, tiers[:6])
            except UserError:
                return False
        else:
            return False
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        try:
            await self.handle_message(message)
        except Exception:
            log.exception("Falha ao organizar tier list")

    @tasks.loop(minutes=10)
    async def tidy(self):
        """Organiza prints que ficaram sem formatar (ex.: postados com o bot desligado)."""
        for row in await self.bot.db.fetchall("SELECT channel_id FROM tier_channels"):
            channel = self.bot.get_channel(row["channel_id"])
            if channel is None:
                continue
            try:
                async for msg in channel.history(limit=15, oldest_first=True):
                    await self.handle_message(msg)
            except discord.HTTPException:
                pass

    @tidy.before_loop
    async def before_tidy(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------ /tierlist
    @tierlist.command(name="criar", description="Monte sua tier list escrevendo os campeões de cada nível")
    async def tierlist_criar(self, interaction: discord.Interaction):
        channel = await self.channel_of(interaction.guild_id, interaction.user.id)
        if channel is None:
            raise UserError("Você ainda não tem canal de tier list (ele é criado pra quem é do time).")
        await interaction.response.send_modal(TierModal(self, channel))


async def setup(bot):
    await bot.add_cog(TierList(bot))
