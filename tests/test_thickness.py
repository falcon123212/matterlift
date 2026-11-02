"""Thickness map: how much matter light crosses, exported only for materials light goes into
(subsurface) or through (transmission). The official tools check it in test_export_validators.py
and test_export_godot.py (those packages include both lobes)."""
import numpy as np
import pytest
from PIL import Image

from pbrforge import export, gltf, maps, metrics

from .test_pbrforge import _noise


@pytest.fixture(scope="module")
def derived():
    return maps.derive(_noise(256, seed=5), maps.MapParams(detail_kind="none"))


def test_thickness_range_tiles_and_follows_the_relief(derived):
    t, h = derived["thickness"], derived["height"]
    assert t.shape == h.shape and t.dtype == np.float32
    assert t.min() >= 0.2 - 1e-6 and t.max() <= 1.0 + 1e-6  # never fully clear
    assert t.max() - t.min() > 0.4  # it varies, it is not a constant
    assert metrics.seam_score(t) < 2.0
    assert np.corrcoef(t.ravel(), h.ravel())[0, 1] > 0.5  # raised masses are thick


def test_thickness_ignores_fine_detail(derived):
    """Pores and scratches change the surface, not how much matter there is behind it."""
    t, h = derived["thickness"], derived["height"]
    fine = lambda a: np.abs(a - np.roll(a, 1, 0)).mean() / (a.max() - a.min())  # noqa: E731
    assert fine(t) < fine(h)


@pytest.mark.parametrize("shading, has", [({}, False), ({"clearcoat": 0.5}, False), ({"subsurface": 0.4}, True),
                                          ({"transmission": 0.6, "ior": 1.45}, True)])
def test_exported_only_when_light_goes_in(derived, tmp_path, shading, has):
    d = export.export_package(derived, "jade", tmp_path, "png", Image.new("RGB", (64, 64)), shading)
    assert (d / f"{d.name}_Thickness.png").is_file() == has
    tres = (d / f"{d.name}.tres").read_text()
    assert ('ExtResource("Thickness")' in tres) == has
    assert ("subsurf_scatter_transmittance_enabled = true" in tres) == has
    mtlx = (d / f"{d.name}.mtlx").read_text()
    assert (f"{d.name}_Thickness.png" in mtlx) == has
    assert ('name="subsurface_radius"' in mtlx) == (shading.get("subsurface", 0) > 0)
    assert ('name="transmission_depth"' in mtlx) == (shading.get("transmission", 0) > 0)
    doc = gltf.read_glb_json(d / f"{d.name}.glb")
    volume = doc["materials"][0].get("extensions", {}).get("KHR_materials_volume")
    assert (volume is not None) == has
    assert ("KHR_materials_volume" in doc["extensionsUsed"]) == has
    assert len(doc["images"]) == len(doc["textures"]) == (4 if has else 3)
    if has:
        assert doc["textures"][volume["thicknessTexture"]["index"]]["source"] == 3
        assert volume["thicknessFactor"] > 0 and all(0 <= c <= 1 for c in volume["attenuationColor"])
