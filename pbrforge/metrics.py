"""Automatic judges for a texture: seams, grid blocks, internal period, salient singletons, PBR range."""
from __future__ import annotations

import numpy as np
from scipy import ndimage

from . import filters


def luminance(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    return img[..., 0] * 0.2126 + img[..., 1] * 0.7152 + img[..., 2] * 0.0722


def _col_steps(img: np.ndarray) -> np.ndarray:
    """Mean absolute step between column x and x+1 (wrapping), per x."""
    d = np.abs(np.roll(img, -1, axis=1) - img)
    return d.mean(axis=tuple(i for i in range(d.ndim) if i != 1))


def seam_score(img: np.ndarray) -> float:
    """Wrap-around step relative to the typical interior step. ~1 = invisible seam, >2 = visible."""
    scores = []
    for a in (img, np.swapaxes(img, 0, 1)):
        steps = _col_steps(a)
        scores.append(steps[-1] / (np.median(steps[:-1]) + 1e-6))
    return float(max(scores))


def block_score(img: np.ndarray) -> float:
    """Strongest interior straight line of discontinuity (grid seams inside the tile)."""
    scores = []
    for a in (img, np.swapaxes(img, 0, 1)):
        steps = _col_steps(a)[:-1]
        scores.append(steps.max() / (np.median(steps) + 1e-6))
    return float(max(scores))


def detect_period(img: np.ndarray, min_corr: float = 0.4) -> tuple[int | None, int | None] | None:
    """Detect an internal repetition (e.g. Muse returning a 2x2 copy of one tile).

    Returns (period_x, period_y) per axis with a lag in [N/4, 3N/4]; an axis without a clear
    repetition is None, and None overall when neither axis repeats. Muse Image 1.0 typically
    repeats strongly along x (~0.8) and partially along y (~0.5).
    """
    lum = luminance(img).astype(np.float64)
    lum = lum - filters.blur(lum, max(lum.shape) / 32)
    f = np.fft.rfft2(lum)
    ac = np.fft.irfft2(f * np.conj(f), s=lum.shape)
    ac /= ac[0, 0] + 1e-12
    h, w = lum.shape
    periods = []
    for profile, n in ((ac[0, :], w), (ac[:, 0], h)):
        lo, hi = n // 4, (3 * n) // 4
        lag = lo + int(np.argmax(profile[lo:hi]))
        periods.append(lag if profile[lag] >= min_corr else None)
    if periods == [None, None]:
        return None
    return periods[0], periods[1]


def salient_mask(img: np.ndarray, k: float = 3.5) -> np.ndarray:
    """Pixels whose colour stands out from the local surroundings (moss patches, stains, logos)."""
    sigma = max(img.shape[:2]) / 24
    local = filters.blur(img, sigma)
    dev = np.linalg.norm(img - local, axis=-1)
    dev = filters.blur(dev, 2)
    thresh = np.median(dev) + k * 1.4826 * np.median(np.abs(dev - np.median(dev)))
    mask = dev > thresh
    # Only blobs count as singletons, not scattered speckle.
    return ndimage.binary_opening(mask, iterations=2)


def repetition_score(img: np.ndarray) -> float:
    """Share of the tile covered by salient blobs, in percent. Above ~1.5% the grid shows when tiled."""
    return float(salient_mask(img).mean() * 100.0)


def albedo_out_of_range(img: np.ndarray, lo: float = 30 / 255, hi: float = 240 / 255) -> float:
    """Percent of pixels outside the plausible PBR albedo range (sRGB)."""
    lum = luminance(img)
    return float(((lum < lo) | (lum > hi)).mean() * 100.0)


def report(img: np.ndarray) -> dict:
    return {
        "seam": round(seam_score(img), 2),
        "blocks": round(block_score(img), 2),
        "repetition": round(repetition_score(img), 2),
        "albedo_out_of_range": round(albedo_out_of_range(img), 2),
        "period": detect_period(img),
    }
