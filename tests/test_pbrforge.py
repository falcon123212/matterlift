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


def test_colour_match_moves_toward_samples():
    from pbrforge import color

    orange = np.zeros((128, 128, 3), np.float32) + [0.85, 0.45, 0.15]
    dusty = [np.zeros((64, 64, 3), np.float32) + [0.55, 0.35, 0.30]]
    out, rep = color.match_to_samples(orange + _noise(128) * 0.05, dusty)
    assert rep["delta_e_after"] < rep["delta_e_before"] / 2
    x = _noise(64)
    assert np.abs(color.lab_to_srgb(color.srgb_to_lab(x)) - x).max() < 1e-4


def test_periodic_component_adds_no_ramp_to_a_uniform_tile():
    """Regression: zoom padded with zeros and the 'fix' put a gradient over the whole tile."""
    img = _noise(720, seed=5) * 0.2 + 0.2  # dark, evenly lit, like walnut planks
    out = seamless.periodic_component(img)
    rows = metrics.luminance(out).mean(axis=1)
    assert rows.max() - rows.min() < 0.02


@pytest.mark.parametrize("kind", ["wood", "stone", "fabric", "metal", "plaster"])
def test_detail_layers_tile(kind):
    from pbrforge import detail

    h = detail.detail_tiled(kind, 512, 8)
    assert h.shape == (512, 512)
    # The wrap step must look like any interior step. (seam_score's ratio to the median is
    # unreliable here: brushed metal is nearly constant along rows, so each row step is a single
    # random draw.)
    for a in (h, h.T):
        steps = np.abs(np.roll(a, -1, axis=1) - a).mean(axis=0)
        assert steps[-1] <= steps[:-1].max() + 1e-6, kind


def test_detail_kind_inferred_from_names():
    from pbrforge import detail

    assert detail.infer_kind("vieux parquet de chêne") == "wood"
    assert detail.infer_kind("rusty steel") == "metal"
    assert detail.infer_kind("linen cloth") == "fabric"
    assert detail.infer_kind("dalle en pierre") == "stone"


def test_wear_lightens_edges_and_darkens_cavities():
    albedo = _noise(256)
    plain = maps.derive(albedo, maps.MapParams(wear=0))
    worn = maps.derive(albedo, maps.MapParams(wear=1))
    edges, cavities = maps.edge_wear(plain["height"], plain["ao"])
    lum = lambda m: metrics.luminance(m["albedo"])  # noqa: E731
    assert (lum(worn) - lum(plain))[edges > 0.8].mean() > 0
    assert (lum(worn) - lum(plain))[cavities > 0.8].mean() < 0


def test_detail_layer_keeps_normals_unit_length():
    m = maps.derive(_noise(256), maps.MapParams(detail_kind="stone", detail_strength=1))
    n = m["normal"] * 2 - 1
    assert np.allclose(np.linalg.norm(n, axis=-1), 1, atol=0.02)


def test_grain_orientation_follows_the_boards():
    stripes_x = np.tile(np.sin(np.arange(256) / 3.0)[:, None], (1, 256))  # grain along X
    img = np.repeat((stripes_x * 0.2 + 0.5)[..., None], 3, -1).astype(np.float32)
    assert maps.grain_along_x(img).mean() > 0.9
    assert maps.grain_along_x(np.swapaxes(img, 0, 1)).mean() < 0.1


def test_crop_grid_takes_one_cell_of_a_muse_grid():
    cell = _noise(200, seed=8)
    cell[:, :2] *= 0.6  # the visible join Muse leaves between copies
    cell[:2, :] *= 0.6
    grid = np.tile(cell, (4, 4, 1))
    out = seamless.crop_grid(grid)
    assert out.shape[:2] == (200, 200)


def test_crop_grid_leaves_planks_alone():
    rng = np.random.default_rng(3)
    boards = [np.clip(_noise(800, seed=10 + i)[:160] * rng.uniform(0.6, 1.2), 0, 1) for i in range(5)]
    for b in boards:
        b[:3] *= 0.3  # dark gap between boards
    planks = np.concatenate(boards, axis=0)
    assert seamless.crop_grid(planks).shape == planks.shape


def test_smooth_surfaces_stay_smooth():
    """Regression: every signal was stretched to full scale, so a smooth painted door came out
    as bumpy as a brick wall."""
    rng = np.random.default_rng(4)
    paint = np.clip(0.6 + rng.normal(0, 0.006, (256, 256, 3)), 0, 1).astype(np.float32)  # sensor noise
    rough = _noise(256, sigma=2.0)
    flat_guide = 0.5 + 0.02 * _noise(256, seed=6)[..., 0]
    deep_guide = _noise(256, seed=6)[..., 0]
    smooth = maps.derive(paint, maps.MapParams(), height_guide=flat_guide)
    bumpy = maps.derive(rough, maps.MapParams(), height_guide=deep_guide)
    tilt = lambda m: np.degrees(np.arccos(np.clip(m["normal"][..., 2] * 2 - 1, -1, 1))).mean()  # noqa: E731
    assert tilt(smooth) < tilt(bumpy) / 3
    assert smooth["ao"].min() > 0.8


def test_flatten_uniform_only_touches_plain_surfaces():
    from pbrforge import delight

    yy, xx = np.mgrid[:256, :256] / 256.0
    blotch = (np.sin(xx * 2 * np.pi) * 0.04)[..., None]
    paint = np.clip(0.6 + blotch + np.random.default_rng(2).normal(0, 0.004, (256, 256, 3)), 0, 1).astype(np.float32)
    out, k = delight.flatten_uniform(paint)
    assert k == 1.0 and metrics.luminance(out).std() < metrics.luminance(paint).std() / 3
    _, k_rough = delight.flatten_uniform(_noise(256, sigma=1.5))
    assert k_rough == 0.0


@pytest.mark.parametrize("n,size", [(512, 4096), (1600, 2048), (1600, 512), (1601, 1024)])
def test_resize_keeps_the_tile_seamless(n, size):
    from pbrforge import io

    out = io.resize(_noise(n, seed=3), size)
    assert out.shape == (size, size, 3)
    assert metrics.seam_score(out) < 1.5  # Pillow alone clamps the border: ~4 on 2K/4K upscales
