"""Card de perfil no estilo "Welcome to Hell": fogo, brasas, neon roxo e as últimas 5 partidas."""
import asyncio
import io
import random
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core.cards import TIER_COLOR, circle, cover, fit_box, fit_text, font, k, rounded, tier_label

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
NEON = (190, 80, 255)
NEON_SOFT = (150, 60, 220)
FIRE = (255, 90, 30)
EMBER = (255, 150, 60)
WHITE = (245, 240, 250)
MUTED = (175, 160, 190)
WIN = (80, 230, 140)
LOSS = (255, 70, 90)
QUEUE_SHORT = {420: "Solo/Duo", 440: "Flex", 400: "Normal", 430: "Normal", 490: "Rápida", 450: "ARAM",
               1700: "Arena", 1900: "URF", 0: "Custom"}

_deco: dict = {}


def deco(name: str, size: int) -> ImageFont.FreeTypeFont:
    key = (name, size)
    if key not in _deco:
        _deco[key] = ImageFont.truetype(str(FONTS / name), size)
    return _deco[key]


# Fontes do card: NAME = nome e elo (pincel seco); TITLE = frases e títulos (tinta escorrendo);
# PUNCH = "AMASSOU / FOI AMASSADO" (forte e legível)
STYLE = {"NAME": "RockSalt-Regular.ttf", "TITLE": "RubikWetPaint-Regular.ttf", "PUNCH": "Bangers-Regular.ttf",
         "NAME_SCALE": 0.75, "TITLE_SCALE": 0.85}


def marker(size):
    return deco(STYLE["NAME"], int(size * STYLE["NAME_SCALE"]))


def creepy(size):
    return deco(STYLE["TITLE"], int(size * STYLE["TITLE_SCALE"]))


def punch(size):
    return deco(STYLE["PUNCH"], size)


# ------------------------------------------------------------------ efeitos
def glow_layer(size, draw_fn, blur: int, strength: int = 1) -> Image.Image:
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(layer))
    g = layer.filter(ImageFilter.GaussianBlur(blur))
    for _ in range(strength - 1):
        g = Image.alpha_composite(g, g)
    return g


def glow_text(base, xy, s, f, fill, glow, blur=10, strength=2, anchor="la", stroke=0):
    base.alpha_composite(glow_layer(base.size, lambda d: d.text(xy, s, font=f, fill=glow + (255,), anchor=anchor,
                                                                stroke_width=stroke + 3,
                                                                stroke_fill=glow + (255,)), blur, strength))
    d = ImageDraw.Draw(base)
    d.text(xy, s, font=f, fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=(20, 0, 30))


def radial(size, center, radius, color, alpha) -> Image.Image:
    w, h = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse((center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius),
                                  fill=color + (alpha,))
    return layer.filter(ImageFilter.GaussianBlur(radius // 2))


def embers(size, n=140, seed=7) -> Image.Image:
    rnd = random.Random(seed)
    w, h = size
    soft = Image.new("RGBA", size, (0, 0, 0, 0))
    sharp = Image.new("RGBA", size, (0, 0, 0, 0))
    ds, dh = ImageDraw.Draw(soft), ImageDraw.Draw(sharp)
    for _ in range(n):
        x = rnd.uniform(0, w)
        y = h - abs(rnd.gauss(0, h * 0.45)) % h  # mais brasas perto do chão
        r = rnd.choice([1, 1, 1.5, 2, 2.5, 3])
        col = rnd.choice([EMBER, FIRE, (255, 200, 90), NEON])
        a = rnd.randint(120, 255)
        ds.ellipse((x - r * 3, y - r * 3, x + r * 3, y + r * 3), fill=col + (a // 2,))
        dh.ellipse((x - r, y - r, x + r, y + r), fill=col + (a,))
    out = soft.filter(ImageFilter.GaussianBlur(4))
    out.alpha_composite(sharp)
    return out


def vignette(size, strength=230) -> Image.Image:
    w, h = size
    mask = Image.new("L", (w, h), strength)
    ImageDraw.Draw(mask).ellipse((-w * 0.15, -h * 0.25, w * 1.15, h * 1.25), fill=0)
    mask = mask.filter(ImageFilter.GaussianBlur(min(w, h) // 6))
    layer = Image.new("RGBA", size, (5, 0, 10, 0))
    layer.putalpha(mask)
    return layer


def tint(img: Image.Image, color, amount: float) -> Image.Image:
    over = Image.new("RGBA", img.size, color + (255,))
    return Image.blend(img.convert("RGBA"), over, amount)


def ago(ms: int) -> str:
    sec = max(time.time() - ms / 1000, 0)
    if sec < 3600:
        return f"há {int(sec // 60)} min"
    if sec < 86400:
        return f"há {int(sec // 3600)}h"
    return f"há {int(sec // 86400)}d"


def mood(wins: int, total: int) -> str:
    if not total:
        return "SEM PARTIDAS RECENTES"
    if wins >= 4:
        return "WELCOME TO HELL"
    if wins == 3:
        return "ESQUENTANDO O RIFT"
    if wins == 2:
        return "NO LIMITE DO TILT"
    return "MODO TILT ATIVADO"


# ------------------------------------------------------------------ card
async def profile_hell(cards, game_name: str, tag: str, level: int, icon_id: int, entries: list,
                       masteries: list, matches: list[dict], puuid: str):
    """matches: lista de respostas do match-v5 (até 5)."""
    dd = cards.dd
    solo = next((e for e in entries if e["queueType"] == "RANKED_SOLO_5x5"), None)
    flex = next((e for e in entries if e["queueType"] == "RANKED_FLEX_SR"), None)
    main = solo or flex
    top_ids = [cards.champ_id(m["championId"]) for m in masteries[:3]]
    games = []
    for m in matches:
        info = m["info"]
        p = next((x for x in info["participants"] if x["puuid"] == puuid), None)
        if p:
            games.append((p, info))
    splash_id = top_ids[0] if top_ids and top_ids[0] else (cards.champ_id(games[0][0]["championId"]) if games else None)
    urls = [dd.profile_icon(icon_id), dd.splash(splash_id) if splash_id else None,
            cards.emblem_url(main and main["tier"]), cards.emblem_url(flex and flex["tier"]) if solo else None]
    urls += [dd.champ_icon(c) if c else None for c in top_ids]
    urls += [dd.champ_icon(cards.champ_id(p["championId"])) for p, _ in games]
    images = await cards.imgs(urls)
    return await asyncio.to_thread(_render, dd, game_name, tag, level, solo, flex, masteries, games, images,
                                   len(top_ids))


def _render(dd, game_name, tag, level, solo, flex, masteries, games, images, n_top):
    W, H = 1200, 700
    icon, splash, em_main, em_flex = images[:4]
    mast_imgs = images[4:4 + n_top]
    game_imgs = images[4 + n_top:]
    main = solo or flex

    # ---------- fundo infernal
    base = Image.new("RGBA", (W, H), (12, 2, 16, 255))
    if splash:
        bg = cover(splash.convert("RGBA"), W, H, 0.2).filter(ImageFilter.GaussianBlur(1.5))
        bg = tint(bg, (40, 0, 30), 0.55)
        base.alpha_composite(bg)
    # chão em chamas: faixa vermelha subindo + focos de fogo laranja
    fire_band = Image.new("L", (1, H))
    fire_band.putdata([int(max(0, (y - H * 0.45) / (H * 0.55)) ** 1.6 * 200) for y in range(H)])
    band = Image.new("RGBA", (W, H), (190, 20, 10, 0))
    band.putalpha(fire_band.resize((W, H)))
    base.alpha_composite(band)
    base.alpha_composite(radial((W, H), (W // 2, H + 100), 560, FIRE, 200))
    base.alpha_composite(radial((W, H), (160, H + 40), 320, (230, 40, 15), 190))
    base.alpha_composite(radial((W, H), (W - 160, H + 60), 340, (240, 70, 20), 180))
    base.alpha_composite(radial((W, H), (W // 2, H - 40), 200, (255, 170, 60), 120))
    base.alpha_composite(radial((W, H), (300, 300), 260, NEON_SOFT, 80))
    base.alpha_composite(vignette((W, H)))
    base.alpha_composite(embers((W, H), n=260))

    # ---------- moldura neon
    frame = (14, 14, W - 14, H - 14)
    base.alpha_composite(glow_layer((W, H), lambda d: d.rounded_rectangle(frame, 28, outline=NEON + (255,), width=8),
                                    12, 2))
    ImageDraw.Draw(base).rounded_rectangle(frame, 28, outline=(230, 190, 255, 255), width=2)

    # ---------- ícone + nível + nome
    if icon:
        base.alpha_composite(glow_layer((W, H), lambda d: d.ellipse((44, 50, 176, 182), fill=NEON + (255,)), 14, 2))
        base.alpha_composite(circle(icon, 120), (50, 56))
    # coroa neon em cima do ícone
    crown = [(78, 40), (84, 14), (97, 30), (110, 8), (123, 30), (136, 14), (142, 40)]
    base.alpha_composite(glow_layer((W, H), lambda d: d.line(crown + [crown[0]], fill=NEON + (255,), width=6,
                                                             joint="curve"), 8, 2))
    d = ImageDraw.Draw(base)
    d.line(crown + [crown[0]], fill=(240, 210, 255), width=3, joint="curve")
    d.ellipse((47, 53, 173, 179), outline=(235, 200, 255), width=3)
    lvl = str(level)
    lw = font(18).getlength(lvl) + 28
    d.rounded_rectangle((110 - lw / 2, 164, 110 + lw / 2, 192), 14, fill=(25, 5, 35), outline=NEON, width=2)
    d.text((110, 178), lvl, font=font(18), fill=WHITE, anchor="mm")

    name_f = marker(72)
    name = fit_text(game_name, name_f, 560)
    glow_text(base, (200, 30), name, name_f, WHITE, NEON, blur=12, strength=2)
    tag_x = 200 + name_f.getlength(name) + 14
    glow_text(base, (tag_x, 78), f"#{tag}", marker(30), (215, 170, 255), NEON_SOFT, blur=6)

    wins5 = sum(1 for p, _ in games if p["win"])
    glow_text(base, (204, 128), mood(wins5, len(games)), creepy(44), (200, 110, 255), (120, 0, 200), blur=8,
              strength=2)

    # ---------- elo (coluna esquerda)
    if em_main:
        e = fit_box(em_main, 230, 200)
        cx, cy = 180, 330
        base.alpha_composite(radial((W, H), (cx, cy), 120, TIER_COLOR.get(main["tier"], NEON), 120))
        base.alpha_composite(e, (cx - e.width // 2, cy - e.height // 2))
    d = ImageDraw.Draw(base)
    if main:
        col = TIER_COLOR.get(main["tier"], WHITE)
        label = "SOLO/DUO" if solo else "FLEX"
        d.text((180, 440), label, font=font(15, "Bold"), fill=MUTED, anchor="mm")
        glow_text(base, (180, 476), tier_label(main["tier"], main["rank"]), marker(34), col,
                  tuple(c // 2 for c in col), blur=6, strength=1, anchor="mm")
        d = ImageDraw.Draw(base)
        w, l = main["wins"], main["losses"]
        wr = w / max(w + l, 1)
        d.text((180, 512), f"{main['leaguePoints']} PDL  ·  {w}V {l}D  ·  {wr * 100:.0f}%", font=font(16, "SemiBold"),
               fill=WHITE, anchor="mm")
        if solo and flex:
            if em_flex:
                ef = fit_box(em_flex, 38, 32)
                base.alpha_composite(ef, (78 - ef.width // 2, 548 - ef.height // 2))
            d = ImageDraw.Draw(base)
            d.text((104, 548), f"FLEX  {tier_label(flex['tier'], flex['rank'])}  ·  {flex['leaguePoints']} PDL",
                   font=font(14, "Bold"), fill=TIER_COLOR.get(flex["tier"], MUTED), anchor="lm")
    else:
        glow_text(base, (180, 330), "SEM RANK", marker(40), MUTED, NEON_SOFT, blur=8, anchor="mm")

    # ---------- últimas 5 partidas (estilo kill feed)
    x0, y0, rw, rh = 380, 190, 790, 66
    glow_text(base, (x0, y0 - 6), "ÚLTIMAS 5 PARTIDAS", creepy(30), WHITE, NEON, blur=6)
    if not games:
        d = ImageDraw.Draw(base)
        d.text((x0, y0 + 50), "Nenhuma partida encontrada.", font=font(18, "SemiBold"), fill=MUTED)
    for i, ((p, info), im) in enumerate(zip(games, game_imgs)):
        y = y0 + 40 + i * (rh + 10)
        win = p["win"]
        col = WIN if win else LOSS
        row = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        rd = ImageDraw.Draw(row)
        rd.rounded_rectangle((x0, y, x0 + rw, y + rh), 10, fill=(8, 0, 14, 200), outline=(120, 50, 170, 160), width=1)
        rd.rounded_rectangle((x0, y, x0 + 6, y + rh), 3, fill=col + (255,))
        base.alpha_composite(row)
        if im:
            base.alpha_composite(rounded(im, 50, 50, 8), (x0 + 16, y + 8))
        d = ImageDraw.Draw(base)
        champ = dd.by_key.get(p["championId"])
        cname = champ["name"] if champ else p["championName"]
        verb = "AMASSOU" if win else "FOI AMASSADO"
        d.text((x0 + 80, y + 9), verb, font=punch(26), fill=col)
        d.text((x0 + 80 + punch(26).getlength(verb) + 10, y + 13), f"de {cname}", font=font(18, "Bold"), fill=WHITE)
        minutes = max(info["gameDuration"] / 60, 1)
        cs = p["totalMinionsKilled"] + p["neutralMinionsKilled"]
        sub = (f"{QUEUE_SHORT.get(info['queueId'], 'Partida')}  ·  {int(minutes)} min  ·  "
               f"{cs / minutes:.1f} CS/min  ·  {ago(info.get('gameEndTimestamp', 0))}")
        d.text((x0 + 80, y + 42), sub, font=font(14, "Medium"), fill=MUTED)
        kda = (p["kills"] + p["assists"]) / max(p["deaths"], 1)
        d.text((x0 + rw - 20, y + 12), f"{p['kills']} / {p['deaths']} / {p['assists']}", font=font(24, "ExtraBold"),
               fill=WHITE, anchor="ra")
        d.text((x0 + rw - 20, y + 42), f"{kda:.2f} KDA", font=font(14, "Bold"),
               fill=(255, 200, 90) if kda >= 3 else MUTED, anchor="ra")

    # ---------- barra de baixo (resumo + mais jogados)
    by = H - 98
    bar = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(bar).rounded_rectangle((40, by, W - 40, by + 62), 14, fill=(5, 0, 10, 215),
                                          outline=(150, 70, 210, 200), width=2)
    base.alpha_composite(bar)
    d = ImageDraw.Draw(base)
    if games:
        k_ = sum(p["kills"] for p, _ in games)
        de = sum(p["deaths"] for p, _ in games)
        a = sum(p["assists"] for p, _ in games)
        dmg = sum(p["totalDamageDealtToChampions"] for p, _ in games) / len(games)
        stats = [(f"{wins5}V {len(games) - wins5}D", WIN if wins5 >= len(games) / 2 else LOSS),
                 (f"KDA {(k_ + a) / max(de, 1):.2f}", WHITE),
                 (f"{k_}/{de}/{a}", WHITE),
                 (f"{k(int(dmg))} dano/jogo", WHITE)]
        x = 64
        for j, (s, c) in enumerate(stats):
            d.text((x, by + 31), s, font=font(20, "ExtraBold"), fill=c, anchor="lm")
            x += font(20, "ExtraBold").getlength(s) + 22
            if j < len(stats) - 1:
                d.text((x - 11, by + 31), "|", font=font(20, "Bold"), fill=(130, 70, 180), anchor="mm")
                x += 6
    # mais jogados (ícones à direita)
    mx = W - 64
    for m, im in reversed(list(zip(masteries[:3], mast_imgs))):
        if im:
            mx -= 46
            base.alpha_composite(circle(im, 44), (mx, by + 9))
            ImageDraw.Draw(base).ellipse((mx - 2, by + 7, mx + 46, by + 55), outline=NEON, width=2)
            mx -= 8
    d = ImageDraw.Draw(base)
    if masteries:
        d.text((mx - 6, by + 31), "MAIS JOGADOS", font=font(13, "Bold"), fill=MUTED, anchor="rm")
    # JPG de alta qualidade: ~4x menor que PNG nesse visual cheio de efeitos (economiza dados da hospedagem)
    buf = io.BytesIO()
    base.convert("RGB").save(buf, "JPEG", quality=92, subsampling=0, optimize=True)
    buf.seek(0)
    return buf
