"""Contact sheets for judging a material: a lit sphere next to a 3x3 tiling (CPU, no GPU needed)."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from . import io


def _sample(tex: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    h, w = tex.shape[:2]
    x = (np.mod(u, 1.0) * w).astype(int) % w
    y = (np.mod(v, 1.0) * h).astype(int) % h
    return tex[y, x]


def render_sphere(maps: dict[str, np.ndarray], size: int = 512, tiles: float = 3.0,
                  light=(-0.8, 0.55, 0.35)) -> np.ndarray:
    """Sphere lit by a low key light (raking, to reveal relief) plus a soft ambient term."""
    # Poor man's mipmap: about one texel per pixel at the equator, so the sphere does not alias.
    texel = max(64, int(size * 1.2 / tiles))
    maps = {k: io.resize(v, texel).clip(0, 1) for k, v in maps.items() if k in
            ("albedo", "normal", "ao", "roughness", "metallic")}
    r = np.linspace(-1, 1, size)
    x, y = np.meshgrid(r, -r)
    inside = x**2 + y**2 <= 1
    z = np.sqrt(np.clip(1 - x**2 - y**2, 0, 1))
    phi = np.arctan2(x, z)
    theta = np.arccos(np.clip(y, -1, 1))
    u = (phi / (2 * np.pi) + 0.5) * tiles * 2
    v = theta / np.pi * tiles

    albedo = _sample(maps["albedo"], u, v)
    nmap = _sample(maps["normal"], u, v) * 2 - 1
    ao = _sample(maps["ao"], u, v)
    rough = _sample(maps["roughness"], u, v)
    metal = _sample(maps["metallic"], u, v)

    n = np.stack([x, y, z], -1)
    t = np.stack([np.cos(phi), np.zeros_like(phi), -np.sin(phi)], -1)  # d/du
    b = np.cross(n, t)  # points toward -v (up on the texture), matching OpenGL green-up
    pn = t * nmap[..., :1] + b * nmap[..., 1:2] + n * nmap[..., 2:3]
    pn /= np.linalg.norm(pn, axis=-1, keepdims=True) + 1e-9

    lv = np.array(light, dtype=np.float64)
    lv /= np.linalg.norm(lv)
    view = np.array([0.0, 0.0, 1.0])
    ndl = np.clip(pn @ lv, 0, 1)
    hv = (lv + view) / np.linalg.norm(lv + view)
    ndh = np.clip(pn @ hv, 0, 1)
    shininess = 2 / np.clip(rough, 0.05, 1) ** 4
    spec = ndh ** shininess * (1 - rough) ** 2
    f0 = 0.04 * (1 - metal)[..., None] + albedo * metal[..., None]
    diffuse = albedo * (1 - metal)[..., None]
    # Cheap sky reflection (bright above, dark below), blurred by roughness: without it bare metal,
    # which has no diffuse term, renders black.
    refl_y = 2 * (pn @ view)[..., None] * pn[..., 1:2] - view[1]
    sky = 0.25 + 0.75 * np.clip(refl_y * 0.5 + 0.5, 0, 1)
    env = (sky * (1 - 0.6 * rough[..., None]) + 0.35 * rough[..., None]) * ao[..., None]
    color = (diffuse * (ndl[..., None] * 1.1 + 0.18 * ao[..., None]) + f0 * spec[..., None] * 3
             + f0 * env * 0.9)
    color = color ** (1 / 1.4)
    bg = np.full_like(color, 0.08)
    return np.where(inside[..., None], np.clip(color, 0, 1), bg).astype(np.float32)


def tiled(albedo: np.ndarray, n: int = 3, size: int = 512) -> np.ndarray:
    small = io.resize(albedo, size // n).clip(0, 1)
    return np.tile(small, (n, n, 1))


def sheet(rows: list[tuple[str, dict[str, np.ndarray]]], size: int = 512) -> Image.Image:
    """One row per (label, maps): sphere | 3x3 tiling | normal map."""
    gap, label_h = 12, 28
    w = size * 3 + gap * 4
    h = len(rows) * (size + label_h + gap) + gap
    out = Image.new("RGB", (w, h), (20, 20, 22))
    draw = ImageDraw.Draw(out)
    for i, (label, maps) in enumerate(rows):
        y0 = gap + i * (size + label_h + gap)
        draw.text((gap, y0 + 6), label, fill=(230, 230, 230))
        tiles = [render_sphere(maps, size), tiled(maps["albedo"], 3, size),
                 io.resize(maps["normal"], size).clip(0, 1)]
        for j, t in enumerate(tiles):
            out.paste(io.to_pil(t), (gap + j * (size + gap), y0 + label_h))
    return out
