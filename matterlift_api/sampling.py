"""Where to sample a surface in the photo, from SAM's mask.

Objects lying on the surface (a bowl on a table) are holes in the mask, so samples taken fully
inside it avoid them. A thin surface (a countertop strip) has no big square but has a long
rectangle; a partly hidden one (a floor behind furniture) is better described by several small
samples than by one. So: the largest rectangle of bounded aspect, then up to two more away from it.
"""
from __future__ import annotations

import numpy as np
from PIL import Image
from scipy import ndimage

Region = tuple[int, int, int, int]  # x, y, w, h in photo pixels

MAX_ASPECT = 3.0


def _reduce(mask: np.ndarray, work: int) -> tuple[np.ndarray, float]:
    h, w = mask.shape
    k = max(1.0, max(h, w) / work)
    small = np.asarray(Image.fromarray(mask).resize((max(1, round(w / k)), max(1, round(h / k))), Image.NEAREST))
    if k > 1:  # one reduced pixel of safety so rounding back up never lands on a hole
        small = ndimage.binary_erosion(small, border_value=0)
    return small, k


def _clamp(w: int, h: int) -> tuple[int, int]:
    if w > MAX_ASPECT * h:
        w = int(MAX_ASPECT * h)
    if h > MAX_ASPECT * w:
        h = int(MAX_ASPECT * w)
    return w, h


def largest_rect(mask: np.ndarray, square: bool = False) -> tuple[int, int, int, int] | None:
    """(x, y, w, h) of the largest-area rectangle fully inside `mask` with aspect <= MAX_ASPECT
    (or a square), in mask pixels. Histogram/stack method, one pass per row."""
    hgt, wid = mask.shape
    heights = np.zeros(wid + 1, dtype=np.int32)
    best, best_rect = 0, None
    for y in range(hgt):
        heights[:wid] = np.where(mask[y], heights[:wid] + 1, 0)
        stack: list[int] = []
        for x in range(wid + 1):
            while stack and heights[stack[-1]] >= heights[x]:
                bar = heights[stack.pop()]
                left = stack[-1] + 1 if stack else 0
                rw, rh = x - left, int(bar)
                cw, ch = (min(rw, rh), min(rw, rh)) if square else _clamp(rw, rh)
                if cw * ch > best:
                    best = cw * ch
                    best_rect = (left + (rw - cw) // 2, y - rh + 1 + (rh - ch) // 2, cw, ch)
            stack.append(x)
    return best_rect


def sample_regions(mask: np.ndarray, max_regions: int = 3, min_side: int = 40, work: int = 256,
                   margin: float = 0.05) -> list[Region]:
    """Up to `max_regions` samples inside the mask, largest first, in mask pixels."""
    small, k = _reduce(mask, work)
    free = small.copy()
    regions: list[Region] = []
    first_area = 0
    for _ in range(max_regions):
        r = largest_rect(free)
        if r is None:
            break
        x, y, w, h = r
        px = (x * k, y * k, w * k, h * k)
        inset = min(px[2], px[3]) * margin
        region = (int(px[0] + inset), int(px[1] + inset), int(px[2] - 2 * inset), int(px[3] - 2 * inset))
        area = region[2] * region[3]
        if min(region[2], region[3]) < min_side or (regions and area < 0.2 * first_area):
            break
        first_area = first_area or area
        regions.append(region)
        pad = max(2, min(w, h) // 4)  # keep the next samples away from this one
        free[max(0, y - pad) : y + h + pad, max(0, x - pad) : x + w + pad] = False
    return regions


def box_fallback(box, photo_size: tuple[int, int]) -> Region:
    """Centre of SAM's box, for a mask with no usable region."""
    side = int(min(box.x2 - box.x1, box.y2 - box.y1) * 0.84)
    x = max(0, (box.x1 + box.x2) // 2 - side // 2)
    y = max(0, (box.y1 + box.y2) // 2 - side // 2)
    return x, y, min(side, photo_size[0] - x), min(side, photo_size[1] - y)


def crop(photo: Image.Image, r: Region) -> Image.Image:
    x, y, w, h = r
    return photo.crop((x, y, x + w, y + h))
