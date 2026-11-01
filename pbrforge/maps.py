"""Derive PBR maps from a tileable albedo. Every filter wraps so the maps tile like the albedo."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from . import detail, filters, io
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
    normal_strength: float = 1.0  # times MACRO_GAIN; calibrated on Bricks113A against its NormalGL
    detail: float = 1.0  # scales the fine bands
    detail_kind: str = "none"  # procedural detail layer, see detail.py
    detail_strength: float = 0.5
    detail_repeats: int = 8  # detail tiles per texture side
    wear: float = 0.0  # 0 new .. 1 heavily worn: lighter smoother edges, dirt in cavities
    directx_normal: bool = False


def joint_polarity(albedo: np.ndarray) -> int:
    """+1 when thin joints (mortar, grout, gaps) are darker than the surface, -1 when lighter."""
    lum = luminance(albedo)
    n = lum.shape[0]
    small = filters.blur(lum, n / 1024)
    size = max(5, n // 64)
    dark = ndimage.black_tophat(small, size=size, mode="wrap").mean()
    light = ndimage.white_tophat(small, size=size, mode="wrap").mean()
    return 1 if dark >= light else -1


def height(albedo: np.ndarray, detail: float = 1.0, guide: np.ndarray | None = None) -> np.ndarray:
    """Height map. `guide` is a height painted by Muse Image from the albedo (r=0.67 against the
    reference displacement, vs 0.24 for luminance alone); the luminance bands add fine grain.
    Without a guide (offline), luminance with automatic joint polarity."""
    fine = _luminance_height(albedo, detail, joint_polarity(albedo))
    if guide is None:
        return fine
    # Muse's fine relief is plausible but not pixel-exact: keep its shapes, drop its grain.
    g = filters.blur(guide, guide.shape[0] / 341)
    g = g - g.min()
    g = g / (g.max() + 1e-9)
    h = 0.85 * g + 0.15 * fine
    return ((h - h.min()) / (h.max() - h.min() + 1e-9)).astype(np.float32)


def _luminance_height(albedo: np.ndarray, detail: float, polarity: int) -> np.ndarray:
    lum = luminance(albedo).astype(np.float64)
    if polarity < 0:
        lum = 1 - lum
    scale = lum.shape[0] / 1024  # keep the same look at every resolution
    h = np.zeros_like(lum)
    prev = lum
    for i, (s, wgt) in enumerate(zip(_SIGMAS, _WEIGHTS)):
        blurred = filters.blur(lum, s * scale)
        band = prev - blurred
        h += band * wgt * (detail if i < 2 else 1.0)
        prev = blurred
    h -= h.min()
    return (h / (h.max() + 1e-9)).astype(np.float32)


def normal(h: np.ndarray, strength: float = 1.0, directx: bool = False) -> np.ndarray:
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


# Calibrated on Bricks113A against its NormalGL (scripts/bench_baseline.py): the macro relief alone
# matched the reference's structure (r=0.52) but had a third of its fine detail, so faces read
# smooth. Micro detail from the albedo brings it to 80% for nearly the same structure (r=0.50).
MACRO_GAIN = 1.6
MICRO_STRENGTH = 0.08


def micro_height(albedo: np.ndarray, polarity: int) -> np.ndarray:
    """Fine relief from the albedo's high band: pores, chisel marks, grain. Exactly aligned with
    the colour, unlike any painted height. Signed, about -1..1."""
    lum = luminance(albedo).astype(np.float32)
    if polarity < 0:
        lum = 1 - lum
    band = lum - filters.blur(lum, 6 * lum.shape[0] / 1024)
    return band / (np.percentile(np.abs(band), 99.5) + 1e-6)


def blend_normals(base: np.ndarray, detail: np.ndarray) -> np.ndarray:
    """Reoriented Normal Mapping (Barré-Brisebois & Hill): the detail normal is rotated onto the
    base one instead of added, so detail follows the slopes of the macro relief."""
    t = base * 2 - 1
    t[..., 2] += 1
    u = detail * 2 - 1
    u[..., :2] *= -1
    r = t * (t * u).sum(-1, keepdims=True) / t[..., 2:3] - u
    r /= np.linalg.norm(r, axis=-1, keepdims=True)
    return (r * 0.5 + 0.5).astype(np.float32)


def studio_normal(h: np.ndarray, albedo: np.ndarray, strength: float = 1.0, detail: float = 1.0,
                  directx: bool = False) -> np.ndarray:
    """Macro normal from the height, micro normal from the albedo, blended with RNM."""
    base = normal(h, strength * MACRO_GAIN)
    micro = normal(micro_height(albedo, joint_polarity(albedo)), MICRO_STRENGTH * detail)
    n = blend_normals(base, micro)
    if directx:
        n[..., 1] = 1 - n[..., 1]
    return n


def ambient_occlusion(h: np.ndarray, strength: float = 1.2) -> np.ndarray:
    """Cavity AO: how far below its neighbourhood each texel sits, over a few radii."""
    scale = h.shape[0] / 1024
    occ = np.zeros_like(h)
    for s in (4, 12, 32):
        occ += np.clip(filters.blur(h, s * scale) - h, 0, None)
    occ /= np.percentile(occ, 99) + 1e-6
    return np.clip(1 - occ * strength * 0.5, 0, 1).astype(np.float32)


def roughness(albedo: np.ndarray, h: np.ndarray, p: MapParams) -> np.ndarray:
    """Base roughness from the plan; cavities rougher, raised worn areas slightly smoother."""
    hp = h - filters.blur(h, h.shape[0] / 64)
    hp /= np.abs(hp).max() + 1e-6
    r = p.roughness - hp * p.roughness_variation * 0.5
    return np.clip(r, 0.02, 1).astype(np.float32)


def metallic(albedo: np.ndarray, p: MapParams) -> np.ndarray:
    if not p.metal_on_desaturated or p.metallic <= 0:
        return np.full(albedo.shape[:2], p.metallic, np.float32)
    mx, mn = albedo.max(axis=-1), albedo.min(axis=-1)
    sat = (mx - mn) / (mx + 1e-4)
    bare = 1 - np.clip((sat - 0.15) / 0.2, 0, 1)  # grey -> metal, orange rust -> dielectric
    bare = filters.blur(bare, 1.5)
    return (bare * p.metallic).astype(np.float32)


DETAIL_GAIN = 0.35  # detail normal strength at detail_strength = 1


def grain_along_x(albedo: np.ndarray) -> np.ndarray:
    """0..1 per pixel, 1 where the grain runs along X (structure tensor: grain along X means the
    luminance changes mostly along Y). Smoothed over about a board width."""
    lum = luminance(albedo)
    gx = np.roll(lum, -1, axis=1) - np.roll(lum, 1, axis=1)
    gy = np.roll(lum, -1, axis=0) - np.roll(lum, 1, axis=0)
    sigma = albedo.shape[0] / 64
    jxx, jyy = filters.blur(gx * gx, sigma), filters.blur(gy * gy, sigma)
    w = jyy / (jxx + jyy + 1e-9)
    return np.clip((w - 0.5) * 3 + 0.5, 0, 1).astype(np.float32)  # sharpen toward 0 or 1


def edge_wear(h: np.ndarray, ao: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(edges, cavities) masks, 0..1: convex rims that rub and wear, recesses where dirt settles."""
    scale = h.shape[0] / 1024
    curv = filters.blur(h, 2 * scale) - filters.blur(h, 10 * scale)
    edges = np.clip(curv / (np.percentile(curv, 97) + 1e-6), 0, 1)
    cavities = np.clip((1 - ao) * 1.5, 0, 1)
    return edges.astype(np.float32), cavities.astype(np.float32)


def apply_wear(albedo: np.ndarray, rough: np.ndarray, h: np.ndarray, ao: np.ndarray,
               wear: float) -> tuple[np.ndarray, np.ndarray]:
    """Worn edges: lighter, less saturated, smoother. Cavities: darker and rougher."""
    if wear <= 0:
        return albedo, rough
    edges, cavities = edge_wear(h, ao)
    e = (edges * wear * 0.5)[..., None]
    c = (cavities * wear * 0.35)[..., None]
    grey = albedo.mean(axis=-1, keepdims=True)
    worn = albedo * (1 - e) + (0.6 * albedo + 0.4 * grey + 0.12) * e
    worn = worn * (1 - c * 0.6)
    rough = rough - edges * wear * 0.18 + cavities * wear * 0.1
    return np.clip(worn, 0, 1).astype(np.float32), np.clip(rough, 0.02, 1).astype(np.float32)


def derive(albedo: np.ndarray, p: MapParams | None = None, size: int | None = None,
           height_guide: np.ndarray | None = None) -> dict[str, np.ndarray]:
    """All maps at `size` (default: albedo size). Maps are computed at the target size, so the
    procedural detail layer is at full resolution in every export."""
    p = p or MapParams()
    if size:
        albedo = io.resize(albedo, size).clip(0, 1)
    if height_guide is not None:
        height_guide = io.resize(height_guide, albedo.shape[0])
    h = height(albedo, p.detail, height_guide) * p.height_strength
    ao = ambient_occlusion(h)
    rough = roughness(albedo, h, p)
    metal = metallic(albedo, p)
    n = studio_normal(h, albedo, p.normal_strength, p.detail)
    if p.detail_kind in detail.KINDS and p.detail_kind != "none" and p.detail_strength > 0:
        dh = detail.detail_tiled(p.detail_kind, albedo.shape[0], p.detail_repeats)
        if p.detail_kind in detail.ORIENTED:
            # Fibres follow the grain: blend the detail and its transpose by the local orientation.
            along_x = grain_along_x(albedo)
            dh = along_x * dh + (1 - along_x) * dh.T
        k = detail.KIND_GAIN[p.detail_kind] * p.detail_strength
        n = blend_normals(n, normal(dh * 0.5 + 0.5, DETAIL_GAIN * k))
        rough = np.clip(rough + dh * 0.05 * k, 0.02, 1).astype(np.float32)
    albedo, rough = apply_wear(albedo, rough, h, ao, p.wear)
    if p.directx_normal:
        n[..., 1] = 1 - n[..., 1]
    return {
        "albedo": albedo,
        "height": h,
        "normal": n,
        "ao": ao,
        "roughness": rough,
        "metallic": metal,
        "orm": np.stack([ao, rough, metal], axis=-1),
    }
