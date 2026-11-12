"""Card dos avisos de evento do app da Bloom (scrim, coach, jogo oficial) no canal #notícias.

Mesmo visual do /scout: fundo escuro, Bebas Neue nos números e títulos, Barlow nos rótulos.
Cada time tem a sua cor (Bloom White gelo, Bloom Red vermelho)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from core.cards_pro import barlow, bebas, fit, jpg, tracked

W, H = 1200, 540
M = 56
BG = (11, 7, 16)
TEXT = (244, 240, 248)
MUTED = (150, 140, 165)
GRAY = (120, 116, 132)
BRT = timezone(timedelta(hours=-3))  # horário de Brasília (sem horário de verão)
LOGO = Path(__file__).resolve().parent.parent / "assets" / "bloom" / "logo.png"

TEAM_COLOR = {"Bloom White": (196, 220, 248), "Bloom Red": (232, 71, 91)}
KIND_LABEL = {"created": "NOVO EVENTO", "time": "HORÁRIO ALTERADO", "cancelled": "EVENTO CANCELADO",
              "updated": "EVENTO ATUALIZADO", "reminder": "LEMBRETE"}
WEEKDAY = ["SEG", "TER", "QUA", "QUI", "SEX", "SÁB", "DOM"]

_logo_cache: dict = {}


def team_logo(color, size):
    """Logo branco sobre preto vira uma máscara, pintada na cor do time."""
    key = (color, size)
    if key not in _logo_cache:
        if not LOGO.exists():
            _logo_cache[key] = None
        else:
            src = Image.open(LOGO).convert("L").resize((size, size), Image.LANCZOS)
            mask = ImageOps.autocontrast(src)
            tinted = Image.new("RGBA", (size, size), color + (255,))
            tinted.putalpha(mask)
            _logo_cache[key] = tinted
    return _logo_cache[key]


def faded(img, alpha):
    out = img.copy()
    out.putalpha(img.getchannel("A").point(lambda a: int(a * alpha)))
    return out


def layer(base, fn):
    lay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    fn(ImageDraw.Draw(lay))
    base.alpha_composite(lay)


def countdown(start, now):
    mins = int((start - now).total_seconds() // 60)
    if mins < -180:
        return "ENCERRADO"
    if mins < 0:
        return "JÁ COMEÇOU"
    if mins < 60:
        return f"{max(mins, 1)} MIN"
    hours = round(mins / 60)
    if hours < 24:
        return f"{hours} HORA" if hours == 1 else f"{hours} HORAS"
    days = (start.date() - now.date()).days
    return "AMANHÃ" if days == 1 else f"{days} DIAS"


def render_aviso(team, kind, heading, title, start, type_label=None, location=None, now=None):
    """team: 'Bloom White'/'Bloom Red'; kind: created|time|cancelled|updated|reminder;
    heading: frase do aviso (ex.: 'Nova scrim marcada'); title: 'Copa X vs Adversário';
    start: datetime com fuso (ou None)."""
    now = now or datetime.now(BRT)
    cancelled = kind == "cancelled"
    accent = GRAY if cancelled else TEAM_COLOR.get(team, TEAM_COLOR["Bloom White"])
    base = Image.new("RGBA", (W, H), BG + (255,))

    # ---- fundo: brilho da cor do time no canto e o logo grande apagado à direita
    def glow(d):
        d.ellipse((-260, -320, 520, 380), fill=accent + (70,))
        d.ellipse((W - 420, H - 260, W + 260, H + 320), fill=accent + (36,))
    lay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    glow(ImageDraw.Draw(lay))
    base.alpha_composite(lay.filter(ImageFilter.GaussianBlur(120)))
    big = team_logo((255, 255, 255) if team == "Bloom White" and not cancelled else accent, 560)
    if big:
        base.alpha_composite(faded(big, 0.10), (W - 470, -20))
    layer(base, lambda d: [d.line((x, 0, x - 260, H), fill=(255, 255, 255, 6), width=2)
                           for x in range(700, W + 300, 38)])

    d = ImageDraw.Draw(base)

    # ---- topo: logo, nome do time e o tipo do aviso
    logo_col = (255, 255, 255) if team == "Bloom White" and not cancelled else accent
    small = team_logo(logo_col, 76)
    x = M
    if small:
        base.alpha_composite(small, (M - 6, 38))
        x = M + 86
    tracked(d, (x, 44), team.upper(), barlow(24, "Bold"), accent, spacing=4)
    head = (f"COMEÇA EM {countdown(start.astimezone(BRT), now)}" if start else "LEMBRETE") if kind == "reminder" else (heading or KIND_LABEL.get(kind, "AVISO")).upper()
    d.text((x, 70), fit(head, bebas(52), W - x - 300), font=bebas(52), fill=TEXT)

    if type_label:
        label = type_label.upper()
        f = barlow(24, "Bold")
        w = int(f.getlength(label) + 4 * (len(label) - 1)) + 44
        box = (W - M - w, 52, W - M, 96)
        d.rounded_rectangle(box, 22, fill=accent)
        tracked(d, (box[0] + 22, 59), label, f, BG, spacing=4)

    # ---- confronto: nome do evento em cima, "TIME vs ADVERSÁRIO" grande
    event, opp = (title.split(" vs ", 1) + [None])[:2] if " vs " in title else (title, None)
    y = 168
    if opp:
        tracked(d, (M, y), fit(event.upper(), barlow(26, "Bold"), W - 2 * M), barlow(26, "Bold"), MUTED, spacing=4)
        left, right = team.upper(), opp.upper()
        size = 112
        while size > 56 and bebas(size).getlength(left) + bebas(size).getlength(right) + 150 > W - 2 * M:
            size -= 4
        f, fv = bebas(size), bebas(int(size * 0.55))
        ty = y + 38
        d.text((M, ty), left, font=f, fill=accent)
        vx = M + f.getlength(left) + 30
        d.text((vx, ty + size * 0.36), "VS", font=fv, fill=MUTED)
        rx = vx + fv.getlength("VS") + 30
        d.text((rx, ty), fit(right, f, W - M - rx), font=f, fill=TEXT)
        line_y, line_x2 = ty + size * 0.48, rx + f.getlength(fit(right, f, W - M - rx))
    else:
        size = 104
        f = bebas(size)
        name = fit(title.upper(), f, W - 2 * M)
        d.text((M, y + 20), name, font=f, fill=TEXT)
        line_y, line_x2 = y + 20 + size * 0.48, M + f.getlength(name)
    if cancelled:
        d.line((M - 8, line_y, line_x2 + 8, line_y), fill=(240, 74, 92), width=8)

    # ---- faixa de informações
    tiles = []
    if start:
        s = start.astimezone(BRT)
        tiles.append(("DIA", f"{WEEKDAY[s.weekday()]} {s:%d/%m}"))
        tiles.append(("HORÁRIO", f"{s:%H:%M}"))
        if not cancelled:
            tiles.append(("FALTAM", countdown(s, now)))
    if location:
        tiles.append(("ONDE", location.upper()))
    if cancelled:
        tiles.append(("SITUAÇÃO", "CANCELADO"))
    highlight = {"time": "HORÁRIO", "reminder": "FALTAM", "cancelled": "SITUAÇÃO"}.get(kind)

    ty0, ty1, gap = 372, 484, 14
    widths = [1.0] * len(tiles)
    if location:
        widths[[t[0] for t in tiles].index("ONDE")] = 1.6
    unit = (W - 2 * M - gap * (len(tiles) - 1)) / max(sum(widths), 1)
    x = M
    for (label, value), wf in zip(tiles, widths):
        tw = unit * wf
        hot = label == highlight
        red = label == "SITUAÇÃO"
        col = (240, 74, 92) if red else accent
        layer(base, lambda dd, x=x, tw=tw, hot=hot, col=col: dd.rounded_rectangle(
            (x, ty0, x + tw, ty1), 16, fill=(col + (40,)) if hot else (255, 255, 255, 10),
            outline=(col + (220,)) if hot else (255, 255, 255, 24), width=2))
        d = ImageDraw.Draw(base)
        tracked(d, (x + 22, ty0 + 16), label, barlow(20, "Bold"), col if hot else MUTED, spacing=3)
        fv = bebas(54)
        d.text((x + 22, ty0 + 42), fit(value, fv, tw - 40), font=fv, fill=col if red else TEXT)
        x += tw + gap

    # barra da cor do time embaixo
    ImageDraw.Draw(base).rectangle((0, H - 8, W, H), fill=accent)
    return jpg(base)
