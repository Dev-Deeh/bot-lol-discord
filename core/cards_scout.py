"""Card do /scout: uma linha por jogador com os rostos dos campeões + área de bans em destaque."""
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
ROW_H = 132
ICON = 64


def tier_name(e):
    if not e:
        return "SEM ELO"
    n = TIER_PT.get(e["tier"], e["tier"]).upper()
    return n if TIERS.index(e["tier"]) >= 7 else f"{n} {e['rank']}"


def layer_rect(base, box, radius, fill=None, outline=None, width=1):
    lay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(lay).rounded_rectangle(box, radius, fill=fill, outline=outline, width=width)
    base.alpha_composite(lay)


async def render_scout(cards, players: list[dict], must: list[dict], extra: list[dict], recent: int):
    dd = cards.dd
    urls = []
    for pl in players:
        if pl.get("error"):
            continue
        urls.append(cards.emblem_url(pl["solo"]["tier"]) if pl.get("solo") else None)
        top = sorted(pl["champs"].items(), key=lambda kv: -kv[1]["games"])[:3]
        pl["_top"] = top
        urls += [dd.champ_icon(dd.by_key[cid]["id"]) if cid in dd.by_key else None for cid, _ in top]
        urls += [dd.champ_icon(dd.by_key[m["championId"]]["id"]) if m["championId"] in dd.by_key else None
                 for m in pl["masteries"][:3]]
    for c in must + extra:
        urls.append(dd.champ_icon(dd.by_key[c["id"]]["id"]) if c["id"] in dd.by_key else None)
    imgs = iter(await cards.imgs(urls))
    for pl in players:
        if pl.get("error"):
            continue
        pl["_emblem"] = next(imgs)
        pl["_top_imgs"] = [next(imgs) for _ in pl["_top"]]
        pl["_mast_imgs"] = [next(imgs) for _ in pl["masteries"][:3]]
    for c in must + extra:
        c["_img"] = next(imgs)
    return await asyncio.to_thread(_render, players, must, extra, recent, dd)


def _render(players, must, extra, recent, dd):
    ban_ids = {(c["player"], c["id"]) for c in must}
    ban_h = 250 if must else 150
    H = 150 + len(players) * (ROW_H + 12) + 30 + ban_h + 50
    base = Image.new("RGBA", (W, H), BG + (255,))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((W - 500, -300, W + 300, 300), fill=ACCENT + (38,))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(130)))
    d = ImageDraw.Draw(base)
    d.rectangle((0, 0, 5, H), fill=ACCENT)

    d.rectangle((M, 50, M + 26, 52), fill=ACCENT)
    tracked(d, (M + 38, 42), "SCOUT · TIME ADVERSÁRIO", barlow(16), ACCENT, 3)
    d.text((M, 128), "ANÁLISE DE BANS", font=bebas(72), fill=TEXT, anchor="ls")
    d.text((W - M, 124), f"últimas {recent} ranqueadas de cada um", font=barlow(20, "Medium"), fill=MUTED, anchor="rs")

    y = 150
    for pl in players:
        layer_rect(base, (M, y, W - M, y + ROW_H), 16, fill=PANEL, outline=LINE)
        d = ImageDraw.Draw(base)
        if pl.get("error"):
            d.text((M + 28, y + ROW_H / 2), pl["riot_id"], font=bebas(36), fill=MUTED, anchor="lm")
            d.text((W - M - 28, y + ROW_H / 2), pl["error"].upper(), font=barlow(18), fill=LOSS, anchor="rm")
            y += ROW_H + 12
            continue
        solo = pl.get("solo")
        # emblema + identidade
        if pl["_emblem"]:
            e = fit_box(pl["_emblem"], 92, 80)
            base.alpha_composite(e, (M + 18 + (92 - e.width) // 2, y + (ROW_H - e.height) // 2))
        d = ImageDraw.Draw(base)
        name, _, tag = pl["riot_id"].partition("#")
        nx = M + 128
        d.text((nx, y + 58), fit(name.upper(), bebas(40), 300), font=bebas(40), fill=TEXT, anchor="ls")
        d.text((nx + bebas(40).getlength(fit(name.upper(), bebas(40), 300)) + 8, y + 56), f"#{tag}",
               font=barlow(18, "Medium"), fill=MUTED, anchor="ls")
        tcol = TIER_COLOR.get(solo["tier"], TEXT) if solo else MUTED
        d.text((nx, y + 90), tier_name(solo), font=bebas(28), fill=tcol, anchor="ls")
        sub = []
        if solo:
            w, l = solo["wins"], solo["losses"]
            sub.append(f"{solo['leaguePoints']} PDL · {w / max(w + l, 1) * 100:.0f}% WR")
        if pl.get("role"):
            sub.append(pl["role"].upper())
        tracked(d, (nx, y + 100), "  ·  ".join(sub), barlow(14), MUTED, 1.5)

        # campeões mais jogados (rostos)
        cx = 560
        tracked(d, (cx, y + 10), "MAIS JOGADOS", barlow(12), MUTED, 2)
        for i, ((cid, c), img) in enumerate(zip(pl["_top"], pl["_top_imgs"])):
            x = cx + i * 120
            is_ban = (pl["riot_id"].split("#")[0], cid) in ban_ids
            if img:
                base.alpha_composite(rounded(img, ICON, ICON, 12), (x, y + 30))
            d = ImageDraw.Draw(base)
            d.rounded_rectangle((x, y + 30, x + ICON - 1, y + 30 + ICON - 1), 12,
                                outline=ACCENT if is_ban else (255, 255, 255, 40), width=3 if is_ban else 1)
            wr = c["wins"] / c["games"]
            kda = (c["k"] + c["a"]) / max(c["d"], 1)
            d.text((x + ICON + 8, y + 44), f"{c['games']}J", font=bebas(24), fill=TEXT, anchor="ls")
            d.text((x + ICON + 8, y + 66), f"{wr * 100:.0f}%", font=barlow(16), fill=WIN if wr >= .5 else LOSS,
                   anchor="ls")
            d.text((x + ICON + 8, y + 86), f"KDA {kda:.1f}", font=barlow(14, "Medium"), fill=MUTED, anchor="ls")
            if is_ban:
                d.text((x + ICON / 2, y + 30 + ICON + 18), "BANIR", font=bebas(18), fill=ACCENT, anchor="ms")
        if not pl["_top"]:
            d.text((cx, y + 62), "SEM RANQUEADAS RECENTES", font=barlow(16), fill=MUTED, anchor="ls")

        # maestrias
        mx = W - M - 3 * 44 - 18
        tracked(d, (mx, y + 10), "MAESTRIA", barlow(12), MUTED, 2)
        for i, img in enumerate(pl["_mast_imgs"]):
            if img:
                base.alpha_composite(rounded(img, 40, 40, 20), (mx + i * 44, y + 34))
        y += ROW_H + 12

    # ---------- bans
    y += 18
    d = ImageDraw.Draw(base)
    if must:
        d.text((M, y + 40), "BANIR", font=bebas(52), fill=ACCENT, anchor="ls")
        tracked(d, (M + bebas(52).getlength("BANIR") + 16, y + 36), "OS CAMPEÕES QUE MAIS AMEAÇAM", barlow(14),
                MUTED, 2.5)
        bw = (W - 2 * M - 2 * 20) / 3
        for i, c in enumerate(must[:3]):
            x = M + i * (bw + 20)
            layer_rect(base, (x, y + 60, x + bw, y + 60 + 170), 16, fill=(232, 64, 87, 28),
                       outline=ACCENT + (160,), width=2)
            if c.get("_img"):
                base.alpha_composite(rounded(c["_img"], 96, 96, 16), (int(x + 18), y + 80))
            d = ImageDraw.Draw(base)
            d.text((x + 132, y + 112), fit(c["champ"].upper(), bebas(38), bw - 150), font=bebas(38), fill=TEXT,
                   anchor="ls")
            d.text((x + 132, y + 138), fit(c["player"], barlow(18), bw - 150), font=barlow(18), fill=MUTED,
                   anchor="ls")
            d.text((x + 132, y + 166), f"{c['games']} DE {c['total']} JOGOS", font=bebas(24), fill=TEXT, anchor="ls")
            d.text((x + 132, y + 192), f"{c['wr'] * 100:.0f}% DE VITÓRIA", font=bebas(24),
                   fill=WIN if c["wr"] >= .5 else LOSS, anchor="ls")
        if extra:
            ex = W - M
            d.text((ex, y + 40), "SE SOBRAR BAN: " + " · ".join(c["champ"].upper() for c in extra),
                   font=bebas(24), fill=MUTED, anchor="rs")
    else:
        layer_rect(base, (M, y + 10, W - M, y + 130), 16, fill=PANEL, outline=LINE)
        d = ImageDraw.Draw(base)
        d.text((M + 28, y + 64), "SEM BAN OBRIGATÓRIO", font=bebas(44), fill=WIN, anchor="ls")
        d.text((M + 28, y + 98), "Ninguém tem um campeão dominante. Use os bans nos counters do seu time ou no meta.",
               font=barlow(18, "Medium"), fill=MUTED, anchor="ls")
    d = ImageDraw.Draw(base)
    tracked(d, (M, H - 34), "BOT DEEH LOL · DADOS DA API OFICIAL DA RIOT", barlow(12), MUTED, 2.5)
    return jpg(base)
