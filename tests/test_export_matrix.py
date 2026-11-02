"""Every export the UI offers (512, 1K, 2K, 4K x PNG, JPG): files, sizes, pixel formats, value
ranges, seams, normal conventions, the zip and the .glb, checked file by file."""
import io
import json
import struct
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from pbrforge import export, maps, metrics, shaders

from .test_pbrforge import _noise

SIZES = (512, 1024, 2048, 4096)
FORMATS = ("png", "jpg")
TEXTURES = ("Color", "NormalGL", "NormalDX", "Roughness", "AmbientOcclusion", "Displacement", "Metalness")
PARAMS = maps.MapParams(metallic=1.0, detail_kind="metal", detail_strength=0.5, wear=0.4)
_derived: dict[int, tuple] = {}


def _material(size: int):
    """Derived once per size and shared by both formats (4K takes a few seconds)."""
    if size not in _derived:
        albedo = _noise(512, seed=3)
        _derived[size] = (maps.derive(albedo, PARAMS, size=size), shaders.layers(albedo, PARAMS, size, None))
    return _derived[size]


@pytest.fixture(scope="module", params=[(s, f) for s in SIZES for f in FORMATS], ids=lambda p: f"{p[0]}-{p[1]}")
def package(request, tmp_path_factory):
    size, fmt = request.param
    m, lay = _material(size)
    d = export.export_package(m, "rusty steel plate", tmp_path_factory.mktemp(f"{size}{fmt}"), fmt,
                              Image.new("RGB", (512, 512)), {"clearcoat": 0.3, "ior": 1.5}, shader_layers=(lay, PARAMS))
    return d, size, fmt


def _texture(d: Path, kind: str, fmt: str) -> Image.Image:
    return Image.open(d / f"{d.name}_{kind}.{fmt}")


def test_name_and_every_file(package):
    d, size, fmt = package
    assert d.name == f"RustySteelPlate_{export.RES_LABEL[size]}-{fmt.upper()}"
    for kind in TEXTURES:
        assert (d / f"{d.name}_{kind}.{fmt}").is_file(), kind
    for ext in (".tres", ".mtlx", ".usda", ".glb"):
        assert (d / f"{d.name}{ext}").is_file(), ext
    assert (d / "RustySteelPlate.png").is_file()  # preview
    sh = d / "shader"
    for f in (f"{d.name}.gdshader", f"{d.name}_shader.tres", f"{d.name}_blender.py"):
        assert (sh / f).is_file(), f


def test_texture_sizes_and_pixel_formats(package):
    d, size, fmt = package
    modes = {"Color": "RGB", "NormalGL": "RGB", "NormalDX": "RGB", "Roughness": "L", "AmbientOcclusion": "L",
             "Metalness": "L", "Displacement": "I;16" if fmt == "png" else "L"}
    for kind, mode in modes.items():
        img = _texture(d, kind, fmt)
        assert img.size == (size, size), kind
        assert img.mode == mode or (mode == "I;16" and img.mode.startswith("I")), (kind, img.mode)


def test_values_are_in_pbr_ranges(package):
    d, _, fmt = package
    color = np.asarray(_texture(d, "Color", fmt), dtype=np.float32)
    lo, hi = np.percentile(color.mean(-1), [1, 99])
    assert 20 <= lo and hi <= 245, (lo, hi)  # no crushed blacks or blown whites in an albedo
    normal = np.asarray(_texture(d, "NormalGL", fmt), dtype=np.float32) / 255 * 2 - 1
    assert normal[..., 2].min() > 0  # every normal faces out of the surface
    assert np.abs(np.linalg.norm(normal, axis=-1) - 1).mean() < 0.02  # unit length
    for kind in ("Roughness", "AmbientOcclusion"):
        a = np.asarray(_texture(d, kind, fmt))
        assert a.max() > a.min(), kind  # not a flat map


def test_directx_normal_is_opengl_with_green_flipped(package):
    d, _, fmt = package
    gl = np.asarray(_texture(d, "NormalGL", fmt), dtype=int)
    dx = np.asarray(_texture(d, "NormalDX", fmt), dtype=int)
    tol = 1 if fmt == "png" else 3  # each JPG is compressed on its own
    assert np.abs(gl[..., 1] + dx[..., 1] - 255).mean() <= tol
    assert np.abs(gl[..., 0] - dx[..., 0]).mean() <= tol


def test_every_map_tiles_without_a_seam(package):
    d, _, fmt = package
    for kind in TEXTURES:
        a = np.asarray(_texture(d, kind, fmt), dtype=np.float32)
        assert metrics.seam_score(a) < 2.0, kind  # >2 is a visible seam


def test_zip_holds_the_whole_folder(package):
    d, _, _ = package
    z = export.zip_package(d)
    on_disk = {p.relative_to(d.parent).as_posix() for p in d.rglob("*") if p.is_file()}
    with zipfile.ZipFile(z) as f:
        assert f.testzip() is None
        assert {n for n in f.namelist() if not n.endswith("/")} == on_disk


def test_glb_embeds_the_textures_at_full_size(package):
    d, size, _ = package
    data = (d / f"{d.name}.glb").read_bytes()
    magic, version, length = struct.unpack_from("<III", data)
    assert magic == 0x46546C67 and version == 2 and length == len(data)
    json_len = struct.unpack_from("<I", data, 12)[0]
    j = json.loads(data[20:20 + json_len])
    bin_start = 20 + json_len + 8
    for img in j["images"]:
        view = j["bufferViews"][img["bufferView"]]
        png = data[bin_start + view.get("byteOffset", 0):][:view["byteLength"]]
        assert Image.open(io.BytesIO(png)).size == (size, size)
    m = j["materials"][0]
    assert m["pbrMetallicRoughness"]["metallicFactor"] == 1.0
    assert "KHR_materials_clearcoat" in m["extensions"]
