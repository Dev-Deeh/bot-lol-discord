"""Gera os cards em imagem (perfil, partida ao vivo, resumo de partida, ranking e alerta de elo)."""
import asyncio
import io
import logging
from collections import OrderedDict
from pathlib import Path

import aiohttp
from PIL import Image, ImageChops, ImageDraw, ImageFont

from core import util

log = logging.getLogger("bot.cards")

FONT_PATH = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Montserrat.ttf"
EMBLEM_URL = ("https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-static-assets/"
              "global/default/images/ranked-emblem/emblem-{}.png")
UA = {"User-Agent": "bot-lol-discord/1.0"}

# Paleta inspirada no cliente do LoL
BG = (1, 10, 19)
PANEL = (10, 20, 40, 200)
GOLD = (200, 155, 60)
TEXT = (240, 230, 210)
MUTED = (160, 155, 140)
BLUE = (10, 200, 185)
RED = (232, 64, 87)
WIN = (46, 204, 113)
LOSS = (232, 64, 87)
TIER_COLOR = {"IRON": (130, 112, 105), "BRONZE": (176, 110, 72), "SILVER": (160, 178, 190),
              "GOLD": (220, 170, 70), "PLATINUM": (78, 190, 180), "EMERALD": (45, 190, 120),
              "DIAMOND": (110, 140, 240), "MASTER": (175, 90, 220), "GRANDMASTER": (230, 75, 70),
              "CHALLENGER": (245, 205, 120)}


# ================================================================== helpers de desenho
_fonts: dict = {}


def font(size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    key = (size, weight)
    if key not in _fonts:
        f = ImageFont.truetype(str(FONT_PATH), size)
        try:
            f.set_variation_by_name(weight)
        except Exception:
            pass
        _fonts[key] = f
    return _fonts[key]


def tier_color(tier):
    return TIER_COLOR.get(tier, MUTED)


def cover(img: Image.Image, w: int, h: int, focus_y: float = 0.3) -> Image.Image:
    scale = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1), Image.LANCZOS)
    left = (img.width - w) // 2
    top = int((img.height - h) * focus_y)
    return img.crop((left, top, left + w, top + h))


def rounded(img: Image.Image, w: int, h: int, radius: int) -> Image.Image:
    img = img.convert("RGBA").resize((w, h), Image.LANCZOS)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius, fill=255)
    img.putalpha(ImageChops.multiply(img.getchannel("A"), mask))
    return img


def circle(img: Image.Image, d: int) -> Image.Image:
    return rounded(img, d, d, d // 2)


def fit_box(img: Image.Image, w: int, h: int) -> Image.Image:
    img = img.copy()
    img.thumbnail((w, h), Image.LANCZOS)
    return img


def crop_alpha(img: Image.Image) -> Image.Image:
    box = img.getchannel("A").getbbox()
    return img.crop(box) if box else img


def overlay(base: Image.Image, draw_fn):
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(layer))
    base.alpha_composite(layer)


def panel(base: Image.Image, box, radius=18, fill=PANEL, outline=None, width=2):
    overlay(base, lambda d: d.rounded_rectangle(box, radius, fill=fill, outline=outline, width=width))


def h_gradient(w: int, h: int, color, a_left: int, a_right: int) -> Image.Image:
    row = Image.new("L", (w, 1))
    row.putdata([int(a_left + (a_right - a_left) * x / max(w - 1, 1)) for x in range(w)])
    alpha = row.resize((w, h))
    layer = Image.new("RGBA", (w, h), color + (0,))
    layer.putalpha(alpha)
    return layer


def v_gradient(w: int, h: int, color, a_top: int, a_bottom: int) -> Image.Image:
    col = Image.new("L", (1, h))
    col.putdata([int(a_top + (a_bottom - a_top) * y / max(h - 1, 1)) for y in range(h)])
    layer = Image.new("RGBA", (w, h), color + (0,))
    layer.putalpha(col.resize((w, h)))
    return layer


def background(w: int, h: int, splash: Image.Image | None, focus_y=0.3) -> Image.Image:
    base = Image.new("RGBA", (w, h), BG + (255,))
    if splash:
        base.alpha_composite(cover(splash.convert("RGBA"), w, h, focus_y))
        base.alpha_composite(h_gradient(w, h, BG, 245, 150))
        base.alpha_composite(v_gradient(w, h, BG, 40, 200))
    else:
        base.alpha_composite(v_gradient(w, h, (20, 40, 70), 120, 0))
    return base


def fit_text(s: str, f, max_w: int) -> str:
    if f.getlength(s) <= max_w:
        return s
    while s and f.getlength(s + "…") > max_w:
        s = s[:-1]
    return s + "…"


def text(d: ImageDraw.ImageDraw, xy, s: str, f, fill=TEXT, anchor="la", shadow=True):
    if shadow:
        d.text((xy[0] + 2, xy[1] + 2), s, font=f, fill=(0, 0, 0, 170), anchor=anchor)
    d.text(xy, s, font=f, fill=fill, anchor=anchor)


def paste(base: Image.Image, img: Image.Image | None, xy, placeholder_size=None):
    if img is None:
        if placeholder_size:
            overlay(base, lambda d: d.rounded_rectangle(
                (xy[0], xy[1], xy[0] + placeholder_size[0], xy[1] + placeholder_size[1]), 8, fill=(30, 40, 60, 255)))
        return
    base.alpha_composite(img, (int(xy[0]), int(xy[1])))


def bar(base, box, ratio: float, color, bg=(40, 50, 70, 255)):
    x0, y0, x1, y1 = box
    r = (y1 - y0) // 2
    fill_x = x0 + max(int((x1 - x0) * max(min(ratio, 1), 0)), y1 - y0)

    def draw(d):
        d.rounded_rectangle(box, r, fill=bg)
        d.rounded_rectangle((x0, y0, fill_x, y1), r, fill=color + (255,))
    overlay(base, draw)


def to_png(img: Image.Image) -> io.BytesIO:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG", optimize=True)
    buf.seek(0)
    return buf


def k(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}".replace(".", ",") + " mi"
    if n >= 1000:
        return f"{n / 1000:.0f} mil"
    return str(n)


def dots(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def tier_label(tier, rank) -> str:
    if not tier:
        return "SEM RANK"
    name = util.TIER_PT.get(tier, tier).upper()
    return name if util.TIERS.index(tier) >= 7 else f"{name} {rank}"


# ================================================================== gerador
class CardMaker:
    """Baixa e guarda as imagens COMPRIMIDAS (PNG/JPG) num cache limitado em bytes,
    pra caber em hospedagens com pouca memória (ex.: 100 MB)."""

    def __init__(self, session: aiohttp.ClientSession, ddragon, max_cache_bytes=12 * 1024 * 1024):
        self.session = session
        self.dd = ddragon
        self.cache: OrderedDict[str, bytes] = OrderedDict()
        self.cache_bytes = 0
        self.max_cache_bytes = max_cache_bytes

    def _remember(self, url: str, data: bytes):
        self.cache[url] = data
        self.cache_bytes += len(data)
        while self.cache_bytes > self.max_cache_bytes and self.cache:
            _, old = self.cache.popitem(last=False)
            self.cache_bytes -= len(old)

    async def img(self, url: str | None) -> Image.Image | None:
        if not url:
            return None
        data = self.cache.get(url)
        if data is not None:
            self.cache.move_to_end(url)
        else:
            try:
                data = None
                for attempt in range(2):  # muitas imagens ao mesmo tempo às vezes estouram o tempo: tenta de novo
                    try:
                        async with self.session.get(url, headers=UA, timeout=aiohttp.ClientTimeout(total=20)) as r:
                            if r.status != 200:
                                return None
                            data = await r.read()
                        break
                    except asyncio.TimeoutError:
                        if attempt:
                            raise
                if "ranked-emblem" in url:  # emblemas vêm 1280x720 com muita borda: recorta e reduz uma vez
                    im = crop_alpha(Image.open(io.BytesIO(data)).convert("RGBA"))
                    im.thumbnail((240, 240), Image.LANCZOS)
                    buf = io.BytesIO()
                    im.save(buf, "PNG")
                    data = buf.getvalue()
                if "/splash/" not in url:  # splash é grande e varia muito: não vale guardar
                    self._remember(url, data)
            except Exception:
                log.warning("Falha ao baixar imagem %s", url)
                return None
        try:
            return Image.open(io.BytesIO(data)).convert("RGBA")
        except Exception:
            return None

    async def imgs(self, urls):
        return await asyncio.gather(*(self.img(u) for u in urls))

    def emblem_url(self, tier):
        return EMBLEM_URL.format(tier.lower()) if tier else None

    def champ_id(self, key) -> str | None:
        c = self.dd.by_key.get(int(key)) if key else None
        return c["id"] if c else None

    # -------------------------------------------------------------- PERFIL
    async def profile(self, game_name: str, tag: str, level: int, icon_id: int,
                      entries: list, masteries: list) -> io.BytesIO:
        solo = next((e for e in entries if e["queueType"] == "RANKED_SOLO_5x5"), None)
        flex = next((e for e in entries if e["queueType"] == "RANKED_FLEX_SR"), None)
        top_ids = [self.champ_id(m["championId"]) for m in masteries[:3]]
        splash_id = top_ids[0] if top_ids and top_ids[0] else None
        urls = [self.dd.profile_icon(icon_id), self.dd.splash(splash_id) if splash_id else None,
                self.emblem_url(solo and solo["tier"]), self.emblem_url(flex and flex["tier"])]
        urls += [self.dd.champ_icon(c) if c else None for c in top_ids]
        images = await self.imgs(urls)
        return await asyncio.to_thread(self._profile, game_name, tag, level, solo, flex, masteries, top_ids, images)

    def _profile(self, game_name, tag, level, solo, flex, masteries, top_ids, images):
        W, H = 1100, 460
        icon, splash, em_solo, em_flex, *champ_icons = images
        base = background(W, H, splash, 0.25)
        main_tier = (solo or flex or {}).get("tier")
        accent = tier_color(main_tier) if main_tier else GOLD
        d = ImageDraw.Draw(base)

        # ícone + nível
        if icon:
            paste(base, circle(icon, 150), (45, 45))
        d.ellipse((41, 41, 199, 199), outline=accent, width=5)
        lvl = f"{level}"
        lw = font(20).getlength(lvl) + 30
        panel(base, (120 - lw / 2, 182, 120 + lw / 2, 214), 16, fill=BG + (255,), outline=accent)
        d = ImageDraw.Draw(base)
        text(d, (120, 198), lvl, font(20), TEXT, anchor="mm", shadow=False)

        # nome
        name_f = font(46, "ExtraBold")
        name = fit_text(game_name, name_f, 640)
        text(d, (235, 60), name, name_f)
        text(d, (235 + name_f.getlength(name) + 12, 76), f"#{tag}", font(26, "Medium"), MUTED)
        text(d, (237, 122), "PERFIL DE INVOCADOR", font(16, "SemiBold"), GOLD)

        # blocos de ranqueada
        for i, (label, entry, em) in enumerate((("SOLO/DUO", solo, em_solo), ("FLEX", flex, em_flex))):
            x0, y0 = 235 + i * 425, 160
            col = tier_color(entry["tier"]) if entry else MUTED
            panel(base, (x0, y0, x0 + 405, y0 + 150), 18, outline=col + (120,))
            d = ImageDraw.Draw(base)
            if em:
                e = fit_box(em, 120, 110)
                paste(base, e, (x0 + 15 + (120 - e.width) // 2, y0 + 20 + (110 - e.height) // 2))
            tx = x0 + 150
            text(d, (tx, y0 + 18), label, font(15, "SemiBold"), MUTED)
            if entry:
                text(d, (tx, y0 + 40), tier_label(entry["tier"], entry["rank"]), font(28, "ExtraBold"), col)
                text(d, (tx, y0 + 76), f"{entry['leaguePoints']} PDL", font(20, "SemiBold"), TEXT)
                w, l = entry["wins"], entry["losses"]
                wr = w / (w + l) if w + l else 0
                text(d, (tx, y0 + 104), f"{w}V {l}D", font(16, "Medium"), MUTED)
                text(d, (x0 + 390, y0 + 104), f"{wr * 100:.0f}%", font(16, "Bold"),
                     WIN if wr >= 0.5 else LOSS, anchor="ra")
                bar(base, (tx, y0 + 128, x0 + 390, y0 + 136), wr, WIN if wr >= 0.5 else LOSS)
                d = ImageDraw.Draw(base)
            else:
                text(d, (tx, y0 + 55), "SEM RANK", font(28, "ExtraBold"), MUTED)
                text(d, (tx, y0 + 95), "Jogue as MDs!", font(16, "Medium"), MUTED)

        # maestrias
        text(d, (45, 345), "MAIS JOGADOS", font(16, "SemiBold"), GOLD)
        for i, m in enumerate(masteries[:3]):
            x = 45 + i * 345
            ci = champ_icons[i] if i < len(champ_icons) else None
            if ci:
                paste(base, circle(ci, 70), (x, 370))
            d.ellipse((x - 2, 368, x + 72, 442), outline=GOLD, width=2)
            champ = self.dd.by_key.get(m["championId"])
            text(d, (x + 88, 382), champ["name"] if champ else "?", font(22, "Bold"))
            text(d, (x + 88, 412), f"Maestria {m['championLevel']} · {k(m['championPoints'])} pts",
                 font(16, "Medium"), MUTED)
        if not masteries:
            text(d, (45, 385), "Nenhuma maestria ainda", font(20, "Medium"), MUTED)
        return to_png(base)

    # -------------------------------------------------------------- PARTIDA AO VIVO
    async def live(self, game: dict, leagues: list, puuid: str, queue_name: str) -> io.BytesIO:
        parts = game["participants"]
        urls = []
        for p in parts:
            cid = self.champ_id(p["championId"])
            perks = p.get("perks") or {}
            ids = perks.get("perkIds") or [None]
            urls += [self.dd.champ_icon(cid) if cid else None,
                     self.dd.summoner_spell_icons.get(p.get("spell1Id")),
                     self.dd.summoner_spell_icons.get(p.get("spell2Id")),
                     self.dd.rune_icons.get(ids[0]),
                     self.dd.rune_icons.get(perks.get("perkSubStyle"))]
        for e in leagues:
            urls.append(self.emblem_url(e and e["tier"]))
        bans = [b for b in game.get("bannedChampions") or [] if b["championId"] > 0]
        urls += [self.dd.champ_icon(self.champ_id(b["championId"])) for b in bans]
        images = await self.imgs(urls)
        return await asyncio.to_thread(self._live, game, leagues, puuid, queue_name, bans, images)

    def _live(self, game, leagues, puuid, queue_name, bans, images):
        W, H = 1100, 720
        parts = game["participants"]
        n = len(parts)
        per = images[:n * 5]
        emblems = images[n * 5:n * 6]
        ban_imgs = images[n * 6:]
        base = background(W, H, None)
        d = ImageDraw.Draw(base)
        title_f = font(34, "ExtraBold")
        text(d, (40, 36), "PARTIDA AO VIVO", title_f, GOLD)
        dot_x = 40 + title_f.getlength("PARTIDA AO VIVO") + 16
        overlay(base, lambda dd: dd.ellipse((dot_x, 48, dot_x + 16, 64), fill=RED + (255,)))
        d = ImageDraw.Draw(base)
        minutes = max(game.get("gameLength", 0), 0) // 60
        text(d, (W - 40, 46), f"{queue_name}  ·  {minutes} min", font(20, "SemiBold"), MUTED, anchor="ra")

        cols = {100: (30, "TIME AZUL", BLUE), 200: (565, "TIME VERMELHO", RED)}
        rows = {100: 0, 200: 0}
        for x, label, col in cols.values():
            overlay(base, lambda dd, x=x, col=col: dd.rounded_rectangle((x, 100, x + 505, 106), 3, fill=col + (255,)))
            d = ImageDraw.Draw(base)
            text(d, (x, 118), label, font(18, "ExtraBold"), col)

        for i, p in enumerate(parts):
            team = p["teamId"] if p["teamId"] in cols else 100
            x, _, col = cols[team]
            y = 150 + rows[team] * 96
            rows[team] += 1
            me = p.get("puuid") == puuid
            panel(base, (x, y, x + 505, y + 84), 14, fill=(14, 26, 48, 230),
                  outline=(GOLD + (255,)) if me else None, width=3 if me else 2)
            champ_img, s1, s2, key, sub = per[i * 5:i * 5 + 5]
            paste(base, rounded(champ_img, 64, 64, 12) if champ_img else None, (x + 10, y + 10), (64, 64))
            for j, s in enumerate((s1, s2)):
                paste(base, rounded(s, 30, 30, 6) if s else None, (x + 80, y + 10 + j * 34), (30, 30))
            if key:
                paste(base, fit_box(key, 32, 32), (x + 116, y + 9))
            if sub:
                paste(base, fit_box(sub, 22, 22), (x + 121, y + 50))
            d = ImageDraw.Draw(base)
            champ = self.dd.by_key.get(p["championId"])
            name = (p.get("riotId") or "Jogador oculto").split("#")[0]
            text(d, (x + 160, y + 16), fit_text(name, font(20, "Bold"), 200), font(20, "Bold"), GOLD if me else TEXT)
            text(d, (x + 160, y + 46), champ["name"] if champ else "?", font(16, "Medium"), MUTED)
            e = leagues[i]
            em = emblems[i]
            if em:
                emi = fit_box(em, 46, 40)
                paste(base, emi, (x + 385 - emi.width // 2, y + 6 + (40 - emi.height) // 2))
            d = ImageDraw.Draw(base)
            label = tier_label(e["tier"], e["rank"]) if e else "SEM RANK"
            text(d, (x + 385, y + 50), label, font(13, "Bold"), tier_color(e["tier"]) if e else MUTED, anchor="ma")
            if e:
                wr = e["wins"] / max(e["wins"] + e["losses"], 1)
                text(d, (x + 495, y + 18), f"{e['leaguePoints']} PDL", font(14, "SemiBold"), TEXT, anchor="ra")
                text(d, (x + 495, y + 46), f"{wr * 100:.0f}%", font(14, "Bold"), WIN if wr >= .5 else LOSS, anchor="ra")

        # bans
        text(d, (40, 642), "BANS", font(15, "SemiBold"), MUTED)
        bx = {100: 110, 200: 645}
        for b, im in zip(bans, ban_imgs):
            team = b["teamId"] if b["teamId"] in bx else 100
            if im:
                g = rounded(im, 40, 40, 8).convert("LA").convert("RGBA")
                paste(base, g, (bx[team], 630))
            bx[team] += 46
        return to_png(base)

    # -------------------------------------------------------------- RESUMO DE PARTIDA
    async def match(self, p: dict, info: dict, riot_name: str, queue_name: str) -> io.BytesIO:
        cid = self.champ_id(p["championId"])
        items = [p.get(f"item{i}") for i in range(7)]
        urls = [self.dd.splash(cid) if cid else None, self.dd.champ_icon(cid) if cid else None]
        urls += [self.dd.item_icon(i) if i else None for i in items]
        images = await self.imgs(urls)
        return await asyncio.to_thread(self._match, p, info, riot_name, queue_name, images)

    def _match(self, p, info, riot_name, queue_name, images):
        W, H = 1100, 380
        splash, icon, *items = images
        win = p["win"]
        col = WIN if win else LOSS
        base = background(W, H, splash, 0.2)
        overlay(base, lambda d: d.rectangle((0, 0, 8, H), fill=col + (255,)))
        d = ImageDraw.Draw(base)
        if icon:
            paste(base, rounded(icon, 120, 120, 18), (45, 45))
        d.rounded_rectangle((41, 41, 169, 169), 20, outline=col, width=4)
        text(d, (195, 40), "VITÓRIA" if win else "DERROTA", font(52, "Black"), col)
        champ = self.dd.by_key.get(p["championId"])
        minutes = max(info["gameDuration"] / 60, 1)
        text(d, (198, 108), f"{champ['name'] if champ else p['championName']}  ·  {riot_name}",
             font(22, "Bold"), TEXT)
        text(d, (198, 142), f"{queue_name}  ·  {int(minutes)} min", font(18, "Medium"), MUTED)

        # itens
        for i in range(7):
            x = W - 45 - (7 - i) * 54
            im = items[i] if i < len(items) else None
            paste(base, rounded(im, 48, 48, 8) if im else None, (x, 48), (48, 48))

        # KDA
        kda = (p["kills"] + p["assists"]) / max(p["deaths"], 1)
        kda_txt = f"{p['kills']} / {p['deaths']} / {p['assists']}"
        d = ImageDraw.Draw(base)
        text(d, (45, 200), kda_txt, font(54, "ExtraBold"), TEXT)
        text(d, (45 + font(54, "ExtraBold").getlength(kda_txt) + 18, 225), f"{kda:.2f} KDA",
             font(22, "Bold"), GOLD if kda >= 3 else MUTED)
        multi = ("PENTAKILL" if p.get("pentaKills") else "QUADRAKILL" if p.get("quadraKills")
                 else "TRIPLE KILL" if p.get("tripleKills") else None)
        if multi:
            mw = font(22, "Black").getlength(multi) + 36
            panel(base, (W - 45 - mw, 200, W - 45, 244), 22, fill=GOLD + (255,))
            d = ImageDraw.Draw(base)
            text(d, (W - 45 - mw / 2, 222), multi, font(22, "Black"), BG, anchor="mm", shadow=False)

        # estatísticas
        cs = p["totalMinionsKilled"] + p["neutralMinionsKilled"]
        stats = [("DANO", dots(p["totalDamageDealtToChampions"])), ("CS", f"{cs} ({cs / minutes:.1f}/min)"),
                 ("OURO", dots(p["goldEarned"])), ("VISÃO", str(p.get("visionScore", 0))),
                 ("KP", f"{self._kp(p, info)}%")]
        bw = (W - 90 - 4 * 14) / 5
        for i, (label, value) in enumerate(stats):
            x = 45 + i * (bw + 14)
            panel(base, (x, 285, x + bw, 345), 12)
            d = ImageDraw.Draw(base)
            text(d, (x + 14, 293), label, font(13, "SemiBold"), MUTED, shadow=False)
            text(d, (x + 14, 313), value, font(20, "Bold"), TEXT, shadow=False)
        return to_png(base)

    @staticmethod
    def _kp(p, info) -> int:
        team_kills = sum(x["kills"] for x in info["participants"] if x["teamId"] == p["teamId"])
        return round((p["kills"] + p["assists"]) / team_kills * 100) if team_kills else 0

    # -------------------------------------------------------------- RANKING
    async def ranking(self, rows: list) -> io.BytesIO:
        images = await self.imgs([self.emblem_url(r["tier"]) for r in rows])
        return await asyncio.to_thread(self._ranking, rows, images)

    def _ranking(self, rows, images):
        W = 1000
        H = 130 + len(rows) * 74 + 20
        base = background(W, H, None)
        d = ImageDraw.Draw(base)
        text(d, (40, 38), "RANKING DO SERVIDOR", font(34, "ExtraBold"), GOLD)
        text(d, (W - 40, 50), "SOLO/DUO", font(18, "SemiBold"), MUTED, anchor="ra")
        medal = {0: (245, 205, 120), 1: (200, 210, 220), 2: (205, 130, 80)}
        for i, (r, em) in enumerate(zip(rows, images)):
            y = 110 + i * 74
            panel(base, (30, y, W - 30, y + 64), 14, fill=(14, 26, 48, 230),
                  outline=(medal[i] + (200,)) if i in medal else None)
            d = ImageDraw.Draw(base)
            text(d, (75, y + 32), str(i + 1), font(26, "Black"), medal.get(i, MUTED), anchor="mm")
            if em:
                e = fit_box(em, 60, 52)
                paste(base, e, (140 - e.width // 2, y + 32 - e.height // 2))
            d = ImageDraw.Draw(base)
            text(d, (190, y + 12), fit_text(r["name"], font(22, "Bold"), 330), font(22, "Bold"))
            text(d, (190, y + 40), tier_label(r["tier"], r["rank"]) + (f" · {r['lp']} PDL" if r["tier"] else ""),
                 font(15, "Bold"), tier_color(r["tier"]) if r["tier"] else MUTED)
            w, l = r["wins"] or 0, r["losses"] or 0
            if w + l:
                wr = w / (w + l)
                text(d, (W - 60, y + 14), f"{wr * 100:.0f}%", font(22, "ExtraBold"), WIN if wr >= .5 else LOSS,
                     anchor="ra")
                text(d, (W - 60, y + 42), f"{w}V {l}D", font(14, "Medium"), MUTED, anchor="ra")
                bar(base, (600, y + 28, 800, y + 36), wr, WIN if wr >= .5 else LOSS)
                d = ImageDraw.Draw(base)
        return to_png(base)

    # -------------------------------------------------------------- ALERTA DE ELO
    async def rank_change(self, name: str, tier: str, rank: str, lp: int, kind: str) -> io.BytesIO:
        em, = await self.imgs([self.emblem_url(tier)])
        return await asyncio.to_thread(self._rank_change, name, tier, rank, lp, kind, em)

    def _rank_change(self, name, tier, rank, lp, kind, em):
        W, H = 900, 260
        col = tier_color(tier)
        base = background(W, H, None)
        base.alpha_composite(h_gradient(W, H, col, 0, 70))
        if em:
            e = fit_box(em, 220, 200)
            paste(base, e, (W - 150 - e.width // 2, H // 2 - e.height // 2))
        d = ImageDraw.Draw(base)
        title = {"up": "SUBIU PARA", "down": "CAIU PARA", "placed": "TERMINOU AS MDS EM"}[kind]
        tcol = {"up": WIN, "down": LOSS, "placed": GOLD}[kind]
        text(d, (45, 45), fit_text(name, font(30, "Bold"), 560), font(30, "Bold"))
        text(d, (45, 95), title, font(20, "SemiBold"), tcol)
        text(d, (45, 125), tier_label(tier, rank), font(54, "Black"), col)
        text(d, (48, 195), f"{lp} PDL", font(22, "SemiBold"), TEXT)
        return to_png(base)
