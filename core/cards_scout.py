"""Cards do /scout, pensados pra ler no Discord sem precisar abrir a imagem.

- Resumo: bans sugeridos, leitura do time e quem não foi encontrado.
- Um card por jogador: elo, forma recente, números e os campeões que ele joga,
  com o campeão mais jogado de fundo.
O Discord mostra cada card na largura toda da mensagem, então a letra é grande."""
import asyncio

from PIL import Image, ImageDraw, ImageFilter

from core.cards import TIER_COLOR, cover, fit_box, rounded
from core.cards_pro import barlow, bebas, fit, jpg, tracked
from core.util import TIER_PT, TIERS

W = 1200
M = 56
BG = (11, 7, 16)
PANEL = (255, 255, 255, 12)
LINE = (255, 255, 255, 30)
TEXT = (244, 240, 248)
MUTED = (160, 150, 175)
ACCENT = (232, 64, 87)
WIN = (64, 214, 140)
LOSS = (240, 74, 92)
POOL = 4


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


def glow(base, box, color, alpha, blur):
    lay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(lay).ellipse(box, fill=color + (alpha,))
    base.alpha_composite(lay.filter(ImageFilter.GaussianBlur(blur)))


def short(riot_id):
    return riot_id.split("#")[0]


# ================================================================== carregamento
async def render_scout(cards, players: list[dict], must: list[dict], extra: list[dict], recent: int,
                       notes: list[tuple[str, str]] | None = None):
    """Devolve [resumo, card do jogador 1, card do jogador 2, ...] (JPGs em memória)."""
    dd = cards.dd
    icon = lambda cid: dd.champ_icon(dd.by_key[cid]["id"]) if cid in dd.by_key else None  # noqa: E731
    urls = []
    for pl in players:
        if pl.get("error"):
            continue
        pl["_top"] = sorted(pl["champs"].items(), key=lambda kv: (-kv[1]["games"], -kv[1]["wins"]))[:POOL]
        if not pl["_top"]:   # sem ranqueadas: mostra as maiores maestrias
            pl["_mastery"] = [m["championId"] for m in pl.get("masteries", [])][:POOL]
        ids = [cid for cid, _ in pl["_top"]] or pl.get("_mastery", [])
        main = dd.by_key.get(ids[0]) if ids else None
        urls.append(cards.emblem_url(pl["solo"]["tier"]) if pl.get("solo") else None)
        urls.append(dd.splash(main["id"]) if main else None)
        urls += [icon(cid) for cid in ids]
    urls += [icon(c["id"]) for c in must]
    imgs = iter(await cards.imgs(urls))
    for pl in players:
        if pl.get("error"):
            continue
        pl["_emblem"] = next(imgs)
        pl["_splash"] = next(imgs)
        pl["_icons"] = [next(imgs) for _ in (pl["_top"] or pl.get("_mastery", []))]
    for c in must:
        c["_img"] = next(imgs)
    names = {c: dd.champ_name(c) for pl in players if not pl.get("error")
             for c in [cid for cid, _ in pl["_top"]] + pl.get("_mastery", [])}
    return await asyncio.to_thread(_render_all, players, must, extra, recent, notes or [], names)


def _render_all(players, must, extra, recent, notes, names):
    ok = [p for p in players if not p.get("error")]
    out = [_summary(players, must, extra, recent, notes)]
    ban_keys = {(c["player"], c["id"]) for c in must}
    for i, pl in enumerate(ok, 1):
        out.append(_player(pl, i, len(ok), recent, ban_keys, names))
    return out


# ================================================================== resumo
def _summary(players, must, extra, recent, notes):
    ok = [p for p in players if not p.get("error")]
    bad = [p for p in players if p.get("error")]
    note_f = barlow(30, "Medium")
    note_lines = [wrap(t, note_f, W - 2 * M - 56) for _, t in notes]
    H = 230 + (330 if must else 170) + (60 if extra else 0)
    if notes:
        H += 80 + sum(64 + 40 * len(ls) + 18 for ls in note_lines)
    if bad:
        H += 70
    H += 60
    base = Image.new("RGBA", (W, H), BG + (255,))
    glow(base, (W - 560, -360, W + 300, 320), ACCENT, 60, 140)
    d = ImageDraw.Draw(base)
    d.rectangle((0, 0, 8, H), fill=ACCENT)

    tracked(d, (M, 50), "SCOUT · TIME ADVERSÁRIO", barlow(24, "Bold"), ACCENT, 5)
    d.text((M - 4, 80), "ANÁLISE DO ADVERSÁRIO", font=bebas(92), fill=TEXT)
    sub = f"{len(ok)} JOGADORES · ÚLTIMAS {recent} RANQUEADAS SOLO/DUO DE CADA UM"
    tracked(d, (M, 180), sub, barlow(22, "Bold"), MUTED, 3)
    y = 230

    if must:
        d.text((M, y), "BANIR", font=bebas(64), fill=ACCENT)
        y += 80
        n = len(must)
        gap = 20
        bw = (W - 2 * M - gap * (n - 1)) / n
        for i, c in enumerate(must):
            x = M + i * (bw + gap)
            layer_rect(base, (x, y, x + bw, y + 230), 20, fill=ACCENT + (30,), outline=ACCENT + (170,), width=3)
            if c.get("_img"):
                base.alpha_composite(rounded(c["_img"], 120, 120, 18), (int(x + 22), y + 22))
            d = ImageDraw.Draw(base)
            tx, tw = x + 160, bw - 176
            if n == 3:   # 3 lado a lado: o texto vai embaixo do ícone
                tx, tw = x + 22, bw - 44
                d.text((x + 160, y + 30), fit(c["champ"].upper(), bebas(46), bw - 176), font=bebas(46), fill=TEXT)
                d.text((x + 160, y + 86), fit(c["player"], barlow(28, "Bold"), bw - 176), font=barlow(28, "Bold"),
                       fill=MUTED)
                d.text((tx, y + 158), f"{c['games']} DE {c['total']} JOGOS", font=bebas(34), fill=TEXT)
                d.text((tx, y + 192), f"{c['wr'] * 100:.0f}% VITÓRIA · KDA {c['kda']:.1f}", font=bebas(30),
                       fill=WIN if c["wr"] >= .5 else LOSS)
            else:
                d.text((tx, y + 26), fit(c["champ"].upper(), bebas(56), tw), font=bebas(56), fill=TEXT)
                d.text((tx, y + 90), fit(c["player"], barlow(30, "Bold"), tw), font=barlow(30, "Bold"), fill=MUTED)
                d.text((tx, y + 140), f"{c['games']} DE {c['total']} JOGOS", font=bebas(36), fill=TEXT)
                d.text((tx, y + 180), f"{c['wr'] * 100:.0f}% DE VITÓRIA · KDA {c['kda']:.1f}", font=bebas(32),
                       fill=WIN if c["wr"] >= .5 else LOSS)
        y += 250
        if extra:
            txt = "SE SOBRAR BAN:  " + "  ·  ".join(f"{c['champ'].upper()} ({c['player']})" for c in extra)
            d.text((M, y), fit(txt, bebas(38), W - 2 * M), font=bebas(38), fill=MUTED)
            y += 60
    else:
        layer_rect(base, (M, y, W - M, y + 150), 20, fill=PANEL, outline=LINE)
        d = ImageDraw.Draw(base)
        d.text((M + 32, y + 24), "SEM BAN OBRIGATÓRIO", font=bebas(56), fill=WIN)
        d.text((M + 32, y + 92), "Ninguém tem um campeão dominante. Use os bans nos counters do seu time.",
               font=barlow(28, "Medium"), fill=MUTED)
        y += 170

    if notes:
        y += 20
        d.text((M, y), "LEITURA DO TIME", font=bebas(56), fill=TEXT)
        y += 70
        for (title, _), lines in zip(notes, note_lines):
            h = 64 + 40 * len(lines)
            layer_rect(base, (M, y, W - M, y + h), 18, fill=PANEL, outline=LINE)
            d = ImageDraw.Draw(base)
            col = WIN if title == "PONTO FRACO" else ACCENT
            d.rectangle((M, y + 18, M + 5, y + h - 18), fill=col)
            tracked(d, (M + 28, y + 18), title, barlow(22, "Bold"), col, 4)
            for j, line in enumerate(lines):
                d.text((M + 28, y + 50 + j * 40), line, font=note_f, fill=TEXT)
            y += h + 18

    if bad:
        txt = "NÃO ENCONTRADOS: " + ", ".join(p["riot_id"] for p in bad)
        d.text((M, y + 10), fit(txt, barlow(28, "Bold"), W - 2 * M), font=barlow(28, "Bold"), fill=LOSS)
        y += 70

    tracked(d, (M, H - 44), "BOT DEEH LOL · DADOS DA API OFICIAL DA RIOT", barlow(18, "Bold"), MUTED, 3)
    return jpg(base)


# ================================================================== card do jogador
def _player(pl, idx, total, recent, ban_keys, names):
    H = 640
    base = Image.new("RGBA", (W, H), BG + (255,))
    solo, st = pl.get("solo"), pl.get("stats")
    tcol = TIER_COLOR.get(solo["tier"], TEXT) if solo else MUTED

    # fundo: splash do campeão mais jogado à direita, sumindo pra esquerda
    if pl.get("_splash"):
        sp = cover(pl["_splash"].convert("RGBA"), 760, H, 0.25)
        mask = Image.linear_gradient("L").rotate(90, expand=True).resize((760, H))
        mask = mask.point(lambda v: int(v * 0.8))
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        layer.paste(sp, (W - 760, 0), mask)
        base.alpha_composite(layer)
        shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(shade).rectangle((0, 250, W, H), fill=BG + (150,))
        base.alpha_composite(shade.filter(ImageFilter.GaussianBlur(40)))
    glow(base, (-300, -300, 400, 300), tcol, 50, 130)
    d = ImageDraw.Draw(base)
    d.rectangle((0, 0, 8, H), fill=tcol)

    # ---- cabeçalho: emblema, nick, elo
    tracked(d, (M, 40), f"JOGADOR {idx} DE {total}", barlow(22, "Bold"), MUTED, 4)
    x = M
    if pl.get("_emblem"):
        e = fit_box(pl["_emblem"], 150, 130)
        base.alpha_composite(e, (M - 10 + (150 - e.width) // 2, 78 + (130 - e.height) // 2))
        x = M + 160
    d = ImageDraw.Draw(base)
    name, _, tag = pl["riot_id"].partition("#")
    nf = bebas(80)
    nm = fit(name.upper(), nf, W - x - 200)
    d.text((x, 72), nm, font=nf, fill=TEXT)
    d.text((x + nf.getlength(nm) + 10, 112), f"#{tag}", font=barlow(30, "Medium"), fill=MUTED)
    elo = tier_name(solo)
    d.text((x, 160), elo, font=bebas(48), fill=tcol)
    if solo:
        w, l = solo["wins"], solo["losses"]
        d.text((x + bebas(48).getlength(elo) + 16, 170),
               f"{solo['leaguePoints']} PDL · {w / max(w + l, 1) * 100:.0f}% EM {w + l} JOGOS",
               font=barlow(30, "Bold"), fill=MUTED)

    # ---- forma recente (mais antiga à esquerda)
    form = list(reversed(pl.get("form", [])))
    fy = 236
    if form:
        tracked(d, (M, fy), f"ÚLTIMAS {len(form)} RANQUEADAS", barlow(22, "Bold"), MUTED, 3)
        fx = M
        for won in form:
            d.rounded_rectangle((fx, fy + 36, fx + 30, fy + 66), 6, fill=WIN if won else LOSS)
            fx += 38
        wins = sum(form)
        d.text((fx + 12, fy + 30), f"{wins}V {len(form) - wins}D", font=bebas(42), fill=TEXT)

    # ---- números
    if st:
        cells = [("KDA", f"{st['kda']:.1f}"), ("VITÓRIAS", f"{st['wr'] * 100:.0f}%"),
                 ("PART. KILLS", f"{st['kp'] * 100:.0f}%"), ("DANO DO TIME", f"{st['dmg'] * 100:.0f}%")]
        cy = 340
        gap = 16
        cw = (W - 2 * M - gap * 3) / 4
        for i, (lab, val) in enumerate(cells):
            cx = M + i * (cw + gap)
            layer_rect(base, (cx, cy, cx + cw, cy + 104), 16, fill=(16, 12, 22, 200), outline=LINE)
            d = ImageDraw.Draw(base)
            tracked(d, (cx + 22, cy + 14), lab, barlow(20, "Bold"), MUTED, 3)
            col = TEXT
            if lab == "VITÓRIAS":
                col = WIN if st["wr"] >= .5 else LOSS
            d.text((cx + 22, cy + 38), val, font=bebas(58), fill=col)

    # ---- campeões que ele joga
    py = 470
    top, mastery = pl["_top"], pl.get("_mastery", [])
    label = (f"O QUE ELE JOGA · {len(pl['champs'])} CAMPEÕES NAS ÚLTIMAS {pl['games']}" if top
             else "SEM RANQUEADAS RECENTES · MAIORES MAESTRIAS")
    tracked(d, (M, py - 6), label, barlow(22, "Bold"), MUTED, 3)
    slots = len(top or mastery)
    sw = (W - 2 * M) / POOL
    for i in range(slots):
        sx = M + i * sw
        cid = top[i][0] if top else mastery[i]
        img = pl["_icons"][i] if i < len(pl["_icons"]) else None
        banned = (short(pl["riot_id"]), cid) in ban_keys
        iy = py + 34
        if img:
            base.alpha_composite(rounded(img, 96, 96, 14), (int(sx), iy))
        d = ImageDraw.Draw(base)
        d.rounded_rectangle((sx, iy, sx + 95, iy + 95), 14, outline=ACCENT if banned else (255, 255, 255, 50),
                            width=5 if banned else 2)
        if banned:
            d.rounded_rectangle((sx + 10, iy + 76, sx + 86, iy + 104), 8, fill=ACCENT)
            d.text((sx + 48, iy + 91), "BANIR", font=bebas(26), fill=TEXT, anchor="mm")
        tx, tw = sx + 108, sw - 116
        d.text((tx, iy - 2), fit(names.get(cid, "?").upper(), bebas(34), tw), font=bebas(34), fill=TEXT)
        if top:
            c = top[i][1]
            wr = c["wins"] / c["games"]
            d.text((tx, iy + 36), f"{c['games']} JOGO" + ("S" if c["games"] > 1 else ""), font=barlow(26, "Bold"), fill=TEXT)
            d.text((tx, iy + 66), f"{wr * 100:.0f}%", font=barlow(26, "Bold"), fill=WIN if wr >= .5 else LOSS)
            kda = (c["k"] + c["a"]) / max(c["d"], 1)
            d.text((tx + barlow(26, "Bold").getlength(f"{wr * 100:.0f}%") + 10, iy + 66), f"KDA {kda:.1f}",
                   font=barlow(26, "Medium"), fill=MUTED)
    return jpg(base)
