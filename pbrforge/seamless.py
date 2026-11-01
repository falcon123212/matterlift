"""Make a texture tile: remove internal repetition, cut seamless wraps, fix grid lines, tame singletons."""
from __future__ import annotations

import numpy as np
from scipy import ndimage

from . import filters, metrics


def crop_period(img: np.ndarray, min_frac: float = 0.45) -> np.ndarray:
    """Keep one period when the source repeats itself, as a square tile.

    Only long periods count: a short one (planks, bricks, grain) is the pattern itself.
    """
    period = metrics.detect_period(img)
    if period is None:
        return img
    h, w = img.shape[:2]
    px, py = (p if p and p >= min_frac * n else None for p, n in zip(period, (w, h)))
    if px is None and py is None:
        return img
    side = min(px or w, py or h)
    return img[:side, :side]


def periodic_component(img: np.ndarray, blur_frac: float = 1 / 48) -> np.ndarray:
    """Moisan's periodic + smooth decomposition: subtract the smooth field that causes the
    edge mismatch (lighting gradients, colour drift), leaving detail untouched.

    The smooth field is solved on a blurred copy so a feature lying on the border (a dark plank
    gap along row 0) is not mistaken for a mismatch and smeared over the whole tile.
    """
    h, w = img.shape[:2]
    sigma = max(h, w) * blur_frac
    # Blur at 1/8 resolution (fast; borders clamp, not wrap) and bring back to full size.
    f = int(np.clip(sigma / 4, 1, 8))
    zoom = (1 / f, 1 / f, 1) if img.ndim == 3 else (1 / f, 1 / f)
    # mode="nearest" matters: zoom's default pads with zeros, which made the last row and column
    # black and the smooth field then "fixed" that fake mismatch with a ramp over the whole tile.
    small = ndimage.zoom(img, zoom, order=1, mode="nearest")
    small = ndimage.gaussian_filter(small, (sigma / f, sigma / f, 0) if img.ndim == 3 else sigma / f,
                                    mode="nearest")
    back = tuple(t / s for t, s in zip(img.shape, small.shape))
    blurred = ndimage.zoom(small, back, order=1, mode="nearest")[:h, :w]
    chans = [blurred] if img.ndim == 2 else [blurred[..., c] for c in range(img.shape[2])]
    q = np.arange(h)[:, None]
    r = np.arange(w)[None, :]
    denom = 2 * np.cos(2 * np.pi * q / h) + 2 * np.cos(2 * np.pi * r / w) - 4
    denom[0, 0] = 1.0
    out = []
    for u in chans:
        u = u.astype(np.float64)
        v = np.zeros_like(u)
        v[0, :] += u[-1, :] - u[0, :]
        v[-1, :] += u[0, :] - u[-1, :]
        v[:, 0] += u[:, -1] - u[:, 0]
        v[:, -1] += u[:, 0] - u[:, -1]
        s_hat = np.fft.fft2(v) / denom
        s_hat[0, 0] = 0
        out.append(np.real(np.fft.ifft2(s_hat)))
    smooth = out[0] if img.ndim == 2 else np.stack(out, -1)
    return np.clip(img - smooth, 0, 1).astype(np.float32)


def _min_cut(err: np.ndarray) -> np.ndarray:
    """Vertical minimum-error path through err (H, B). Returns the cut column for each row."""
    h, b = err.shape
    cost = err.copy()
    for y in range(1, h):
        prev = cost[y - 1]
        left = np.r_[np.inf, prev[:-1]]
        right = np.r_[prev[1:], np.inf]
        cost[y] += np.minimum(np.minimum(left, prev), right)
    path = np.empty(h, dtype=int)
    path[-1] = int(np.argmin(cost[-1]))
    for y in range(h - 2, -1, -1):
        x = path[y + 1]
        lo, hi = max(0, x - 1), min(b, x + 2)
        path[y] = lo + int(np.argmin(cost[y, lo:hi]))
    return path


def _path_cost(err: np.ndarray) -> float:
    """Mean error along the best vertical cut through err (H, B)."""
    cost = err[0].copy()
    for y in range(1, err.shape[0]):
        left = np.r_[np.inf, cost[:-1]]
        right = np.r_[cost[1:], np.inf]
        cost = err[y] + np.minimum(np.minimum(left, cost), right)
    return float(cost.min() / err.shape[0])


def _cut_costs(img: np.ndarray, band: int, ts: list[int]) -> list[float]:
    out = []
    for t in ts:
        d = img[:, :band] - img[:, t : t + band]
        out.append(_path_cost((d**2).sum(axis=-1) if d.ndim == 3 else d**2))
    return out


def best_tile_size(img: np.ndarray, band: int, min_frac: float = 0.6, size_penalty: float = 0.6) -> int:
    """The square tile size T whose two wrap cuts are least visible.

    The cut blends the first `band` columns with columns T..T+band; with a fixed T = N - band they
    can be unrelated (a light board against a dark one) and even the best cut shows. Searching T
    finds where the image nearly repeats itself (plank joints lining up), at a small cost in size.
    One T for both axes keeps the tile square.
    """
    n = min(img.shape[:2])
    f = max(1, n // 192)
    small = img[:n:f, :n:f]
    sb = max(2, band // f)
    t_max = small.shape[1] - sb
    ts = list(range(int(small.shape[1] * min_frac), t_max + 1, max(1, small.shape[1] // 160)))
    cx = _cut_costs(small, sb, ts)
    cy = _cut_costs(np.swapaxes(small, 0, 1), sb, ts)
    scores = [(a + b) * (1 + size_penalty * (1 - t / t_max)) for a, b, t in zip(cx, cy, ts)]
    return min(n - band, ts[int(np.argmin(scores))] * f)


def _wrap_x(img: np.ndarray, band: int, feather: float, t: int) -> np.ndarray:
    """Make the left/right wrap seamless (Efros-Freeman quilting).

    The new tile is img[:, :T]. Its first `band` columns are a mix of A = img[:, :band]
    (continues into the tile) and B = img[:, T:T+band] (the natural continuation of column T-1,
    so the wrap T-1 -> 0 is seamless). The boundary between B (left of the cut) and A (right of
    it) follows the path of least colour difference; T is chosen where that path is cheapest.
    """
    a, b = img[:, :band], img[:, t : t + band]
    err = ((a - b) ** 2).sum(axis=-1) if img.ndim == 3 else (a - b) ** 2
    err = ndimage.gaussian_filter(err, 1.0)
    path = _min_cut(err)
    cols = np.arange(band)[None, :]
    mask = (cols >= path[:, None]).astype(np.float32)  # 1 = take A
    if feather > 0:
        mask = ndimage.gaussian_filter(mask, feather, mode="nearest")
    if img.ndim == 3:
        mask = mask[..., None]
    out = img[:, :t].copy()
    out[:, :band] = mask * a + (1 - mask) * b
    return out


def make_tileable(img: np.ndarray, band_frac: float = 0.08, feather: float = 1.5) -> np.ndarray:
    """Low-frequency mismatch goes first (periodic component), then structure (minimum cut)."""
    band = max(8, int(min(img.shape[:2]) * band_frac))
    img = periodic_component(img)
    t = best_tile_size(img, band)
    out = _wrap_x(img[: t + band, : t + band], band, feather, t)
    out = np.swapaxes(_wrap_x(np.swapaxes(out, 0, 1), band, feather, t), 0, 1)
    return np.ascontiguousarray(out)


def fix_blocks(img: np.ndarray, ratio: float = 3.0, half_width: int = 12) -> np.ndarray:
    """Remove straight colour steps inside the tile (grid lines) with a smooth ramp correction."""
    out = img.copy()
    for axis_swap in (False, True):
        a = np.swapaxes(out, 0, 1) if axis_swap else out
        steps = metrics._col_steps(a)[:-1]
        med = np.median(steps) + 1e-6
        w = a.shape[1]
        for x in np.where(steps > ratio * med)[0]:
            if x < half_width or x + half_width + 1 >= w:
                continue
            left = a[:, x - 2 : x + 1].mean(axis=1)
            right = a[:, x + 1 : x + 4].mean(axis=1)
            step = ndimage.gaussian_filter1d(right - left, 4, axis=0, mode="wrap")
            ramp = np.linspace(-0.5, 0.5, 2 * half_width)
            for i, r in enumerate(ramp):
                col = x - half_width + 1 + i
                weight = (0.5 - abs(r)) * 2  # 0 at band edges, 1 at the step
                sign = -0.5 if col > x else 0.5
                a[:, col] += sign * step * weight
        out = np.swapaxes(a, 0, 1) if axis_swap else a
    return np.clip(out, 0, 1)


def suppress_singletons(img: np.ndarray, strength: float = 0.8) -> tuple[np.ndarray, float]:
    """Pull salient blobs (the moss patch that forms a grid when tiled) toward their surroundings.

    Returns the new image and the share of pixels touched, in percent.
    """
    mask = metrics.salient_mask(img)
    if not mask.any():
        return img, 0.0
    soft = filters.blur(mask.astype(np.float32), 3)[..., None] * strength
    sigma = max(img.shape[:2]) / 24
    local = filters.blur(img, sigma)
    # Keep the blob's fine detail, replace its colour offset.
    detail = img - filters.blur(img, 3)
    out = img * (1 - soft) + (local + detail) * soft
    return np.clip(out, 0, 1), float(mask.mean() * 100)
