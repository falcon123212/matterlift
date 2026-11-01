"""Export a material as an ambientCG-style package (the layout of Bricks113A_4K-JPG):

<Name>_<res>-<FMT>/
  <Name>_<res>-<FMT>_Color, _NormalGL, _NormalDX, _Roughness, _AmbientOcclusion, _Displacement
  (+ _Metalness when the material has metal), .tres (Godot 4), .mtlx (MaterialX OpenPBR),
  .usda (USD UsdPreviewSurface), preview .png
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

from . import io

RES_LABEL = {512: "512", 1024: "1K", 2048: "2K", 4096: "4K"}


def package_name(name: str, size: int, fmt: str) -> str:
    stem = "".join(p.capitalize() for p in re.split(r"[^A-Za-z0-9]+", name) if p) or "Material"
    return f"{stem}_{RES_LABEL.get(size, str(size))}-{fmt.upper()}"


def _save(path: Path, arr: np.ndarray, fmt: str, bits16: bool = False) -> str:
    if fmt == "jpg":
        img = io.to_pil(arr)
        img = img.convert("L") if arr.ndim == 2 else img
        img.save(path.with_suffix(".jpg"), quality=95, subsampling=0)
        return path.with_suffix(".jpg").name
    if bits16 and arr.ndim == 2:
        io.save(path.with_suffix(".png"), arr, bits=16)
    else:
        img = io.to_pil(arr)
        (img.convert("L") if arr.ndim == 2 else img).save(path.with_suffix(".png"))
    return path.with_suffix(".png").name


def _tres(files: dict[str, str], metal: bool) -> str:
    ids = [k for k in ("Color", "AmbientOcclusion", "Displacement", "Roughness", "NormalGL", "Metalness") if k in files]
    head = f'[gd_resource type="StandardMaterial3D" load_steps={len(ids) + 1} format=3]\n\n'
    res = "".join(f'[ext_resource type="Texture2D" id="{k}" path="./{files[k]}"]\n' for k in ids)
    body = """[resource]
albedo_texture = ExtResource("Color")
ao_enabled = true
ao_texture = ExtResource("AmbientOcclusion")
ao_texture_channel = 4
roughness_texture = ExtResource("Roughness")
roughness_texture_channel = 4
normal_enabled = true
normal_texture = ExtResource("NormalGL")
heightmap_enabled = true
heightmap_scale = 1.0
heightmap_texture = ExtResource("Displacement")
"""
    if metal:
        body += 'metallic = 1.0\nmetallic_texture = ExtResource("Metalness")\nmetallic_texture_channel = 4\n'
    return head + res + "\n" + body


def _mtlx(stem: str, files: dict[str, str], metal: bool) -> str:
    n = stem.replace("-", "_")

    def tiled(key: str, typ: str, srgb: bool = False) -> str:
        cs = ' colorspace="srgb_texture"' if srgb else ""
        return (f'  <tiledimage name="{n}_{key}" type="{typ}">\n'
                f'    <input name="file" type="filename" value="{files[key]}"{cs} />\n'
                f'    <input name="uvtiling" type="vector2" value="1.0, 1.0" />\n  </tiledimage>\n')

    metal_in = f'    <input name="base_metalness" type="float" nodename="{n}_Metalness" />\n' if metal else ""
    return f"""<?xml version="1.0"?>
<materialx version="1.39" fileprefix="./">
  <open_pbr_surface name="{n}_OpenPbrSurface" type="surfaceshader">
    <input name="base_color" type="color3" nodename="{n}_Color" />
    <input name="specular_roughness" type="float" nodename="{n}_Roughness" />
{metal_in}    <input name="geometry_normal" type="vector3" nodename="NormalMap" />
  </open_pbr_surface>
  <surfacematerial name="{n}" type="material">
    <input name="surfaceshader" type="surfaceshader" nodename="{n}_OpenPbrSurface" />
    <input name="displacementshader" type="displacementshader" nodename="displacement" />
  </surfacematerial>
{tiled("Color", "color3", True)}{tiled("Roughness", "float")}{tiled("NormalGL", "vector3")}{tiled("Displacement", "float")}{tiled("Metalness", "float") if metal else ""}  <normalmap name="NormalMap" type="vector3">
    <input name="in" type="vector3" nodename="{n}_NormalGL" />
    <input name="scale" type="float" value="1.0" />
  </normalmap>
  <displacement name="displacement" type="displacementshader">
    <input name="displacement" type="float" nodename="{n}_Displacement" />
    <input name="scale" type="float" value="1.0" />
  </displacement>
</materialx>
"""


def _usda(stem: str, files: dict[str, str], metal: bool) -> str:
    n = re.sub(r"[^A-Za-z0-9_]", "_", stem)

    def tex(key: str, out: str, cs: str) -> str:
        return f'''        def Shader "{key}"
        {{
            uniform token info:id = "UsdUVTexture"
            asset inputs:file = @./{files[key]}@
            token inputs:sourceColorSpace = "{cs}"
            float2 inputs:st.connect = </{n}/Material/uv.outputs:result>
            token inputs:wrapS = "repeat"
            token inputs:wrapT = "repeat"
            {"float4 inputs:scale = (2, 2, 2, 1)" if key == "NormalGL" else ""}
            {"float4 inputs:bias = (-1, -1, -1, 0)" if key == "NormalGL" else ""}
            {out} outputs:{"rgb" if out == "float3" else "r"}
        }}
'''
    metal_line = (f'            float inputs:metallic.connect = </{n}/Material/Metalness.outputs:r>\n'
                  if metal else "            float inputs:metallic = 0\n")
    return f'''#usda 1.0
(
    defaultPrim = "{n}"
)

def Xform "{n}"
{{
    def Material "Material"
    {{
        token outputs:surface.connect = </{n}/Material/Surface.outputs:surface>

        def Shader "Surface"
        {{
            uniform token info:id = "UsdPreviewSurface"
            color3f inputs:diffuseColor.connect = </{n}/Material/Color.outputs:rgb>
            float inputs:roughness.connect = </{n}/Material/Roughness.outputs:r>
            float inputs:occlusion.connect = </{n}/Material/AmbientOcclusion.outputs:r>
            normal3f inputs:normal.connect = </{n}/Material/NormalGL.outputs:rgb>
            float inputs:displacement.connect = </{n}/Material/Displacement.outputs:r>
{metal_line}            token outputs:surface
        }}

        def Shader "uv"
        {{
            uniform token info:id = "UsdPrimvarReader_float2"
            string inputs:varname = "st"
            float2 outputs:result
        }}

{tex("Color", "float3", "sRGB")}{tex("Roughness", "float", "raw")}{tex("AmbientOcclusion", "float", "raw")}{tex("NormalGL", "float3", "raw")}{tex("Displacement", "float", "raw")}{tex("Metalness", "float", "raw") if metal else ""}    }}
}}
'''


def export_package(maps: dict[str, np.ndarray], name: str, out_root: Path, fmt: str = "png",
                   preview: Image.Image | None = None) -> Path:
    """Write the package folder and return its path. `maps` come from pbrforge.derive."""
    fmt = fmt.lower()
    if fmt not in ("png", "jpg"):
        raise ValueError("fmt must be png or jpg")
    size = maps["albedo"].shape[0]
    stem = package_name(name, size, fmt)
    d = Path(out_root) / stem
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)

    n_gl = maps["normal"]
    n_dx = n_gl.copy()
    n_dx[..., 1] = 1 - n_dx[..., 1]  # DirectX: green flipped
    metal = bool(maps["metallic"].max() > 0.02)

    files = {
        "Color": _save(d / f"{stem}_Color", maps["albedo"], fmt),
        "NormalGL": _save(d / f"{stem}_NormalGL", n_gl, fmt),
        "NormalDX": _save(d / f"{stem}_NormalDX", n_dx, fmt),
        "Roughness": _save(d / f"{stem}_Roughness", maps["roughness"], fmt),
        "AmbientOcclusion": _save(d / f"{stem}_AmbientOcclusion", maps["ao"], fmt),
        "Displacement": _save(d / f"{stem}_Displacement", maps["height"], fmt, bits16=True),
    }
    if metal:
        files["Metalness"] = _save(d / f"{stem}_Metalness", maps["metallic"], fmt)

    (d / f"{stem}.tres").write_text(_tres(files, metal), encoding="utf-8")
    (d / f"{stem}.mtlx").write_text(_mtlx(stem, files, metal), encoding="utf-8")
    (d / f"{stem}.usda").write_text(_usda(stem, files, metal), encoding="utf-8")
    if preview is not None:
        preview.convert("RGB").resize((512, 512), Image.LANCZOS).save(d / f"{stem.split('_')[0]}.png")
    return d


def zip_package(folder: Path) -> Path:
    return Path(shutil.make_archive(str(folder), "zip", root_dir=folder.parent, base_dir=folder.name))
