"""The albedo clean-up chain, in the order that works on Muse Image output."""
from __future__ import annotations

import numpy as np

from . import delight, metrics, seamless


def fix_albedo(img: np.ndarray, singletons: float = 0.8, fix_grid: bool = False) -> tuple[np.ndarray, dict]:
    """Return a tileable, delit albedo and the before/after scores.

    fix_grid smooths straight colour steps inside the tile. Off by default: Muse's grid comes
    from internal repetition, which crop_period already removes, and planks or tiles have
    legitimate straight steps that it would smear.
    """
    before = metrics.report(img)
    out = seamless.crop_period(img)
    out = delight.fit_pbr_range(delight.delight(out))
    out = seamless.make_tileable(out)
    if fix_grid:
        out = seamless.fix_blocks(out)
    touched = 0.0
    if singletons > 0:
        out, touched = seamless.suppress_singletons(out, singletons)
    after = metrics.report(out)
    after["singletons_touched"] = round(touched, 2)
    return out, {"before": before, "after": after}
