"""Card do /scout: uma linha por jogador (rota, elo, forma, números e campeões) + bans + leitura do time."""
import asyncio

from PIL import Image, ImageDraw, ImageFilter

from core.cards import TIER_COLOR, fit_box, rounded
from core.cards_pro import barlow, bebas, fit, jpg, tracked
from core.util import TIER_PT, TIERS

W = 1200
M = 48
BG = (11, 7, 16)
PANEL = (255, 255, 255, 10)
LINE = (255, 255, 255, 24)
TEXT = (244, 240, 248)
MUTED = (150, 140, 165)
ACCENT = (232, 64, 87)       # vermelho: scout/adversário
WIN = (64, 214, 140)
LOSS = (240, 74, 92)
ROW_H = 150
GAP = 12
ICON = 56
LANE_SHORT = {"TOP": "TOP", "JUNGLE": "JG", "MIDDLE": "MID", "BOTTOM": "ADC", "UTILITY": "SUP"}


def tier_name(e):
    if not e:
        return "SEM ELO"
    n = TIER_PT.get(e["tier"], e["tier"]).upper()
    return n if TIERS.index(e["tier"]) >= 7 else f"{n} {e['rank']}"


def layer_rect(base, box, radius, fill=None, outline=None, width=1):
    lay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(lay).rounded_rectangle(box, radius, fill=fill, outline=outline, width=width)
    base.alpha_composite(lay)


def wrap(text, f, max_w):
    lines, cur = [], ""
    for w in text.split():
        t = f"{cur} {w}".strip()
        if f.getlength(t) <= max_w:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


async def render_scout(cards, players: list[dict], must: list[dict], extra: list[dict], recent: int,
                       notes: list[tuple[str, str]] | None = None):
    dd = cards.dd
    icon = lambda cid: dd.champ_icon(dd.by_key[cid]["id"]) if cid in dd.by_key else None  # noqa: E731
    urls = []
    for pl in players:
        if pl.get("error"):
            continue
        urls.append(cards.emblem_url(pl["solo"]["tier"]) if pl.get("solo") else None)
        pl["_top"] = sorted(pl["champs"].items(), key=lambda kv: (-kv[1]["games"], -kv[1]["wins"]))[:3]
        urls += [icon(cid) for cid, _ in pl["_top"]]
    urls += [icon(c["id"]) for c in must]
    imgs = iter(await cards.imgs(urls))
    for pl in players:
        if pl.get("error"):
            continue
        pl["_emblem"] = next(imgs)
        pl["_top_imgs"] = [next(imgs) for _ in pl["_top"]]
    for c in must:
        c["_img"] = next(imgs)
    return await asyncio.to_thread(_render, players, must, extra, recent, notes or [])


def _row(base, pl, y, ban_keys):
    layer_rect(base, (M, y, W - M, y + ROW_H), 16, fill=PANEL, outline=LINE)
    d = ImageDraw.Draw(base)
    if pl.get("error"):
        d.text((M + 28, y + ROW_H / 2), pl["riot_id"], font=bebas(36), fill=MUTED, anchor="lm")
        d.text((W - M - 28, y + ROW_H / 2), pl["error"].upper(), font=barlow(18), fill=LOSS, anchor="rm")
        return
    solo, st = pl.get("solo"), pl.get("stats")

    # rota
    lane = LANE_SHORT.get(pl.get("lane"), "?")
    d.rectangle((M, y + 20, M + 4, y + ROW_H - 20), fill=ACCENT)
    d.text((M + 58, y + 76), lane, font=bebas(44), fill=TEXT, anchor="ms")
    share = pl.get("role_share", 0)
    d.text((M + 58, y + 100), f"{share * 100:.0f}% NA ROTA", font=barlow(12),
           fill=LOSS if pl.get("off_role") else MUTED, anchor="ms")

    # emblema + nick + elo
    if pl["_emblem"]:
        e = fit_box(pl["_emblem"], 78, 70)
        base.alpha_composite(e, (M + 112 + (78 - e.width) // 2, y + 26 + (70 - e.height) // 2))
    d = ImageDraw.Draw(base)
    nx = M + 204
    name, _, tag = pl["riot_id"].partition("#")
    nm = fit(name.upper(), bebas(34), 250)
    d.text((nx, y + 50), nm, font=bebas(34), fill=TEXT, anchor="ls")
    d.text((nx + bebas(34).getlength(nm) + 6, y + 48), f"#{tag}", font=barlow(15, "Medium"), fill=MUTED, anchor="ls")
    tcol = TIER_COLOR.get(solo["tier"], TEXT) if solo else MUTED
    d.text((nx, y + 78), tier_name(solo), font=bebas(24), fill=tcol, anchor="ls")
    if solo:
        w, l = solo["wins"], solo["losses"]
        tx = nx + bebas(24).getlength(tier_name(solo)) + 10
        d.text((tx, y + 77), f"{solo['leaguePoints']} PDL · {w / max(w + l, 1) * 100:.0f}% em {w + l} jogos",
               font=barlow(14, "Medium"), fill=MUTED, anchor="ls")

    # forma recente: quadradinhos (mais antiga à esquerda, mais nova à direita)
    form = list(reversed(pl.get("form", [])))
    fx = nx
    for won in form:
        d.rounded_rectangle((fx, y + 96, fx + 13, y + 109), 3, fill=WIN if won else LOSS)
        fx += 17
    if form:
        wins = sum(form)
        d.text((fx + 6, y + 109), f"{wins}V {len(form) - wins}D", font=bebas(18), fill=TEXT, anchor="ls")
    tracked(d, (nx, y + 120), "DA MAIS ANTIGA PRA MAIS RECENTE", barlow(10), MUTED, 1.5)

    # números
    sx = 640
    if st:
        cells = [("KDA", f"{st['kda']:.1f}"), ("PART. KILLS", f"{st['kp'] * 100:.0f}%"),
                 ("CS/MIN", f"{st['cs']:.1f}"), ("DANO DO TIME", f"{st['dmg'] * 100:.0f}%")]
        for i, (lab, val) in enumerate(cells):
            cx, cy = sx + (i % 2) * 86, y + 22 + (i // 2) * 58
            d.text((cx, cy + 28), val, font=bebas(30), fill=TEXT, anchor="ls")
            tracked(d, (cx, cy + 34), lab, barlow(10), MUTED, 1.2)

    # campeões
    cx0 = 826
    tracked(d, (cx0, y + 12), f"MAIS JOGADOS · POOL DE {len(pl['champs'])}", barlow(11), MUTED, 1.6)
    for i, ((cid, c), img) in enumerate(zip(pl["_top"], pl["_top_imgs"])):
        x = cx0 + i * 108
        is_ban = (name, cid) in ban_keys
        if img:
            base.alpha_composite(rounded(img, ICON, ICON, 10), (x, y + 34))
        d = ImageDraw.Draw(base)
        d.rounded_rectangle((x, y + 34, x + ICON - 1, y + 34 + ICON - 1), 10,
                            outline=ACCENT if is_ban else (255, 255, 255, 40), width=3 if is_ban else 1)
        wr = c["wins"] / c["games"]
        kda = (c["k"] + c["a"]) / max(c["d"], 1)
        d.text((x + ICON + 6, y + 50), f"{c['games']}J", font=bebas(22), fill=TEXT, anchor="ls")
        d.text((x + ICON + 6, y + 70), f"{wr * 100:.0f}%", font=barlow(14), fill=WIN if wr >= .5 else LOSS,
               anchor="ls")
        d.text((x + ICON + 6, y + 87), f"KDA {kda:.1f}", font=barlow(12, "Medium"), fill=MUTED, anchor="ls")
        if is_ban:
            d.text((x + ICON / 2, y + 34 + ICON + 20), "BANIR", font=bebas(18), fill=ACCENT, anchor="ms")
    if not pl["_top"]:
        d.text((cx0, y + 70), "SEM RANQUEADAS RECENTES", font=barlow(15), fill=MUTED, anchor="ls")


def _render(players, must, extra, recent, notes):
    ban_keys = {(c["player"], c["id"]) for c in must}
    ban_h = 250 if must else 150
    notes_h = (70 + ((len(notes) + 1) // 2) * 92) if notes else 0
    H = 150 + len(players) * (ROW_H + GAP) + 20 + ban_h + notes_h + 50
    base = Image.new("RGBA", (W, H), BG + (255,))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((W - 500, -300, W + 300, 300), fill=ACCENT + (38,))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(130)))
    d = ImageDraw.Draw(base)
    d.rectangle((0, 0, 5, H), fill=ACCENT)
    d.rectangle((M, 50, M + 26, 52), fill=ACCENT)
    tracked(d, (M + 38, 42), "SCOUT · TIME ADVERSÁRIO", barlow(16), ACCENT, 3)
    d.text((M, 128), "ANÁLISE DE BANS", font=bebas(72), fill=TEXT, anchor="ls")
    d.text((W - M, 124), f"últimas {recent} ranqueadas solo/duo de cada um", font=barlow(20, "Medium"),
           fill=MUTED, anchor="rs")

    y = 150
    for pl in players:
        _row(base, pl, y, ban_keys)
        y += ROW_H + GAP

    # ---------- bans
    y += 20
    d = ImageDraw.Draw(base)
    if must:
        d.text((M, y + 40), "BANIR", font=bebas(52), fill=ACCENT, anchor="ls")
        tracked(d, (M + bebas(52).getlength("BANIR") + 16, y + 36), "OS CAMPEÕES QUE MAIS AMEAÇAM", barlow(14),
                MUTED, 2.5)
        bw = (W - 2 * M - 2 * 20) / 3
        for i, c in enumerate(must[:3]):
            x = M + i * (bw + 20)
            layer_rect(base, (x, y + 60, x + bw, y + 230), 16, fill=(232, 64, 87, 28), outline=ACCENT + (160,),
                       width=2)
            if c.get("_img"):
                base.alpha_composite(rounded(c["_img"], 96, 96, 16), (int(x + 18), y + 80))
            d = ImageDraw.Draw(base)
            d.text((x + 132, y + 112), fit(c["champ"].upper(), bebas(38), bw - 150), font=bebas(38), fill=TEXT,
                   anchor="ls")
            d.text((x + 132, y + 138), fit(c["player"], barlow(18), bw - 150), font=barlow(18), fill=MUTED,
                   anchor="ls")
            d.text((x + 132, y + 166), f"{c['games']} DE {c['total']} JOGOS", font=bebas(24), fill=TEXT,
                   anchor="ls")
            d.text((x + 132, y + 192), f"{c['wr'] * 100:.0f}% DE VITÓRIA · KDA {c['kda']:.1f}", font=bebas(24),
                   fill=WIN if c["wr"] >= .5 else LOSS, anchor="ls")
        if extra:
            d.text((W - M, y + 40), "SE SOBRAR BAN: " + " · ".join(c["champ"].upper() for c in extra),
                   font=bebas(24), fill=MUTED, anchor="rs")
    else:
        layer_rect(base, (M, y + 10, W - M, y + 130), 16, fill=PANEL, outline=LINE)
        d = ImageDraw.Draw(base)
        d.text((M + 28, y + 64), "SEM BAN OBRIGATÓRIO", font=bebas(44), fill=WIN, anchor="ls")
        d.text((M + 28, y + 98), "Ninguém tem um campeão dominante. Use os bans nos counters do seu time ou no meta.",
               font=barlow(18, "Medium"), fill=MUTED, anchor="ls")
    y += ban_h

    # ---------- leitura do time
    if notes:
        d = ImageDraw.Draw(base)
        d.text((M, y + 40), "LEITURA DO TIME", font=bebas(40), fill=TEXT, anchor="ls")
        cw = (W - 2 * M - 20) / 2
        for i, (title, text) in enumerate(notes):
            x = M + (i % 2) * (cw + 20)
            ty = y + 60 + (i // 2) * 92
            layer_rect(base, (x, ty, x + cw, ty + 80), 14, fill=PANEL, outline=LINE)
            d = ImageDraw.Draw(base)
            tracked(d, (x + 20, ty + 14), title, barlow(12), WIN if title == "PONTO FRACO" else ACCENT, 2)
            for j, line in enumerate(wrap(text, barlow(17, "Medium"), cw - 40)[:2]):
                d.text((x + 20, ty + 46 + j * 22), line, font=barlow(17, "Medium"), fill=TEXT, anchor="ls")

    d = ImageDraw.Draw(base)
    tracked(d, (M, H - 34), "BOT DEEH LOL · DADOS DA API OFICIAL DA RIOT", barlow(12), MUTED, 2.5)
    return jpg(base)
