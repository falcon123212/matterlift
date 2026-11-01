import time

import numpy as np
import pytest
from scipy import ndimage

from pbrforge import delight, maps, metrics, seamless


def _noise(n=256, seed=0, sigma=3.0):
    rng = np.random.default_rng(seed)
    img = np.stack([ndimage.gaussian_filter(rng.random((n, n)), sigma, mode="wrap") for _ in range(3)], -1)
    img -= img.min()
    return (img / img.max() * 0.6 + 0.2).astype(np.float32)


@pytest.fixture
def broken_wrap():
    """Smooth noise with a strong left/right and top/bottom discontinuity."""
    img = _noise()
    ramp = np.linspace(0, 0.3, img.shape[1], dtype=np.float32)
    return np.clip(img + ramp[None, :, None] + ramp[:, None, None], 0, 1)


def test_seam_score_detects_and_make_tileable_fixes(broken_wrap):
    before = metrics.seam_score(broken_wrap)
    after = metrics.seam_score(seamless.make_tileable(broken_wrap))
    assert before > 3
    assert after < 1.6


def test_tileable_noise_scores_near_one():
    assert metrics.seam_score(_noise()) < 1.5


def test_detect_and_crop_period():
    tile = _noise(200)
    big = np.tile(tile, (2, 2, 1))
    assert metrics.detect_period(big) == (200, 200)
    assert seamless.crop_period(big).shape == (200, 200, 3)
    assert metrics.detect_period(_noise(400, seed=3)) is None


def test_fix_blocks_removes_grid_line():
    img = _noise()
    img[:, 128:] = np.clip(img[:, 128:] + 0.25, 0, 1)
    assert metrics.block_score(img) > 5
    assert metrics.block_score(seamless.fix_blocks(img)) < metrics.block_score(img) / 2


def test_suppress_singletons_reduces_salient_blob():
    img = _noise(256, sigma=1.5)
    yy, xx = np.mgrid[:256, :256]
    blob = (yy - 80) ** 2 + (xx - 90) ** 2 < 15**2
    img[blob] = [0.1, 0.7, 0.1]  # green moss patch
    before = metrics.repetition_score(img)
    out, touched = seamless.suppress_singletons(img)
    assert touched > 0
    assert metrics.repetition_score(out) < before


def test_delight_flattens_vignette():
    img = _noise()
    yy, xx = np.mgrid[:256, :256] / 255.0
    lit = img * (0.5 + 0.5 * xx)[..., None]
    low = lambda a: ndimage.gaussian_filter(metrics.luminance(a), 32, mode="wrap")  # noqa: E731
    assert low(delight.delight(lit)).std() < low(lit).std() / 2


def test_maps_tile_and_have_valid_ranges():
    m = maps.derive(_noise(), maps.MapParams(metallic=0.8, metal_on_desaturated=True))
    for name, a in m.items():
        assert a.min() >= 0 and a.max() <= 1, name
    # Wrapping filters: a map rolled by half must still be seamless.
    for name in ("height", "normal", "ao", "roughness"):
        assert metrics.seam_score(m[name]) < 1.6, name
    n = m["normal"] * 2 - 1
    assert np.allclose(np.linalg.norm(n, axis=-1), 1, atol=0.02)


def test_derive_1024_under_4s():
    img = _noise(1024)
    t = time.perf_counter()
    maps.derive(img)
    assert time.perf_counter() - t < 4.0


def test_fix_albedo_squares_a_wide_image():
    from pbrforge import fix_albedo

    wide = np.concatenate([_noise(256, seed=1), _noise(256, seed=2)], axis=1)
    out, _ = fix_albedo(wide)
    assert out.shape[0] == out.shape[1]
