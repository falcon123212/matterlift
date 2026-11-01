"""The "understanding" picture: the photo with each SAM mask tinted, the square sampled from it,
and what Spark called it. Shown before generation so the user sees what the tool understood."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont

PALETTE = [(230, 80, 70), (90, 110, 230), (240, 180, 40), (90, 200, 120),
           (200, 90, 220), (60, 200, 220), (250, 130, 30), (160, 160, 160)]


def draw(photo: Image.Image, items: list[tuple[str, np.ndarray | None, tuple[int, int, int] | None]],
         max_side: int = 1400) -> Image.Image:
    """items: (label, mask or None, sampled square (x, y, side) or None), in photo pixels."""
    vis = np.asarray(photo.convert("RGB")).astype(np.float32)
    for i, (_, mask, _) in enumerate(items):
        if mask is not None:
            vis[mask] = vis[mask] * 0.5 + np.array(PALETTE[i % len(PALETTE)]) * 0.5
    out = Image.fromarray(vis.astype(np.uint8))
    scale = min(1.0, max_side / max(out.size))
    if scale < 1:
        out = out.resize((round(out.width * scale), round(out.height * scale)), Image.LANCZOS)
    d = ImageDraw.Draw(out)
    lw = max(2, round(4 * out.width / 1400))
    fs = max(14, round(out.width / 52))
    font = ImageFont.load_default(size=fs)
    for i, (label, mask, square) in enumerate(items):
        color = PALETTE[i % len(PALETTE)]
        if square is not None:
            x, y, s = (v * scale for v in square)
            d.rectangle([x, y, x + s, y + s], outline=(255, 255, 255), width=lw + 2)
            d.rectangle([x, y, x + s, y + s], outline=color, width=lw)
        if mask is not None and mask.any():
            ys, xs = np.nonzero(mask)
            tx, ty = float(np.median(xs)) * scale, float(np.median(ys)) * scale
        elif square is not None:
            tx, ty = (square[0] + 4) * scale, (square[1] + 4) * scale
        else:
            continue
        text = f" {i + 1}  {label.replace('_', ' ')} "
        w = d.textlength(text, font=font) + 8
        tx = min(tx, out.width - w - 2)
        d.rounded_rectangle([tx, ty, tx + w, ty + fs * 1.5], radius=fs // 3, fill=(20, 20, 22))
        d.text((tx + 4, ty + fs * 0.2), text, fill=color, font=font)
    return out
