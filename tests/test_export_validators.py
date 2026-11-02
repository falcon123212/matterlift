"""The exported files pass the formats' official tools: Khronos glTF-Validator, the MaterialX
library (ASWF) and Pixar's USD. Each test is skipped when its tool is not installed
(pip install MaterialX usd-core; npm --prefix web ci for the glTF validator)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from pbrforge import export, maps

from .test_pbrforge import _noise

ROOT = Path(__file__).resolve().parents[1]
GLTF_SCRIPT = ROOT / "web" / "scripts" / "validate-gltf.mjs"

# Every shading lobe Spark can ask for, one at a time and all together.
SHADINGS = {
    "plain": {},
    "clearcoat": {"clearcoat": 0.8, "clearcoat_roughness": 0.05},
    "sheen": {"sheen": 0.7},
    "transmission": {"transmission": 0.6, "ior": 1.45},
    "anisotropy": {"anisotropy": 0.5},
    "subsurface": {"subsurface": 0.4},
    "everything": {"clearcoat": 0.3, "sheen": 0.5, "ior": 1.6, "transmission": 0.2, "anisotropy": 0.4,
                   "subsurface": 0.3},
}


@pytest.fixture(scope="module")
def packages(tmp_path_factory) -> dict[str, Path]:
    out = {}
    for metallic in (0.0, 1.0):
        m = maps.derive(_noise(128), maps.MapParams(metallic=metallic))
        for key, shading in SHADINGS.items():
            name = f"{key} {'metal' if metallic else 'dielectric'}"
            out[name] = export.export_package(m, name, tmp_path_factory.mktemp("v"), "png", shading=shading)
    return out


def test_gltf_passes_khronos_validator(packages):
    node = shutil.which("node")
    if not node or not (ROOT / "web" / "node_modules" / "gltf-validator").exists():
        pytest.skip("Khronos glTF-Validator not installed (npm --prefix web ci)")
    files = [str(d / f"{d.name}.glb") for d in packages.values()]
    run = subprocess.run([node, str(GLTF_SCRIPT), *files], capture_output=True, text=True)
    reports = [json.loads(line) for line in run.stdout.splitlines()]
    assert len(reports) == len(files)
    for r in reports:
        assert r["errors"] == 0 and r["warnings"] == 0, r


def test_materialx_documents_are_valid(packages):
    mx = pytest.importorskip("MaterialX")
    for d in packages.values():
        doc = mx.createDocument()
        mx.readFromXmlFile(doc, str(d / f"{d.name}.mtlx"))
        ok, message = doc.validate()
        assert ok, message
        assert doc.getMaterialNodes(), d.name
        shaders = [n for n in doc.getNodes() if n.getCategory() == "open_pbr_surface"]
        assert len(shaders) == 1, d.name
        files = [i.getValueString() for n in doc.getNodes() for i in n.getInputs() if i.getType() == "filename"]
        assert files and all((d / f).is_file() for f in files), (d.name, files)


def test_usd_stages_open_and_every_texture_resolves(packages):
    pytest.importorskip("pxr")
    from pxr import Sdf, Usd, UsdShade

    for d in packages.values():
        stage = Usd.Stage.Open(str(d / f"{d.name}.usda"))
        assert stage and stage.GetDefaultPrim(), d.name
        mats = [UsdShade.Material(p) for p in stage.Traverse() if p.IsA(UsdShade.Material)]
        assert len(mats) == 1, d.name
        surface = mats[0].ComputeSurfaceSource()[0]
        assert surface and surface.GetIdAttr().Get() == "UsdPreviewSurface", d.name
        for name in ("diffuseColor", "roughness", "occlusion", "normal", "displacement"):
            assert surface.GetInput(name).HasConnectedSource(), (d.name, name)
        textures = [UsdShade.Shader(p) for p in stage.Traverse()
                    if UsdShade.Shader(p) and UsdShade.Shader(p).GetIdAttr().Get() == "UsdUVTexture"]
        assert textures, d.name
        for t in textures:
            asset: Sdf.AssetPath = t.GetInput("file").Get()
            assert asset.resolvedPath and Path(asset.resolvedPath).is_file(), (d.name, asset.path)
