"""Fast periodic filters. Large Gaussian blurs are done in the Fourier domain: exact on a torus
(which is what a tiling texture is) and the same cost whatever the sigma."""
from __future__ import annotations

import numpy as np
from scipy import ndimage

_cache: dict[tuple, np.ndarray] = {}


def _kernel(h: int, w: int, sigma: float) -> np.ndarray:
    key = (h, w, round(sigma, 3))
    if key not in _cache:
        fy = np.fft.fftfreq(h)[:, None]
        fx = np.fft.rfftfreq(w)[None, :]
        _cache[key] = np.exp(-2 * np.pi**2 * sigma**2 * (fx**2 + fy**2))
        if len(_cache) > 32:
            _cache.pop(next(iter(_cache)))
    return _cache[key]


def blur(img: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian blur with wrap-around borders, per channel."""
    if sigma < 3:
        s = (sigma, sigma, 0) if img.ndim == 3 else sigma
        return ndimage.gaussian_filter(img, s, mode="wrap")
    h, w = img.shape[:2]
    k = _kernel(h, w, sigma)
    if img.ndim == 2:
        return np.fft.irfft2(np.fft.rfft2(img) * k, s=(h, w)).astype(np.float32)
    f = np.fft.rfft2(img, axes=(0, 1))
    return np.fft.irfft2(f * k[..., None], s=(h, w), axes=(0, 1)).astype(np.float32)
