import numpy as np
import pytest

from matterlift_api.sampling import sample_regions
from matterlift_api.sam_mask import MaskError, decode_one_bit

# Real one_bit payloads returned by sam-3.1 for "stone" on a 256 px flagstone texture.
EDGE_STONE = (5, 22, "!!!!!-I64i@axK!$f].")  # thin sliver cut by the image border
STONE = (37, 35, "!!!!!6GO4wTWrtoYQU0.dll$mO^Y1C")


def test_decodes_real_payloads():
    for h, w, payload in (EDGE_STONE, STONE):
        m = decode_one_bit(payload, h, w)
        assert m.shape == (h, w) and m.dtype == bool
        assert 0.3 < m.mean() < 1.0  # an object inside its own box


def test_stone_mask_is_one_blob_touching_its_box():
    m = decode_one_bit(STONE[2], STONE[0], STONE[1])
    from scipy import ndimage

    labels, count = ndimage.label(m)
    assert count == 1
    # The box is tight: the mask reaches every side.
    assert m[0].any() and m[-1].any() and m[:, 0].any() and m[:, -1].any()


def test_rejects_wrong_marker_and_truncation():
    with pytest.raises(MaskError):
        decode_one_bit("~" + STONE[2][1:], STONE[0], STONE[1])
    with pytest.raises(MaskError):
        decode_one_bit(STONE[2][:-3], STONE[0], STONE[1])


def test_samples_avoid_holes():
    mask = np.zeros((400, 600), dtype=bool)
    mask[50:350, 50:550] = True  # table top
    mask[60:200, 60:200] = False  # bowl
    regions = sample_regions(mask, margin=0)
    assert regions
    for x, y, w, h in regions:
        assert mask[y : y + h, x : x + w].all()
    assert regions[0][2] * regions[0][3] >= 300 * 200


def test_thin_strip_gives_a_long_sample():
    mask = np.zeros((300, 900), dtype=bool)
    mask[100:180, 20:880] = True  # countertop seen edge-on
    x, y, w, h = sample_regions(mask)[0]
    assert w > 2 * h and h >= 40


def test_partly_hidden_surface_gives_several_samples():
    mask = np.zeros((400, 800), dtype=bool)
    mask[:, :] = True
    mask[:, 250:550] = False  # a table hides the middle of the floor
    regions = sample_regions(mask)
    assert len(regions) >= 2
    assert {r[0] < 250 for r in regions} == {True, False}  # one each side


def test_no_samples_in_empty_mask():
    assert sample_regions(np.zeros((50, 50), dtype=bool)) == []
