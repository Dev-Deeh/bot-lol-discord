"""Deixa os avisos do app da Bloom mais visuais no Discord.

O robô de avisos (Cloudflare) posta no #notícias de cada time um aviso simples pelo webhook
"Bloom White App" / "Bloom Red App". Assim que ele chega, o bot desenha o card do evento e
edita a mesma mensagem pra mostrar o card (as marcações do cargo continuam lá).
Se o bot estiver fora do ar, o aviso simples fica, então nada se perde."""
import asyncio
import logging

import discord
from discord.ext import commands

from core import cards_aviso
from core.cards_aviso import render_aviso

log = logging.getLogger("bot.avisos")
TEAMS = ("Bloom White", "Bloom Red")
KIND_BY_EMOJI = {"📅": "created", "🔁": "time", "❌": "cancelled", "✏️": "updated", "⏰": "reminder"}


def parse(embed: discord.Embed):
    """Lê o aviso simples que o robô de avisos manda. Devolve None se não for um aviso do app."""
    footer = (embed.footer.text or "") if embed.footer else ""
    team = footer.removesuffix(" App")
    if team not in TEAMS or not embed.title:
        return None
    emoji, _, heading = embed.title.partition(" ")
    kind = KIND_BY_EMOJI.get(emoji)
    if not kind:
        return None
    fields = {f.name: f.value for f in embed.fields}
    start = embed.timestamp
    return {"team": team, "kind": kind, "heading": heading,
            "title": (embed.description or "").strip("* ") or heading,
            "start": start, "type_label": fields.get("Tipo"), "location": fields.get("Onde"),
            "url": embed.url, "color": embed.color}


class Avisos(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.hooks: dict[int, discord.Webhook] = {}

    async def ensure_logo(self, guild: discord.Guild):
        """O logo não vai pro git: se faltar, usa o ícone do servidor (é o mesmo logo da Bloom)."""
        if cards_aviso.LOGO.exists() or not guild.icon:
            return
        try:
            data = await guild.icon.with_size(512).with_format("png").read()
            cards_aviso.LOGO.parent.mkdir(parents=True, exist_ok=True)
            cards_aviso.LOGO.write_bytes(data)
            cards_aviso._logo_cache.clear()
        except Exception:
            log.exception("Não consegui baixar o logo do servidor")

    async def webhook(self, message: discord.Message):
        hook = self.hooks.get(message.webhook_id)
        if not hook:
            hook = next((h for h in await message.channel.webhooks() if h.id == message.webhook_id), None)
            if hook:
                self.hooks[hook.id] = hook
        return hook

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.webhook_id or not message.embeds or not message.guild:
            return
        info = parse(message.embeds[0])
        if not info:
            return
        try:
            await self.ensure_logo(message.guild)
            card = await asyncio.to_thread(render_aviso, info["team"], info["kind"], info["heading"], info["title"],
                                           info["start"], info["type_label"], info["location"])
            hook = await self.webhook(message)
            if not hook:
                log.warning("Sem acesso ao webhook do aviso em #%s", message.channel)
                return
            embed = discord.Embed(title="Abrir no app", url=info["url"], color=info["color"])
            embed.set_image(url="attachment://aviso.jpg")
            await hook.edit_message(message.id, embed=embed,
                                    attachments=[discord.File(card, "aviso.jpg")])
            log.info("Card do aviso: %s · %s", info["team"], info["title"])
        except Exception:
            log.exception("Não consegui trocar o aviso pelo card")


async def setup(bot):
    await bot.add_cog(Avisos(bot))
