import numpy as np
import pytest

from matterlift_api.pipeline import largest_square_in_mask
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


def test_largest_square_avoids_holes():
    mask = np.zeros((400, 600), dtype=bool)
    mask[50:350, 50:550] = True  # table top
    mask[60:200, 60:200] = False  # bowl
    x, y, side = largest_square_in_mask(mask, margin=0)
    assert mask[y : y + side, x : x + side].all()
    assert side >= 260


def test_largest_square_none_for_empty_mask():
    assert largest_square_in_mask(np.zeros((50, 50), dtype=bool)) is None
