"""Lê um print de tier list (estilo TierMaker) e descobre quais campeões estão em cada nível.

1. Acha as linhas pela coluna de etiquetas coloridas da esquerda.
2. Em cada linha, acha os quadradinhos (ícones) separados pelo fundo escuro.
3. Compara cada quadradinho com os ícones oficiais dos campeões (Data Dragon) e pega o mais parecido.
"""
import io

import numpy as np
from PIL import Image

SMALL = 24          # tamanho usado na comparação
MARGIN = 0.10       # corta a borda dos ícones (moldura/brilho)


def _small(img: Image.Image) -> np.ndarray:
    img = img.convert("RGB")
    w, h = img.size
    mx, my = int(w * MARGIN), int(h * MARGIN)
    img = img.crop((mx, my, w - mx, h - my)).resize((SMALL, SMALL), Image.BILINEAR)
    a = np.asarray(img, dtype=np.float32)
    return (a - a.mean()) / (a.std() + 1e-6)  # normaliza brilho/contraste


def prepare_icons(icons: dict) -> tuple[list, np.ndarray]:
    """icons: {id_do_campeão: PIL.Image}. Retorna (ids, matriz)."""
    ids = list(icons)
    return ids, np.stack([_small(icons[i]).ravel() for i in ids])


def _runs(mask_1d: np.ndarray, min_len: int):
    runs, start = [], None
    for i, v in enumerate(list(mask_1d) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= min_len:
                runs.append((start, i))
            start = None
    return runs


def _label_column(arr: np.ndarray):
    """Faixa x das etiquetas: colunas da esquerda com cor clara e saturada na maior parte da altura."""
    rgb = arr.astype(np.int32)
    mx, mn = rgb.max(axis=2), rgb.min(axis=2)
    label = (mx > 140) & ((mx - mn) > 40)
    frac = label.mean(axis=0)
    w = arr.shape[1]
    cols = frac[: w // 3] > 0.35
    runs = _runs(cols, 20)
    return runs[0] if runs else None


def _tier_rows(arr: np.ndarray, x0: int, x1: int):
    """Linhas de nível: trechos verticais onde a coluna de etiqueta tem cor (ignora as linhas pretas entre elas)."""
    # só a borda esquerda da etiqueta: o texto ("MELHORES BONECOS") fica no meio e cortaria a cor
    strip = arr[:, x0 + 2: min(x0 + 12, x1)].astype(np.int32)
    mx, mn = strip.max(axis=2), strip.min(axis=2)
    colored = ((mx > 120) & ((mx - mn) > 30)).mean(axis=1) > 0.6
    rows = _runs(colored, 30)
    if not rows:
        return rows
    # descarta faixas baixas demais (botões "Share", cabeçalhos)
    tallest = max(b - a for a, b in rows)
    return [(a, b) for a, b in rows if (b - a) >= max(45, tallest * 0.3)]


def read_tierlist(data: bytes, icon_ids: list, icon_mat: np.ndarray):
    """Retorna [(y0, y1, [(champ_id, distância, caixa), ...]), ...] por linha de nível, ou [] se não achar."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    arr = np.asarray(img)
    lab = _label_column(arr)
    if not lab:
        return []
    lx0, lx1 = lab
    rows = []
    for y0, y1 in _tier_rows(arr, lx0, lx1):
        band = arr[y0:y1, lx1 + 2:].astype(np.int32)
        content = band.max(axis=2) > 60                       # tira fundo escuro e linhas pretas
        lines = _runs(content.mean(axis=1) > 0.02, 25)       # cada linha de ícones (nível pode quebrar em 2+)
        found = []
        line_sizes = [b - a for a, b in lines]
        size = int(np.median(line_sizes)) if line_sizes else 0
        for ly0, ly1 in lines:
            if ly1 - ly0 < size * 0.6:
                continue
            sub = content[ly0:ly1]
            colmask = sub.mean(axis=0) > 0.15
            runs = _runs(colmask, max(8, size // 3))
            if not runs:
                continue
            # grade: ícones quadrados do mesmo tamanho; cada um "encaixa" no começo real do ícone
            # (logo depois de uma faixa escura), pra não ir desalinhando ao longo da linha
            gaps = [b2 - a1 for (_, a1), (b2, _) in zip(runs, runs[1:]) if 0 < b2 - a1 < size * 0.3]
            pitch = size + (float(np.median(gaps)) if gaps else max(2, size * 0.05))
            starts = [i for i in range(1, len(colmask)) if colmask[i] and not colmask[i - 1]]
            x, end = runs[0][0], runs[-1][1]
            while x + size * 0.6 <= end:
                near = [s for s in starts if abs(s - x) <= size * 0.2]
                if near:
                    x = min(near, key=lambda s: abs(s - x))
                bx0, bx1 = int(round(x)), int(round(x + size))
                if colmask[bx0:min(bx1, len(colmask))].mean() > 0.5:   # tem ícone aqui (não é espaço vazio)
                    box = (lx1 + 2 + bx0, y0 + ly0, lx1 + 2 + bx1, y0 + ly1)
                    tile = _small(img.crop(box)).ravel()
                    dist = ((icon_mat - tile) ** 2).mean(axis=1)
                    order = np.argsort(dist)[:3]
                    found.append((icon_ids[int(order[0])], float(dist[order[0]]), box,
                                  [icon_ids[int(i)] for i in order]))
                x += pitch
        rows.append((y0, y1, [f[:3] for f in found], [f[3] for f in found]))
    return rows
