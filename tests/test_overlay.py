import numpy as np
from PIL import Image

from matterlift_api import overlay


def test_draws_found_and_missing_materials():
    photo = Image.new("RGB", (800, 600), (120, 110, 100))
    mask = np.zeros((600, 800), dtype=bool)
    mask[100:400, 100:500] = True
    out = overlay.draw(photo, [("oak_table", mask, [(150, 150, 200, 120), (360, 300, 100, 80)]),
                               ("plaster_wall", None, [])])  # SAM found no plaster
    assert out.size == (800, 600)
    a = np.asarray(out).astype(int)
    assert np.abs(a[250, 300] - [120, 110, 100]).sum() > 30  # the mask is tinted
    assert np.abs(a[550, 750] - [120, 110, 100]).sum() == 0  # outside: untouched
