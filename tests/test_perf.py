"""Performance guards: catch a slowdown or a memory blow-up in pbrforge before it ships. Limits are
about 3x what a 2026 desktop measures (results/perf_pbrforge.md), so slower CI runners pass.
The 4K memory limit keeps an export inside the API container (4 GB on Modal)."""
import time
import tracemalloc

import pytest

from pbrforge import maps

from .test_pbrforge import _noise

PARAMS = maps.MapParams(metallic=1.0, detail_kind="stone", detail_strength=0.6, wear=0.4)


def _derive(size: int) -> tuple[float, float]:
    albedo = _noise(1600, seed=1)
    tracemalloc.start()
    t = time.perf_counter()
    maps.derive(albedo, PARAMS, size=size)
    seconds = time.perf_counter() - t
    peak_mb = tracemalloc.get_traced_memory()[1] / 1e6
    tracemalloc.stop()
    return seconds, peak_mb


@pytest.mark.parametrize("size,max_s,max_mb", [(512, 2, 150), (1024, 5, 400), (2048, 18, 1500)])
def test_derive_time_and_memory(size, max_s, max_mb):
    seconds, peak = _derive(size)
    assert seconds < max_s, f"{size}: {seconds:.1f} s"
    assert peak < max_mb, f"{size}: {peak:.0f} MB"


def test_4k_fits_in_the_api_container():
    _, peak = _derive(4096)
    assert peak < 3200, f"4K derive peaks at {peak:.0f} MB; the Modal container has 4096"
