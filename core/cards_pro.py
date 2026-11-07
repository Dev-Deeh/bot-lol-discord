"""Card de perfil estilo transmissão de esports: limpo, alinhado em grade, tipografia condensada.

Fontes: Bebas Neue (títulos e números) + Barlow Condensed (rótulos e textos)."""
import asyncio
import io
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core.cards import TIER_COLOR, cover, fit_box, rounded
from core.util import TIER_PT, TIERS

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
W, H = 1200, 675
M = 64  # margem

THEMES = {
    "inferno": {"bg": (11, 7, 16), "accent": (178, 92, 255), "accent2": (235, 70, 80), "text": (244, 240, 248),
                "muted": (150, 140, 165), "line": (255, 255, 255, 28)},
    "hextech": {"bg": (1, 10, 19), "accent": (200, 170, 110), "accent2": (10, 200, 185), "text": (240, 230, 210),
                "muted": (140, 150, 150), "line": (200, 170, 110, 45)},
}
WIN = (64, 214, 140)
LOSS = (240, 74, 92)

# ================================================================== dados
def favorite(games):
    """Campeão mais jogado (lista mais recente primeiro). Empate: o mais recente."""
    if not games:
        return None, 0
    counts = Counter(p["championId"] for p, _ in games)
    first = {}
    for i, (p, _) in enumerate(games):
        first.setdefault(p["championId"], i)
    key = max(counts, key=lambda c: (counts[c], -first[c]))
    return key, counts[key]


async def load(cards, icon_id, entries, matches, puuid):
    """matches: até 10 partidas (mais recente primeiro). Mostra as 5 últimas; o fundo usa as 10."""
    dd = cards.dd
    all_games = []
    for m in matches:
        p = next((x for x in m["info"]["participants"] if x["puuid"] == puuid), None)
        if p:
            all_games.append((p, m["info"]))
    games = all_games[:5]
    fav_key, fav_n = favorite(all_games)
    fav = dd.by_key.get(fav_key) if fav_key else None
    solo = next((e for e in entries if e["queueType"] == "RANKED_SOLO_5x5"), None)
    flex = next((e for e in entries if e["queueType"] == "RANKED_FLEX_SR"), None)
    main = solo or flex
    urls = [dd.profile_icon(icon_id), dd.splash(fav["id"]) if fav else None, cards.emblem_url(main and main["tier"])]
    urls += [dd.champ_icon(cards.champ_id(p["championId"])) for p, _ in games]
    imgs = await cards.imgs(urls)
    return {"games": games, "fav": fav, "fav_n": fav_n, "fav_of": len(all_games), "solo": solo, "flex": flex,
            "main": main, "icon": imgs[0], "splash": imgs[1], "emblem": imgs[2], "game_icons": imgs[3:]}


def summary(games):
    w = sum(1 for p, _ in games if p["win"])
    k = sum(p["kills"] for p, _ in games)
    d = sum(p["deaths"] for p, _ in games)
    a = sum(p["assists"] for p, _ in games)
    return w, len(games) - w, k, d, a, (k + a) / max(d, 1)


def jpg(img):
    """JPG de alta qualidade: bem menor que PNG nesse visual com foto (economiza dados da hospedagem)."""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=92, subsampling=0, optimize=True)
    buf.seek(0)
    return buf


_f: dict = {}


def bebas(size):
    return _load("BebasNeue-Regular.ttf", size)


def barlow(size, weight="SemiBold"):
    return _load(f"BarlowCondensed-{weight}.ttf", size)


def _load(name, size):
    if (name, size) not in _f:
        _f[(name, size)] = ImageFont.truetype(str(FONTS / name), size)
    return _f[(name, size)]


def tracked(d: ImageDraw.ImageDraw, xy, text, f, fill, spacing=2.0, anchor="l"):
    """Texto com espaçamento entre letras (rótulos em caixa alta). anchor: 'l' ou 'r'."""
    width = sum(f.getlength(c) for c in text) + spacing * (len(text) - 1)
    x, y = xy
    if anchor == "r":
        x -= width
    for c in text:
        d.text((x, y), c, font=f, fill=fill)
        x += f.getlength(c) + spacing
    return width


def fit(text, f, max_w):
    if f.getlength(text) <= max_w:
        return text
    while text and f.getlength(text + "…") > max_w:
        text = text[:-1]
    return text + "…"


def translucent(base, draw_fn):
    """Desenha formas semitransparentes numa camada e mistura com o card
    (desenhar direto num RGBA substitui o pixel em vez de misturar)."""
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(layer))
    base.alpha_composite(layer)


def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def tier_name(entry):
    if not entry:
        return "SEM RANK"
    name = TIER_PT.get(entry["tier"], entry["tier"]).upper()
    return name if TIERS.index(entry["tier"]) >= 7 else f"{name} {entry['rank']}"


# ================================================================== desenho
def render_pro(data, game_name, tag, level, theme="inferno"):
    t = THEMES[theme]
    base = Image.new("RGBA", (W, H), t["bg"] + (255,))

    # ---- fundo: campeão à direita, com degradê suave para a área de texto
    if data["splash"]:
        art = cover(data["splash"], 880, H, 0.22)
        base.alpha_composite(art, (W - 880, 0))
    row = Image.new("L", (W, 1))
    row.putdata([int(255 * (1 - smooth((x - 380) / 470))) for x in range(W)])
    shade = Image.new("RGBA", (W, H), t["bg"] + (0,))
    shade.putalpha(row.resize((W, H)))
    base.alpha_composite(shade)
    col = Image.new("L", (1, H))
    col.putdata([int(200 * smooth((y - 430) / 245)) for y in range(H)])
    bottom = Image.new("RGBA", (W, H), t["bg"] + (0,))
    bottom.putalpha(col.resize((W, H)))
    base.alpha_composite(bottom)
    # brilho sutil da cor do tema no canto inferior esquerdo
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((-260, H - 260, 420, H + 300), fill=t["accent"] + (36,))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(120)))

    translucent(base, lambda dl: dl.rectangle((0, 0, W - 1, H - 1), outline=t["line"], width=1))  # borda fina
    d = ImageDraw.Draw(base)
    d.rectangle((0, 0, 5, H), fill=t["accent"])                       # barra de destaque

    # ---- cabeçalho
    d.rectangle((M, 62, M + 26, 64), fill=t["accent"])
    tracked(d, (M + 38, 54), "PERFIL DE INVOCADOR", barlow(16), t["accent"], 3)

    # ---- identidade
    if data["icon"]:
        base.alpha_composite(rounded(data["icon"], 92, 92, 16), (M, 100))
    d = ImageDraw.Draw(base)
    d.rounded_rectangle((M, 100, M + 91, 191), 16, outline=t["accent"], width=2)
    lvl = str(level)
    lw = barlow(16, "Bold").getlength(lvl) + 20
    d.rounded_rectangle((M + 46 - lw / 2, 180, M + 46 + lw / 2, 204), 6, fill=t["bg"], outline=t["accent"], width=1)
    d.text((M + 46, 192), lvl, font=barlow(16, "Bold"), fill=t["text"], anchor="mm")

    name_f = bebas(96)
    name = fit(game_name.upper(), name_f, 620)
    d.text((M + 120, 186), name, font=name_f, fill=t["text"], anchor="ls")
    d.text((M + 120 + name_f.getlength(name) + 12, 184), f"#{tag}", font=barlow(30, "Medium"), fill=t["muted"],
           anchor="ls")

    translucent(base, lambda dl: dl.line((M, 236, 660, 236), fill=t["line"], width=1))

    # ---- elo
    main, solo, flex = data["main"], data["solo"], data["flex"]
    tcol = TIER_COLOR.get(main["tier"], t["text"]) if main else t["muted"]
    if data["emblem"]:
        e = fit_box(data["emblem"], 128, 108)
        base.alpha_composite(e, (M + (128 - e.width) // 2, 262 + (108 - e.height) // 2))
    d = ImageDraw.Draw(base)
    tx = M + 152
    tracked(d, (tx, 262), "RANQUEADA SOLO/DUO" if solo else ("RANQUEADA FLEX" if flex else "RANQUEADA"),
            barlow(15), t["muted"], 2.5)
    tier = tier_name(main)
    d.text((tx, 336), tier, font=bebas(58), fill=tcol, anchor="ls")
    if main:
        d.text((tx + bebas(58).getlength(tier) + 14, 334), f"{main['leaguePoints']} PDL", font=barlow(24),
               fill=t["text"], anchor="ls")
        w_, l_ = main["wins"], main["losses"]
        wr = w_ / max(w_ + l_, 1)
        bx0, by0, bx1 = tx, 352, tx + 320
        translucent(base, lambda dl: dl.rounded_rectangle((bx0, by0, bx1, by0 + 6), 3, fill=(255, 255, 255, 34)))
        d = ImageDraw.Draw(base)
        d.rounded_rectangle((bx0, by0, bx0 + max(int(320 * wr), 6), by0 + 6), 3, fill=WIN if wr >= .5 else LOSS)
        d.text((tx, 372), f"{w_}V  {l_}D", font=barlow(17, "Medium"), fill=t["muted"])
        d.text((bx1, 372), f"{wr * 100:.0f}% DE VITÓRIAS", font=barlow(17), fill=t["text"], anchor="ra")
    if solo and flex:
        fcol = TIER_COLOR.get(flex["tier"], t["muted"])
        x = tracked(d, (tx, 400), "FLEX", barlow(15), t["muted"], 2.5)
        d.text((tx + x + 12, 399), f"{tier_name(flex)}  ·  {flex['leaguePoints']} PDL", font=barlow(17),
               fill=fcol)

    # ---- estatísticas das últimas 5
    w5, l5, k, de, a, kda = summary(data["games"])
    n = w5 + l5
    stats = [("ÚLTIMAS %d" % n if n else "ÚLTIMAS", f"{w5}V {l5}D" if n else "—"),
             ("KDA", f"{kda:.2f}" if n else "—"),
             ("ABATES / MORTES / ASSIST.", f"{k} / {de} / {a}" if n else "—")]
    sx, sy = M, 452
    widths = [150, 120, 260]
    for i, ((label, value), cw) in enumerate(zip(stats, widths)):
        tracked(d, (sx, sy), label, barlow(14), t["muted"], 2)
        color = t["text"]
        if i == 0 and n:
            color = WIN if w5 >= l5 else LOSS
        d.text((sx, sy + 66), value, font=bebas(46), fill=color, anchor="ls")
        sx += cw
        if i < len(stats) - 1:
            translucent(base, lambda dl, x=sx: dl.line((x - 22, sy + 4, x - 22, sy + 62), fill=t["line"], width=1))
            d = ImageDraw.Draw(base)

    # ---- partidas recentes
    gy = 548
    for i, ((p, info), im) in enumerate(zip(data["games"], data["game_icons"])):
        x = M + i * 80
        if im:
            base.alpha_composite(rounded(im, 62, 62, 10), (x, gy))
        d = ImageDraw.Draw(base)
        res = WIN if p["win"] else LOSS
        d.rounded_rectangle((x, gy + 68, x + 61, gy + 72), 2, fill=res)
        d.text((x + 31, gy + 92), f"{p['kills']}/{p['deaths']}/{p['assists']}", font=barlow(16), fill=t["text"],
               anchor="ms")

    # ---- legenda do campeão de fundo
    if data["fav"]:
        d = ImageDraw.Draw(base)
        d.text((W - M, H - 82), data["fav"]["name"].upper(), font=bebas(40), fill=t["text"], anchor="rs")
        n_fav, total = data["fav_n"], data["fav_of"]
        sub = "CAMPEÃO DA ÚLTIMA PARTIDA" if n_fav <= 1 else f"{n_fav} DAS ÚLTIMAS {total} PARTIDAS"
        tracked(d, (W - M, H - 74), sub, barlow(14), t["muted"], 2.5, anchor="r")
    return jpg(base)


async def profile_pro(cards, game_name, tag, level, icon_id, entries, matches, puuid, theme="inferno"):
    data = await load(cards, icon_id, entries, matches, puuid)
    return await asyncio.to_thread(render_pro, data, game_name, tag, level, theme)
