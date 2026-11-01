"""glTF 2.0 binary (.glb) export, no dependencies: the material on a preview sphere, textures
embedded, and Spark's shading model as ratified KHR material extensions.

Texture layout follows the spec: baseColor (sRGB), metallicRoughness (G = roughness, B = metallic)
and occlusion (R) share one ORM image, normal map in OpenGL convention (glTF's +Y up).
"""
from __future__ import annotations

import io as _io
import json
import struct
from pathlib import Path

import numpy as np

from . import io

_FLOAT, _USHORT, _UINT = 5126, 5123, 5125
_ARRAY_BUFFER, _ELEMENT_ARRAY_BUFFER = 34962, 34963


def uv_sphere(radius: float = 0.5, segments: int = 64, rings: int = 32) -> dict[str, np.ndarray]:
    """Positions, normals, tangents (xyz + handedness), UVs and indices of a UV sphere."""
    u = np.linspace(0, 1, segments + 1)
    v = np.linspace(0, 1, rings + 1)
    uu, vv = np.meshgrid(u, v)
    phi, theta = uu * 2 * np.pi, vv * np.pi
    n = np.stack([np.sin(theta) * np.cos(phi), np.cos(theta), -np.sin(theta) * np.sin(phi)], -1)
    t = np.stack([-np.sin(phi), np.zeros_like(phi), -np.cos(phi)], -1)  # d(position)/du
    tangents = np.concatenate([t, np.ones(t.shape[:-1] + (1,))], -1)
    idx = []
    for r in range(rings):
        for s in range(segments):
            a, b = r * (segments + 1) + s, (r + 1) * (segments + 1) + s
            idx += [a, b, a + 1, a + 1, b, b + 1]
    return {
        "POSITION": (n * radius).reshape(-1, 3).astype(np.float32),
        "NORMAL": n.reshape(-1, 3).astype(np.float32),
        "TANGENT": tangents.reshape(-1, 4).astype(np.float32),
        "TEXCOORD_0": np.stack([uu, vv], -1).reshape(-1, 2).astype(np.float32),
        "indices": np.array(idx, dtype=np.uint32),
    }


def _png(arr: np.ndarray) -> bytes:
    buf = _io.BytesIO()
    io.to_pil(arr).save(buf, "PNG")
    return buf.getvalue()


def material_extensions(shading: dict) -> tuple[dict, list[str]]:
    """Spark's shading model -> KHR extensions, only those that change something."""
    ext: dict = {}
    if shading.get("clearcoat", 0) > 0.01:
        ext["KHR_materials_clearcoat"] = {"clearcoatFactor": float(shading["clearcoat"]),
                                          "clearcoatRoughnessFactor": float(shading.get("clearcoat_roughness", 0.1))}
    if shading.get("transmission", 0) > 0.01:
        ext["KHR_materials_transmission"] = {"transmissionFactor": float(shading["transmission"])}
    if abs(shading.get("ior", 1.5) - 1.5) > 0.01:
        ext["KHR_materials_ior"] = {"ior": float(shading["ior"])}
    if shading.get("sheen", 0) > 0.01:
        s = float(shading["sheen"])
        ext["KHR_materials_sheen"] = {"sheenColorFactor": [s, s, s], "sheenRoughnessFactor": 0.6}
    if shading.get("anisotropy", 0) > 0.01:
        ext["KHR_materials_anisotropy"] = {"anisotropyStrength": float(shading["anisotropy"])}
    if shading.get("subsurface", 0) > 0.01:  # closest ratified model: light diffusing through
        ext["KHR_materials_diffuse_transmission"] = {"diffuseTransmissionFactor": float(shading["subsurface"]) * 0.5}
    return ext, sorted(ext)


def write_glb(path: str | Path, maps: dict[str, np.ndarray], name: str, shading: dict | None = None,
              repeat: float = 2.0) -> Path:
    """`maps` from pbrforge.derive (albedo, normal, orm). `repeat` tiles the texture on the sphere
    (KHR_texture_transform), as the preview does."""
    path = Path(path)
    mesh = uv_sphere()
    blob = bytearray()
    buffer_views, accessors = [], []

    def add_view(data: bytes, target: int | None = None) -> int:
        while len(blob) % 4:
            blob.append(0)
        view = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(data)}
        if target:
            view["target"] = target
        blob.extend(data)
        buffer_views.append(view)
        return len(buffer_views) - 1

    attributes = {}
    for key in ("POSITION", "NORMAL", "TANGENT", "TEXCOORD_0"):
        a = mesh[key]
        acc = {"bufferView": add_view(a.tobytes(), _ARRAY_BUFFER), "componentType": _FLOAT,
               "count": len(a), "type": {2: "VEC2", 3: "VEC3", 4: "VEC4"}[a.shape[1]]}
        if key == "POSITION":
            acc["min"], acc["max"] = a.min(0).tolist(), a.max(0).tolist()
        accessors.append(acc)
        attributes[key] = len(accessors) - 1
    ind = mesh["indices"]
    accessors.append({"bufferView": add_view(ind.tobytes(), _ELEMENT_ARRAY_BUFFER), "componentType": _UINT,
                      "count": len(ind), "type": "SCALAR"})
    indices = len(accessors) - 1

    images = []
    for key in ("albedo", "orm", "normal"):
        images.append({"bufferView": add_view(_png(maps[key])), "mimeType": "image/png", "name": f"{name}_{key}"})
    transform = {"KHR_texture_transform": {"scale": [repeat, repeat]}}

    def tex(i: int, **extra) -> dict:
        return {"index": i, **extra, "extensions": transform}

    ext, used = material_extensions(shading or {})
    material = {
        "name": name,
        "pbrMetallicRoughness": {"baseColorTexture": tex(0), "metallicRoughnessTexture": tex(1),
                                 "metallicFactor": 1.0, "roughnessFactor": 1.0},
        "occlusionTexture": tex(1),
        "normalTexture": tex(2, scale=1.0),
    }
    if ext:
        material["extensions"] = ext
    used = sorted({"KHR_texture_transform", *used})

    gltf = {
        "asset": {"version": "2.0", "generator": "MatterLift (pbrforge)"},
        "extensionsUsed": used,
        "scene": 0,
        "scenes": [{"name": name, "nodes": [0]}],
        "nodes": [{"name": f"{name}_preview", "mesh": 0}],
        "meshes": [{"name": f"{name}_sphere",
                    "primitives": [{"attributes": attributes, "indices": indices, "material": 0}]}],
        "materials": [material],
        "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}],
        "images": images,
        "textures": [{"sampler": 0, "source": i} for i in range(3)],
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(blob)}],
    }
    while len(blob) % 4:
        blob.append(0)
    gltf["buffers"][0]["byteLength"] = len(blob)
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    out = struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(js), b"JSON") + js
    out += struct.pack("<I4s", len(blob), b"BIN\x00") + bytes(blob)
    path.write_bytes(out)
    return path


def read_glb_json(path: str | Path) -> dict:
    data = Path(path).read_bytes()
    magic, version, total = struct.unpack_from("<4sII", data, 0)
    assert magic == b"glTF" and version == 2 and total == len(data)
    length, kind = struct.unpack_from("<I4s", data, 12)
    assert kind == b"JSON"
    return json.loads(data[20 : 20 + length])

