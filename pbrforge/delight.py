"""Remove lighting baked into a generated or photographed albedo."""
from __future__ import annotations

import numpy as np
from . import filters
from .metrics import luminance


def delight(img: np.ndarray, sigma_frac: float = 0.125, max_gain: float = 2.0) -> np.ndarray:
    """Flatten low-frequency shading (vignetting, light falloff) while keeping hue and detail."""
    lum = luminance(img)
    low = filters.blur(lum, max(img.shape[:2]) * sigma_frac)
    gain = np.clip(lum.mean() / (low + 1e-4), 1 / max_gain, max_gain)
    return np.clip(img * gain[..., None], 0, 1)


def fit_pbr_range(img: np.ndarray, lo: float = 32 / 255, hi: float = 235 / 255) -> np.ndarray:
    """Softly compress luminance into the plausible albedo range without clipping hue."""
    lum = luminance(img)
    p_lo, p_hi = np.percentile(lum, 0.5), np.percentile(lum, 99.5)
    if p_lo >= lo and p_hi <= hi:
        return img
    new_lo, new_hi = max(p_lo, lo), min(p_hi, hi)
    scale = (new_hi - new_lo) / max(p_hi - p_lo, 1e-4)
    target = np.clip((lum - p_lo) * scale + new_lo, lo * 0.9, hi)
    # Near-black pixels (gaps, cracks) would get an exploding gain and a garish hue.
    gain = np.clip(target / np.maximum(lum, 0.03), 0.5, 2.0)
    return np.clip(img * gain[..., None], 0, 1)


def flatten_uniform(img: np.ndarray, flat_below: float = 0.021, keep_above: float = 0.031) -> tuple[np.ndarray, float]:
    """Remove large blotches from surfaces that should be uniform (paint, plaster, plastic).

    On such a surface the eye has nothing else to look at, so any light/dark drift inside the tile
    becomes a checkerboard once tiled. How much is removed depends on the fine detail: none for a
    brick wall or planks, whose large variations are the pattern itself. Returns (img, strength).
    """
    lum = luminance(img)
    n = img.shape[0]
    fine = float((lum - filters.blur(lum, n / 64)).std())
    strength = float(np.clip((keep_above - fine) / (keep_above - flat_below), 0, 1))
    if strength == 0:
        return img, 0.0
    low = filters.blur(img, n / 8)
    out = img - strength * (low - img.reshape(-1, img.shape[-1]).mean(0))
    return np.clip(out, 0, 1).astype(np.float32), round(strength, 2)
