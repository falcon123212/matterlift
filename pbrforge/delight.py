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
