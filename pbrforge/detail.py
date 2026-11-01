"""Procedural detail layer: the micro relief a studio adds on top of a scanned or painted material.

Each kind is a periodic height field (noise shaped in the Fourier domain, so it tiles exactly),
repeated many times across the texture. It is computed at the export resolution, so a 4K export
gets real 4K micro detail even though Muse paints 1600 px. Kinds:

wood     long fibres along X with pores
stone    multi-octave grit and small pits
fabric   a plain weave
metal    brushed lines along X and a few scratches
plaster  soft trowel undulation with fine sand
"""
from __future__ import annotations

import numpy as np

KINDS = ("none", "wood", "stone", "fabric", "metal", "plaster")

# Name fragments -> kind, for plans that do not say (English and French).
_HINTS = {
    "wood": ("wood", "oak", "walnut", "pine", "plank", "bois", "chene", "chêne", "noyer", "parquet", "bamboo"),
    "stone": ("stone", "brick", "concrete", "marble", "granite", "tile", "terracotta", "flagstone", "rock",
              "pierre", "brique", "béton", "beton", "marbre", "carrelage", "dalle", "slate", "cobble"),
    "fabric": ("fabric", "linen", "cotton", "cloth", "wool", "canvas", "rush", "weave", "wicker", "rattan",
               "tissu", "lin", "toile", "laine", "osier", "denim", "velvet"),
    "metal": ("metal", "steel", "iron", "copper", "brass", "aluminium", "aluminum", "chrome", "rust",
              "métal", "acier", "fer", "cuivre", "laiton", "rouille"),
    "plaster": ("plaster", "stucco", "paint", "wall", "lime", "render", "plâtre", "platre", "enduit", "mur"),
}


# Relative strength per kind: woven or brushed detail reads strong, keep it lighter.
KIND_GAIN = {"wood": 1.0, "stone": 1.0, "fabric": 0.5, "metal": 0.6, "plaster": 0.8, "none": 0.0}


def infer_kind(*texts: str) -> str:
    t = " ".join(texts).lower().replace("_", " ")
    for kind, words in _HINTS.items():
        if any(w in t for w in words):
            return kind
    return "stone"


def _spectral_noise(n: int, rng: np.random.Generator, power: float, aniso: float = 1.0,
                    band: tuple[float, float] = (0.0, 1.0)) -> np.ndarray:
    """Periodic noise with a 1/f^power spectrum; aniso > 1 stretches it along X."""
    fy = np.fft.fftfreq(n)[:, None]
    fx = np.fft.rfftfreq(n)[None, :]
    f = np.sqrt((fx * aniso) ** 2 + fy**2)
    f[0, 0] = 1.0
    amp = f ** (-power)
    lo, hi = band
    amp *= (f >= lo * 0.5) & (f <= hi * 0.5)
    amp[0, 0] = 0.0
    phase = rng.random(amp.shape) * 2 * np.pi
    h = np.fft.irfft2(amp * np.exp(1j * phase), s=(n, n))
    return h / (np.abs(h).max() + 1e-9)


def detail_height(kind: str, n: int = 256, seed: int = 7) -> np.ndarray:
    """One tile of the detail height, about -1..1, periodic."""
    rng = np.random.default_rng(seed)
    if kind == "wood":
        fibres = _spectral_noise(n, rng, 1.2, aniso=14.0)
        pores = _spectral_noise(n, rng, 0.2, aniso=4.0, band=(0.25, 1.0))
        h = fibres + 0.5 * np.minimum(pores, 0)
    elif kind == "stone":
        grit = _spectral_noise(n, rng, 1.0)
        pits = _spectral_noise(n, rng, 0.5, band=(0.1, 0.6))
        h = grit - 0.8 * np.clip(pits - 0.45, 0, None) * 4
    elif kind == "fabric":
        # Fine fuzz and stray fibres only: the weave itself is already in the albedo, and a second
        # procedural weave fights it.
        fuzz = _spectral_noise(n, rng, 0.4, band=(0.3, 1.0))
        fibres = _spectral_noise(n, rng, 0.9, aniso=6.0, band=(0.1, 1.0))
        h = 0.6 * fuzz + 0.4 * fibres
    elif kind == "metal":
        brushed = _spectral_noise(n, rng, 0.6, aniso=40.0)
        scratches = np.zeros((n, n))
        xs = np.arange(n)
        for _ in range(4):
            # Wavy, mostly horizontal; a whole number of waves per tile so they meet over the wrap.
            y0, waves = rng.integers(0, n), int(rng.integers(1, 3))
            amp, phase = rng.uniform(0.02, 0.08) * n, rng.uniform(0, 2 * np.pi)
            ys = (y0 + amp * np.sin(2 * np.pi * waves * xs / n + phase)).astype(int) % n
            scratches[ys, xs] = -0.5
        h = brushed + scratches
    elif kind == "plaster":
        h = _spectral_noise(n, rng, 1.6) + 0.35 * _spectral_noise(n, rng, 0.3, band=(0.3, 1.0))
    else:
        return np.zeros((n, n), np.float32)
    h = h - h.mean()
    return (h / (np.abs(h).max() + 1e-9)).astype(np.float32)


def detail_tiled(kind: str, size: int, repeats: int) -> np.ndarray:
    """The detail height across a size x size texture, `repeats` tiles per side (tiles with it)."""
    repeats = max(1, int(repeats))
    tile = max(32, size // repeats)
    h = np.tile(detail_height(kind, tile), (repeats, repeats))
    if h.shape[0] != size:
        from . import io

        h = io.resize(h, size)
    return h.astype(np.float32)
