"""Jogos grátis e promoções.

- Jogos grátis (a cada 30 min): GamerPower (Epic, Steam, GOG, itch.io, Prime Gaming...) -> canal "canal:gratis".
  Também posta itens/loot de League of Legends e Riot quando aparecem.
- Promoções da Steam em REAIS (1x por dia, às 12h de Brasília) -> canal "canal:promos".
Na primeira vez em um servidor, posta só os 3 jogos grátis mais recentes.
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import aiohttp
import discord
from discord.ext import commands, tasks

from core.util import TZ

log = logging.getLogger("bot.promos")
UA = {"User-Agent": "BotDeehLOL/1.0 (+https://github.com/Dev-Deeh/bot-lol-discord)"}
GIVEAWAYS = "https://www.gamerpower.com/api/giveaways"
STEAM_SPECIALS = "https://store.steampowered.com/api/featuredcategories?cc=br&l=brazilian"
LOL_LOOT = re.compile(r"league of legends|riot|valorant|teamfight tactics|\btft\b|wild rift", re.I)
FIRST_RUN_POSTS = 3


def brl(cents) -> str:
    return f"R$ {cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def giveaway_embed(g) -> discord.Embed:
    e = discord.Embed(title=f"🎁 {g['title']}"[:256], url=g.get("open_giveaway_url") or g.get("gamerpower_url"),
                      description=re.sub(r"\s+", " ", g.get("description") or "")[:300] or None, color=0x2ECC71)
    if g.get("image"):
        e.set_image(url=g["image"])
    worth = g.get("worth")
    e.add_field(name="Plataforma", value=(g.get("platforms") or "—")[:100], inline=True)
    if worth and worth != "N/A":
        e.add_field(name="Valia", value=f"~~{worth}~~ **GRÁTIS**", inline=True)
    end = g.get("end_date")
    if end and end != "N/A":
        try:
            ts = int(datetime.strptime(end, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
            e.add_field(name="Até", value=f"<t:{ts}:f> (<t:{ts}:R>)", inline=True)
        except ValueError:
            pass
    e.set_footer(text="Pegue antes que acabe! • GamerPower")
    return e


class Promos(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.free_games.start()
        self.steam_deals.start()

    async def cog_unload(self):
        self.free_games.cancel()
        self.steam_deals.cancel()

    async def get_json(self, url):
        async with self.bot.session.get(url, headers=UA, timeout=aiohttp.ClientTimeout(total=20)) as r:
            if r.status != 200:
                log.warning("%s respondeu %s", url, r.status)
                return None
            return await r.json(content_type=None)

    async def guilds_with(self, key):
        rows = await self.bot.db.fetchall("SELECT guild_id, value FROM guild_config WHERE key=?", (key,))
        return [(r["guild_id"], self.bot.get_channel(int(r["value"]))) for r in rows]

    # ------------------------------------------------------------ jogos grátis
    async def fetch_giveaways(self) -> list[dict]:
        games = await self.get_json(f"{GIVEAWAYS}?platform=pc&type=game&sort-by=date") or []
        loot = await self.get_json(f"{GIVEAWAYS}?type=loot&sort-by=date") or []
        loot = [g for g in loot if LOL_LOOT.search(g.get("title", "") + " " + g.get("description", ""))]
        items = [g for g in games + loot if isinstance(g, dict) and g.get("id")]
        return sorted(items, key=lambda g: g.get("published_date") or "", reverse=True)

    @tasks.loop(minutes=30)
    async def free_games(self):
        targets = await self.guilds_with("canal:gratis")
        if not targets:
            return
        try:
            items = await self.fetch_giveaways()
        except Exception:
            log.exception("Falha ao buscar jogos grátis")
            return
        if not items:
            return
        for guild_id, channel in targets:
            if channel is None:
                continue
            raw = await self.bot.db.get_config(guild_id, "gratis_seen")
            seen = set(json.loads(raw)) if raw else None
            new = items[:FIRST_RUN_POSTS] if seen is None else [g for g in items if str(g["id"]) not in seen][:6]
            for g in reversed(new):
                try:
                    await channel.send(embed=giveaway_embed(g))
                except discord.HTTPException:
                    log.exception("Falha ao postar jogo grátis")
            keep = list(dict.fromkeys([str(g["id"]) for g in items] + list(seen or [])))[:500]
            await self.bot.db.set_config(guild_id, "gratis_seen", json.dumps(keep))

    @free_games.before_loop
    async def before_free(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------ promoções da Steam (diário)
    async def steam_embed(self):
        data = await self.get_json(STEAM_SPECIALS)
        items = ((data or {}).get("specials") or {}).get("items") or []
        items = sorted([i for i in items if i.get("discounted") and i.get("discount_percent")],
                       key=lambda i: -i["discount_percent"])[:8]
        if not items:
            return None
        e = discord.Embed(title="💸 Promoções do dia na Steam", url="https://store.steampowered.com/specials",
                          description="As maiores promoções em destaque, com preço em reais.", color=0x1B2838)
        for i in items:
            line = f"~~{brl(i['original_price'])}~~ **{brl(i['final_price'])}** (-{i['discount_percent']}%)"
            if i.get("discount_expiration"):
                line += f" · até <t:{i['discount_expiration']}:d>"
            line += f"\n[Ver na Steam](https://store.steampowered.com/app/{i['id']})"
            e.add_field(name=i["name"][:256], value=line, inline=False)
        if items[0].get("large_capsule_image"):
            e.set_image(url=items[0]["large_capsule_image"])
        e.set_footer(text="Steam • preços do Brasil")
        return e

    @tasks.loop(minutes=15)
    async def steam_deals(self):
        now = datetime.now(TZ)
        if now.hour < 12:
            return
        today = now.strftime("%Y-%m-%d")
        targets = await self.guilds_with("canal:promos")
        pending = [(gid, ch) for gid, ch in targets
                   if ch is not None and await self.bot.db.get_config(gid, "promos_last") != today]
        if not pending:
            return
        try:
            embed = await self.steam_embed()
        except Exception:
            log.exception("Falha ao buscar promoções da Steam")
            return
        if embed is None:
            return
        for gid, ch in pending:
            try:
                await ch.send(embed=embed)
                await self.bot.db.set_config(gid, "promos_last", today)
            except discord.HTTPException:
                log.exception("Falha ao postar promoções")

    @steam_deals.before_loop
    async def before_deals(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Promos(bot))
