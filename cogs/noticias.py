"""Notícias oficiais do League of Legends (site da Riot em português) postadas no Discord.

A cada 20 minutos lê https://www.leagueoflegends.com/pt-br/news/ (os dados vêm embutidos na página),
e publica as novidades:
  - patch notes  -> canal configurado em "canal:patch" (se não houver, vai pro de notícias)
  - o resto       -> canal configurado em "canal:lolnews"
Na primeira vez em um servidor, posta as 3 mais recentes pra o canal não começar vazio.
"""
import json
import logging
import re
from datetime import datetime

import aiohttp
import discord
from discord.ext import commands, tasks

log = logging.getLogger("bot.noticias")
NEWS_PAGE = "https://www.leagueoflegends.com/pt-br/news/"
SITE = "https://www.leagueoflegends.com"
UA = {"User-Agent": "Mozilla/5.0 (compatible; BotDeehLOL/1.0)"}
CATEGORY_EMOJI = {"game-updates": "🛠️", "esports": "🏆", "community": "🤝", "media": "🎬", "dev": "🧪",
                  "announcements": "📣", "lore": "📖", "riot-games": "🎮"}
COLOR = 0xC89B3C  # dourado do LoL
FIRST_RUN_POSTS = 3
MAX_PER_TICK = 8


def is_patch_notes(item) -> bool:
    return bool(re.search(r"notas da atualiza|patch-\d|patch notes", item["title"] + " " + item["url"], re.I))


def parse_news(html: str) -> list[dict]:
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        return []
    found, seen = [], set()

    def walk(o):
        if isinstance(o, dict):
            if o.get("publishedAt") and o.get("title") and isinstance(o.get("action"), dict):
                found.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(json.loads(m.group(1)))
    items = []
    for o in found:
        url = ((o.get("action") or {}).get("payload") or {}).get("url") or ""
        if not url:
            continue
        url = SITE + url if url.startswith("/") else url
        key = ((o.get("analytics") or {}).get("contentId")) or url
        if key in seen:
            continue
        seen.add(key)
        desc = o.get("description")
        if isinstance(desc, dict):
            desc = desc.get("body", "")
        desc = re.sub(r"<[^>]+>", "", desc or "").strip()
        cat = o.get("category") or {}
        items.append({
            "id": key, "title": o["title"].strip(), "url": url, "desc": desc,
            "image": ((o.get("media") or o.get("imageMedia") or {}).get("url")),
            "category": cat.get("title") or "Notícias", "cat_key": cat.get("machineName") or "",
            "published": o["publishedAt"],
        })
    items.sort(key=lambda i: i["published"], reverse=True)
    return items


def news_embed(item) -> discord.Embed:
    e = discord.Embed(title=item["title"][:256], url=item["url"], description=item["desc"][:350] or None, color=COLOR)
    e.set_author(name=f"{CATEGORY_EMOJI.get(item['cat_key'], '📰')} {item['category']}")
    if item["image"]:
        e.set_image(url=item["image"])
    e.set_footer(text="League of Legends • Notícia oficial")
    try:
        e.timestamp = datetime.fromisoformat(item["published"].replace("Z", "+00:00"))
    except ValueError:
        pass
    return e


class Noticias(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.feed.start()

    async def cog_unload(self):
        self.feed.cancel()

    async def fetch(self) -> list[dict]:
        async with self.bot.session.get(NEWS_PAGE, headers=UA, timeout=aiohttp.ClientTimeout(total=20)) as r:
            if r.status != 200:
                log.warning("Página de notícias respondeu %s", r.status)
                return []
            return parse_news(await r.text())

    @tasks.loop(minutes=20)
    async def feed(self):
        try:
            items = await self.fetch()
        except Exception:
            log.exception("Falha ao ler as notícias")
            return
        if not items:
            return
        rows = await self.bot.db.fetchall("SELECT DISTINCT guild_id FROM guild_config WHERE key IN ('canal:lolnews', "
                                          "'canal:patch')")
        for row in rows:
            try:
                await self.post_for_guild(row["guild_id"], items)
            except Exception:
                log.exception("Falha ao postar notícias no servidor %s", row["guild_id"])

    @feed.before_loop
    async def before_feed(self):
        await self.bot.wait_until_ready()

    async def post_for_guild(self, guild_id: int, items: list[dict]):
        db = self.bot.db
        news_ch = self.bot.get_channel(int(v)) if (v := await db.get_config(guild_id, "canal:lolnews")) else None
        patch_ch = self.bot.get_channel(int(v)) if (v := await db.get_config(guild_id, "canal:patch")) else None
        raw = await db.get_config(guild_id, "news_seen")
        seen = set(json.loads(raw)) if raw else None
        if seen is None:  # primeira vez: só as mais recentes de cada tipo
            new = [i for i in items if not is_patch_notes(i)][:FIRST_RUN_POSTS] + \
                  [i for i in items if is_patch_notes(i)][:1]
            seen = set()
        else:
            new = [i for i in items if i["id"] not in seen][:MAX_PER_TICK]
        for item in sorted(new, key=lambda i: i["published"]):  # mais antiga primeiro
            channel = (patch_ch or news_ch) if is_patch_notes(item) else (news_ch or patch_ch)
            if channel:
                await channel.send(embed=news_embed(item))
        all_ids = [i["id"] for i in items]
        keep = list(dict.fromkeys(all_ids + list(seen)))[:400]
        await db.set_config(guild_id, "news_seen", json.dumps(keep))


async def setup(bot):
    await bot.add_cog(Noticias(bot))
