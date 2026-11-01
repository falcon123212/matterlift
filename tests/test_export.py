from pathlib import Path

import numpy as np
from PIL import Image

from pbrforge import export, maps

from .test_pbrforge import _noise

# File layout of the reference ambientCG package Bricks113A_4K-JPG.
REFERENCE_SUFFIXES = {"Color", "NormalGL", "NormalDX", "Roughness", "AmbientOcclusion", "Displacement"}


def _package(tmp_path: Path, metallic: float):
    m = maps.derive(_noise(256), maps.MapParams(metallic=metallic))
    return export.export_package(m, "old oak planks", tmp_path, "png")


def test_layout_matches_reference(tmp_path):
    d = _package(tmp_path, 0.0)
    assert d.name == "OldOakPlanks_256-PNG"
    suffixes = {p.stem.split("-PNG_")[1] for p in d.glob("*-PNG_*.png")}
    assert suffixes == REFERENCE_SUFFIXES
    for ext in (".tres", ".mtlx", ".usda"):
        assert (d / f"{d.name}{ext}").exists()
    assert 'normal_texture = ExtResource("NormalGL")' in (d / f"{d.name}.tres").read_text()
    assert "metallic_texture" not in (d / f"{d.name}.tres").read_text()


def test_metal_adds_metalness_and_flips_dx_green(tmp_path):
    d = _package(tmp_path, 1.0)
    assert (d / f"{d.name}_Metalness.png").exists()
    assert "metallic_texture" in (d / f"{d.name}.tres").read_text()
    gl = np.asarray(Image.open(d / f"{d.name}_NormalGL.png"), dtype=int)
    dx = np.asarray(Image.open(d / f"{d.name}_NormalDX.png"), dtype=int)
    assert np.abs(gl[..., 1] + dx[..., 1] - 255).max() <= 1
    assert np.array_equal(gl[..., 0], dx[..., 0])


def test_displacement_is_16_bit(tmp_path):
    d = _package(tmp_path, 0.0)
    assert Image.open(d / f"{d.name}_Displacement.png").mode.startswith("I")
