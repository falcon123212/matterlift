"""Derive PBR maps from a tileable albedo. Every filter wraps so the maps tile like the albedo."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from . import io
from .metrics import luminance

# Weight per band, fine -> coarse. Low frequencies dominate: the stone shape, not its speckle,
# makes the relief. Equal weights give the crinkled look of the first Muse test.
_SIGMAS = (1, 2, 4, 8, 16, 32)
_WEIGHTS = (0.08, 0.15, 0.35, 0.7, 1.0, 1.0)


@dataclass
class MapParams:
    roughness: float = 0.7
    roughness_variation: float = 0.25
    metallic: float = 0.0
    metal_on_desaturated: bool = False  # rusty metal: bare metal where colour is grey
    height_strength: float = 1.0
    normal_strength: float = 4.0
    detail: float = 1.0  # scales the fine bands
    directx_normal: bool = False


def height(albedo: np.ndarray, detail: float = 1.0) -> np.ndarray:
    lum = luminance(albedo).astype(np.float64)
    scale = lum.shape[0] / 1024  # keep the same look at every resolution
    h = np.zeros_like(lum)
    prev = lum
    for i, (s, wgt) in enumerate(zip(_SIGMAS, _WEIGHTS)):
        blurred = ndimage.gaussian_filter(lum, s * scale, mode="wrap")
        band = prev - blurred
        h += band * wgt * (detail if i < 2 else 1.0)
        prev = blurred
    h -= h.min()
    return (h / (h.max() + 1e-9)).astype(np.float32)


def normal(h: np.ndarray, strength: float = 4.0, directx: bool = False) -> np.ndarray:
    """Tangent-space normal map, OpenGL convention (green = up) unless directx."""
    k = strength * h.shape[0] / 256
    dx = (np.roll(h, -1, axis=1) - np.roll(h, 1, axis=1)) * 0.5 * k
    dy = (np.roll(h, -1, axis=0) - np.roll(h, 1, axis=0)) * 0.5 * k
    nx, ny, nz = -dx, dy, np.ones_like(h)
    if directx:
        ny = -ny
    n = np.stack([nx, ny, nz], axis=-1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return (n * 0.5 + 0.5).astype(np.float32)


def ambient_occlusion(h: np.ndarray, strength: float = 1.2) -> np.ndarray:
    """Cavity AO: how far below its neighbourhood each texel sits, over a few radii."""
    scale = h.shape[0] / 1024
    occ = np.zeros_like(h)
    for s in (4, 12, 32):
        occ += np.clip(ndimage.gaussian_filter(h, s * scale, mode="wrap") - h, 0, None)
    occ /= np.percentile(occ, 99) + 1e-6
    return np.clip(1 - occ * strength * 0.5, 0, 1).astype(np.float32)


def roughness(albedo: np.ndarray, h: np.ndarray, p: MapParams) -> np.ndarray:
    """Base roughness from the plan; cavities rougher, raised worn areas slightly smoother."""
    hp = h - ndimage.gaussian_filter(h, h.shape[0] / 64, mode="wrap")
    hp /= np.abs(hp).max() + 1e-6
    r = p.roughness - hp * p.roughness_variation * 0.5
    return np.clip(r, 0.02, 1).astype(np.float32)


def metallic(albedo: np.ndarray, p: MapParams) -> np.ndarray:
    if not p.metal_on_desaturated or p.metallic <= 0:
        return np.full(albedo.shape[:2], p.metallic, np.float32)
    mx, mn = albedo.max(axis=-1), albedo.min(axis=-1)
    sat = (mx - mn) / (mx + 1e-4)
    bare = 1 - np.clip((sat - 0.15) / 0.2, 0, 1)  # grey -> metal, orange rust -> dielectric
    bare = ndimage.gaussian_filter(bare, 1.5, mode="wrap")
    return (bare * p.metallic).astype(np.float32)


def derive(albedo: np.ndarray, p: MapParams | None = None, size: int | None = None) -> dict[str, np.ndarray]:
    """All maps at `size` (default: albedo size). Maps are computed at the target size."""
    p = p or MapParams()
    if size:
        albedo = io.resize(albedo, size).clip(0, 1)
    h = height(albedo, p.detail) * p.height_strength
    ao = ambient_occlusion(h)
    rough = roughness(albedo, h, p)
    metal = metallic(albedo, p)
    return {
        "albedo": albedo,
        "height": h,
        "normal": normal(h, p.normal_strength, p.directx_normal),
        "ao": ao,
        "roughness": rough,
        "metallic": metal,
        "orm": np.stack([ao, rough, metal], axis=-1),
    }
