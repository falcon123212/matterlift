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


def test_package_has_a_valid_glb_with_shading(tmp_path):
    from pbrforge import gltf

    m = maps.derive(_noise(128), maps.MapParams())
    d = export.export_package(m, "lacquered wood", tmp_path, "png",
                              shading={"clearcoat": 0.8, "clearcoat_roughness": 0.05, "ior": 1.5, "sheen": 0})
    j = gltf.read_glb_json(d / f"{d.name}.glb")
    mat = j["materials"][0]
    assert mat["extensions"]["KHR_materials_clearcoat"]["clearcoatFactor"] == 0.8
    assert "KHR_materials_sheen" not in mat["extensions"] and "KHR_materials_ior" not in mat["extensions"]
    assert len(j["images"]) == 3 and j["accessors"][0]["count"] == 65 * 33
    tres = (d / f"{d.name}.tres").read_text()
    assert "clearcoat_enabled = true" in tres and "clearcoat = 0.800" in tres
    assert 'name="coat_weight" type="float" value="0.800"' in (d / f"{d.name}.mtlx").read_text()


def test_usda_carries_clearcoat_and_ior(tmp_path):
    m = maps.derive(_noise(64), maps.MapParams())
    d = export.export_package(m, "glass", tmp_path, "png", shading={"clearcoat": 0.5, "ior": 1.9})
    usda = (d / f"{d.name}.usda").read_text()
    assert "inputs:clearcoat = 0.500" in usda and "inputs:ior = 1.900" in usda


def test_package_has_live_shaders(tmp_path):
    from pbrforge import shaders

    albedo = _noise(128)
    p = maps.MapParams(detail_kind="wood", detail_strength=0.6, wear=0.5)
    m = maps.derive(albedo, p)
    d = export.export_package(m, "old oak", tmp_path, "png", shading={"clearcoat": 0.4},
                              shader_layers=(shaders.layers(albedo, p, 128, None), p))
    sh = d / "shader"
    gd = (sh / f"{d.name}.gdshader").read_text()
    assert "shader_type spatial;" in gd and "uniform float wear : hint_range(0.0, 1.0) = 0.5;" in gd
    assert "uniform float clearcoat_amount : hint_range(0.0, 1.0) = 0.4;" in gd
    tres = (sh / f"{d.name}_shader.tres").read_text()
    assert 'type="ShaderMaterial"' in tres and tres.count("shader_parameter/") == 5
    for line in tres.splitlines():
        if line.startswith("[ext_resource") and "Texture2D" in line:
            assert (sh / line.split('path="./')[1].split('"')[0]).exists()
    script = (sh / f"{d.name}_blender.py").read_text()
    compile(script, "blender.py", "exec")  # valid Python
    assert 'value(nodes, "Wear"' in script and "'wear': 0.5" in script


def test_shader_layers_are_clean_base_maps():
    from pbrforge import shaders

    albedo = _noise(128)
    worn = maps.MapParams(detail_kind="stone", detail_strength=1, wear=1)
    lay = shaders.layers(albedo, worn, 128, None)
    clean = maps.derive(albedo, maps.MapParams())
    assert np.allclose(lay["albedo"], clean["albedo"])  # no wear baked in the shader's base
    assert lay["wear_mask"].shape == (128, 128, 3) and lay["detail_height"].shape == (512, 512)
