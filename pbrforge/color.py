"""Colour fidelity: bring the generated albedo back to the colours of the real surface.

Muse repaints the photo sample, so hue and value drift (a honey oak comes back orange). We match the
albedo's colour statistics to the photo samples in CIELAB: the mean fully, the spread only partly,
since the samples still carry some of the room's lighting. Fidelity is reported as CIE76 Delta E
between mean colours (under ~3 is hard to tell apart, over ~10 is a different colour).
"""
from __future__ import annotations

import numpy as np

from . import delight

_M = np.array([[0.4124564, 0.3575761, 0.1804375],
               [0.2126729, 0.7151522, 0.0721750],
               [0.0193339, 0.1191920, 0.9503041]])
_WHITE = np.array([0.95047, 1.0, 1.08883])


def _to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def srgb_to_lab(img: np.ndarray) -> np.ndarray:
    xyz = (_to_linear(img.astype(np.float64)) @ _M.T) / _WHITE
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def lab_to_srgb(lab: np.ndarray) -> np.ndarray:
    fy = (lab[..., 0] + 16) / 116
    f = np.stack([fy + lab[..., 1] / 500, fy, fy - lab[..., 2] / 200], -1)
    xyz = np.where(f > 6 / 29, f ** 3, 3 * (6 / 29) ** 2 * (f - 4 / 29)) * _WHITE
    return _to_srgb(xyz @ np.linalg.inv(_M).T).astype(np.float32)


def _sample_lab(samples: list[np.ndarray]) -> np.ndarray:
    """Pooled Lab pixels of the delit samples, without the darkest and brightest 3% (shadows,
    specular glints)."""
    pix = np.concatenate([srgb_to_lab(delight.delight(s)).reshape(-1, 3) for s in samples])
    lo, hi = np.percentile(pix[:, 0], [3, 97])
    return pix[(pix[:, 0] >= lo) & (pix[:, 0] <= hi)]


def delta_e(img: np.ndarray, samples: list[np.ndarray]) -> float:
    a = srgb_to_lab(img).reshape(-1, 3).mean(0)
    return float(np.linalg.norm(a - _sample_lab(samples).mean(0)))


def match_to_samples(albedo: np.ndarray, samples: list[np.ndarray], spread: float = 0.5,
                     strength: tuple[float, float, float] = (0.6, 0.9, 0.9)) -> tuple[np.ndarray, dict]:
    """Shift the albedo's Lab mean onto the samples', and its spread `spread` of the way.

    Lightness moves less than hue (strength per L, a, b): a sample in shadow or an exposure
    choice says little about the surface's true value, much more about its colour."""
    if not samples:
        return albedo, {}
    target = _sample_lab(samples)
    lab = srgb_to_lab(albedo)
    flat = lab.reshape(-1, 3)
    mean, std = flat.mean(0), flat.std(0) + 1e-6
    t_mean, t_std = target.mean(0), target.std(0) + 1e-6
    ratio = np.clip(1 + spread * (t_std / std - 1), 0.6, 1.6)
    matched = (lab - mean) * ratio + t_mean
    out = lab_to_srgb(lab + np.asarray(strength) * (matched - lab))
    before = float(np.linalg.norm(mean - t_mean))
    after = float(np.linalg.norm(srgb_to_lab(out).reshape(-1, 3).mean(0) - t_mean))
    return out, {"delta_e_before": round(before, 1), "delta_e_after": round(after, 1)}
