"""Image I/O. Internally every map is float32 in [0, 1], shape (H, W) or (H, W, 3)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


def from_pil(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0


def to_pil(arr: np.ndarray) -> Image.Image:
    a = np.clip(arr, 0.0, 1.0)
    return Image.fromarray((a * 255.0 + 0.5).astype(np.uint8))


def load(path: str | Path) -> np.ndarray:
    return from_pil(Image.open(path))


def save(path: str | Path, arr: np.ndarray, bits: int = 8) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    a = np.clip(arr, 0.0, 1.0)
    if bits == 16:
        if a.ndim != 2:
            raise ValueError("16-bit output is only supported for single-channel maps")
        Image.fromarray((a * 65535.0 + 0.5).astype(np.uint16)).save(path)
    else:
        to_pil(a).save(path)


def resize(arr: np.ndarray, size: int) -> np.ndarray:
    """Lanczos resize of a square map, channel by channel in float."""
    if arr.shape[0] == size and arr.shape[1] == size:
        return arr
    chans = [arr] if arr.ndim == 2 else [arr[..., c] for c in range(arr.shape[2])]
    out = [
        np.asarray(Image.fromarray(c.astype(np.float32), mode="F").resize((size, size), Image.LANCZOS))
        for c in chans
    ]
    return out[0] if arr.ndim == 2 else np.stack(out, axis=-1)
