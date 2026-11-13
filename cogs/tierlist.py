"""Tier list de cada jogador, bonitinha.

- Print postado no próprio canal de tier list (📝・nome): o bot lê os campeões (compara cada quadradinho com os
  ícones oficiais) e monta uma mensagem por nível; se não tiver certeza, reposta o print num card.
  Também organiza prints antigos a cada 10 minutos.
- /tierlist criar: o jogador escreve os campeões de cada nível e o bot monta uma mensagem por nível.
- Texto no formato "S: Jinx, Ahri" (uma linha por nível) postado no canal também vira card.
"""
import asyncio
import io
import logging
import re

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import util
from core.cards_tier import TIER_COLORS, render_row
from core.tier_reader import prepare_icons, read_tierlist
from core.util import UserError

log = logging.getLogger("bot.tierlist")
COLOR = 0xE6EDF5
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")
POSITION_ROLES = ("👑 Capitão", "🎓 Coach", "🛡️ Titular", "🔁 Reserva")
TIER_EMOJI = ["🟥", "🟧", "🟨", "🟩", "🟦", "🟪"]
DEFAULT_LABELS = ["S", "A", "B", "C", "D", "E"]


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
        self._icons = None

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
        parts = [r.name.split(" ", 1)[-1] for r in sorted(member.roles, key=lambda r: -r.position)
                 if r.name.startswith(POSITION_ROLES)]
        acc = await self.bot.db.fetchone("SELECT tier, rank, lp FROM accounts WHERE guild_id=? AND user_id=?",
                                         (member.guild.id, member.id))
        if acc and acc["tier"]:
            parts.append(util.elo_str(acc["tier"], acc["rank"], acc["lp"]))
        return " · ".join(parts)

    def base_embed(self, member: discord.Member, subtitle: str) -> discord.Embed:
        e = discord.Embed(title=f"📝 Tier list de {member.display_name}", description=subtitle or None, color=COLOR)
        e.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        team = next((r.name.split(" ", 2)[-1] for r in member.roles
                     if r.name.startswith(("🛡️ Titular ", "🔁 Reserva "))), "Bloom")
        e.set_footer(text=f"{team} • reaja pra comentar")
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

    # ------------------------------------------------------------ uma mensagem por nível
    async def icon_matrix(self):
        """Ícones de todos os campeões preparados pra comparação (carrega uma vez)."""
        if self._icons is None:
            await self.bot.ddragon.ensure()
            dd = self.bot.ddragon
            ids = list(dd.champions)
            imgs = await self.bot.cards.imgs([dd.champ_icon(i) for i in ids])
            self._icons = await asyncio.to_thread(prepare_icons, {i: im for i, im in zip(ids, imgs) if im})
        return self._icons

    async def clear_bot_messages(self, channel):
        async for msg in channel.history(limit=50):
            if msg.author.id == self.bot.user.id:
                try:
                    await msg.delete()
                except discord.HTTPException:
                    pass

    async def post_tiers(self, channel, member: discord.Member, tiers: list[tuple[str, list[dict]]],
                         print_bytes: bytes | None = None, print_ext: str = ".png"):
        """Abertura + uma mensagem por nível (cor, ícones e nomes) + o print original no fim."""
        await self.clear_bot_messages(channel)
        total = sum(len(c) for _, c in tiers)
        head = self.base_embed(member, await self.subtitle(member))
        head.description = (head.description + "\n\n" if head.description else "") + \
            f"**{total} campeões** em {len(tiers)} níveis. Reaja nos níveis pra comentar! 👇"
        head.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=head)
        for i, (name, champs) in enumerate(tiers):
            row = await render_row(self.bot.cards, name, i, champs)
            r, g, b = TIER_COLORS[i % len(TIER_COLORS)]
            e = discord.Embed(title=f"{TIER_EMOJI[i % len(TIER_EMOJI)]} {name}", color=(r << 16) | (g << 8) | b,
                              description=" · ".join(c["name"] for c in champs) or "—")
            e.set_image(url="attachment://tier.png")
            e.set_footer(text=f"{len(champs)} campeões")
            await channel.send(embed=e, file=discord.File(row, filename="tier.png"))
        if print_bytes:
            e = discord.Embed(title="🖼️ Print original", color=0x2B2D31)
            e.set_image(url=f"attachment://print{print_ext}")
            await channel.send(embed=e, file=discord.File(io.BytesIO(print_bytes), filename=f"print{print_ext}"))

    async def read_print(self, data: bytes):
        """Tenta ler o print; devolve [(nome, [campeões])] só se a leitura for confiável."""
        icon_ids, mat = await self.icon_matrix()
        rows = await asyncio.to_thread(read_tierlist, data, icon_ids, mat)
        rows = [r for r in rows if r[2]]
        dists = [d for r in rows for _, d, _ in r[2]]
        if len(rows) < 2 or not dists:
            return None
        # só confia se TODOS os ícones baterem bem (nos testes, acima de 0,5 começa a errar)
        if max(dists) >= 0.5:
            return None
        dd = self.bot.ddragon
        return [(DEFAULT_LABELS[i] if i < len(DEFAULT_LABELS) else f"Nível {i + 1}",
                 [dd.champions[c] for c, _, _ in r[2]]) for i, r in enumerate(rows)]

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
        await self.post_tiers(channel, member, tiers)
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
            a = images[0]
            ext = "." + (a.content_type or "image/png").split("/")[-1].replace("jpeg", "jpg")
            data = await a.read()
            try:
                tiers = await self.read_print(data)
            except Exception:
                log.exception("Falha ao ler o print da tier list")
                tiers = None
            if tiers:
                await self.post_tiers(message.channel, member, tiers, data, ext)
            else:
                await self.post_image(message.channel, member, data, ext, message.created_at)
                await message.channel.send("ℹ️ Não consegui ler os campeões desse print com segurança. "
                                           "Use **/tierlist criar** pra montar com os ícones, nível por nível.",
                                           delete_after=120)
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
