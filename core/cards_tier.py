"""Card de tier list com os ícones dos campeões (estilo do card de perfil: Bebas Neue + Barlow, tema Inferno)."""
import asyncio
import io

from PIL import Image, ImageDraw, ImageFilter

from core.cards import rounded
from core.cards_pro import barlow, bebas, fit, jpg, tracked

BG = (11, 7, 16)
TEXT = (244, 240, 248)
MUTED = (150, 140, 165)
ACCENT = (178, 92, 255)
TIER_COLORS = [(255, 110, 120), (255, 170, 100), (255, 215, 110), (190, 230, 120), (120, 200, 230), (170, 150, 230)]
W, M, ICON, GAP, LABEL_W = 1200, 48, 72, 8, 150


async def render(cards, owner_name: str, subtitle: str, tiers: list[tuple[str, list[dict]]]):
    """tiers: [(nome do nível, [dados do campeão do Data Dragon, ...]), ...]"""
    urls = [cards.dd.champ_icon(c["id"]) for _, champs in tiers for c in champs]
    imgs = iter(await cards.imgs(urls))
    with_imgs = [(name, [(c, next(imgs)) for c in champs]) for name, champs in tiers]
    return await asyncio.to_thread(_render, owner_name, subtitle, with_imgs)


def _render(owner_name, subtitle, tiers):
    per_row = (W - 2 * M - LABEL_W - 16) // (ICON + GAP)
    row_heights = []
    for _, champs in tiers:
        lines = max(1, -(-len(champs) // per_row))
        row_heights.append(lines * (ICON + GAP) + 16)
    H = 170 + sum(row_heights) + (len(tiers) - 1) * 10 + 60
    base = Image.new("RGBA", (W, H), BG + (255,))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((-300, -300, 500, 300), fill=ACCENT + (40,))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(120)))
    d = ImageDraw.Draw(base)
    d.rectangle((0, 0, 5, H), fill=ACCENT)

    d.rectangle((M, 50, M + 26, 52), fill=ACCENT)
    tracked(d, (M + 38, 42), "TIER LIST · BLOOM WHITE", barlow(16), ACCENT, 3)
    d.text((M, 140), fit(owner_name.upper(), bebas(72), W - 2 * M), font=bebas(72), fill=TEXT, anchor="ls")
    if subtitle:
        d.text((W - M, 136), subtitle, font=barlow(22, "Medium"), fill=MUTED, anchor="rs")

    y = 170
    for i, ((name, champs), rh) in enumerate(zip(tiers, row_heights)):
        color = TIER_COLORS[i % len(TIER_COLORS)]
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.rounded_rectangle((M, y, W - M, y + rh), 12, fill=(255, 255, 255, 10), outline=(255, 255, 255, 22))
        base.alpha_composite(layer)
        d = ImageDraw.Draw(base)
        d.rounded_rectangle((M, y, M + LABEL_W, y + rh), 12, fill=color)
        label = fit(name.upper(), bebas(40), LABEL_W - 16)
        size = 40 if len(label) <= 6 else 28
        d.text((M + LABEL_W / 2, y + rh / 2), fit(name.upper(), bebas(size), LABEL_W - 16), font=bebas(size),
               fill=BG, anchor="mm")
        if not champs:
            d.text((M + LABEL_W + 20, y + rh / 2), "—", font=barlow(22), fill=MUTED, anchor="lm")
        for j, (champ, img) in enumerate(champs):
            cx = M + LABEL_W + 16 + (j % per_row) * (ICON + GAP)
            cy = y + 8 + (j // per_row) * (ICON + GAP)
            if img:
                base.alpha_composite(rounded(img, ICON, ICON, 10), (cx, cy))
            else:
                ImageDraw.Draw(base).rounded_rectangle((cx, cy, cx + ICON, cy + ICON), 10, fill=(40, 30, 55))
        y += rh + 10
    d = ImageDraw.Draw(base)
    tracked(d, (M, H - 40), "FEITO COM /TIERLIST NO BOT DEEH LOL", barlow(13), MUTED, 2.5)
    return jpg(base)
