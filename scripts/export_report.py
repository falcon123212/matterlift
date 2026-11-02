"""Export report: a real MatterLift material exported the way the API does it, at every size and
format, then every shading lobe, each package checked by the official tools (Khronos
glTF-Validator, MaterialX, USD, Godot 4 headless). Writes results/export_report.json and
results/export_report.md, and copies the 512 PNG package to samples/export/ as a downloadable example.

    .venv/Scripts/python scripts/export_report.py [--material 1a39196022] [--sizes 512 1024 2048 4096]

Godot runs when GODOT_BIN points at a Godot 4 binary (the console one on Windows); the glTF
validator needs npm --prefix web ci; MaterialX and usd-core come with pip install -e ".[dev]".
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))
from matterlift_api.pipeline import DATA_DIR, export_material, load_material  # noqa: E402
from tests.test_export_godot import CHECK  # noqa: E402
from tests.test_export_validators import SHADINGS  # noqa: E402

GLTF_SCRIPT = ROOT / "web" / "scripts" / "validate-gltf.mjs"


def _export(mat, size: int, fmt: str, out: Path, shading: tuple[str, dict] | None = None) -> dict:
    """One package as GET /materials/{id}/export makes it, moved into `out`. A shading variant gets
    the lobe in its name, so every package has its own folder and file names."""
    if shading is not None:
        mat = mat.model_copy(deep=True)
        mat.plan.name = f"{mat.plan.name}_{shading[0]}"
        mat.plan.shading = mat.plan.shading.model_validate({**mat.plan.shading.model_dump(), **shading[1]})
    t = time.perf_counter()
    z = export_material(mat, size, fmt)
    seconds = time.perf_counter() - t
    folder = z.with_suffix("")
    dest = out / folder.name
    shutil.move(str(folder), dest)
    row = {"package": folder.name, "size": size, "format": fmt, "export_zip_s": round(seconds, 2),
           "zip_mb": round(z.stat().st_size / 1e6, 1), "files": sum(1 for p in dest.rglob("*") if p.is_file()),
           "folder_mb": round(sum(p.stat().st_size for p in dest.rglob("*") if p.is_file()) / 1e6, 1)}
    shutil.rmtree(z.parent, ignore_errors=True)
    return row


def _khronos(dirs: list[Path]) -> dict[str, str]:
    node = shutil.which("node")
    if not node or not (ROOT / "web" / "node_modules" / "gltf-validator").exists():
        return {d.name: "not run" for d in dirs}
    run = subprocess.run([node, str(GLTF_SCRIPT), *[str(d / f"{d.name}.glb") for d in dirs]],
                         capture_output=True, text=True)
    out = {}
    for line in run.stdout.splitlines():
        r = json.loads(line)
        ok = r["errors"] == 0 and r["warnings"] == 0
        out[Path(r["file"]).stem] = "pass" if ok else f"FAIL {r['errors']} errors, {r['warnings']} warnings"
    return out


def _materialx(d: Path) -> str:
    try:
        import MaterialX as mx
    except ImportError:
        return "not run"
    doc = mx.createDocument()
    mx.readFromXmlFile(doc, str(d / f"{d.name}.mtlx"))
    ok, message = doc.validate()
    files = [i.getValueString() for n in doc.getNodes() for i in n.getInputs() if i.getType() == "filename"]
    missing = [f for f in files if not (d / f).is_file()]
    return "pass" if ok and files and not missing else f"FAIL {message.strip()[:80]} {missing}"


def _usd(d: Path) -> str:
    try:
        from pxr import Usd, UsdShade
    except ImportError:
        return "not run"
    stage = Usd.Stage.Open(str(d / f"{d.name}.usda"))
    textures = [UsdShade.Shader(p) for p in stage.Traverse()
                if UsdShade.Shader(p) and UsdShade.Shader(p).GetIdAttr().Get() == "UsdUVTexture"]
    unresolved = [t.GetInput("file").Get().path for t in textures
                  if not (t.GetInput("file").Get().resolvedPath and Path(t.GetInput("file").Get().resolvedPath).is_file())]
    return "pass" if textures and not unresolved else f"FAIL unresolved {unresolved}"


def _godot(proj: Path, metal: bool) -> dict[str, str]:
    godot = os.environ.get("GODOT_BIN") or shutil.which("godot")
    names = [d.name for d in (proj / "m").iterdir()]
    if not godot or not Path(godot).exists():
        return {n: "not run" for n in names}
    (proj / "project.godot").write_text('[application]\nconfig/name="matterlift_report"\n')
    (proj / "check.gd").write_text(CHECK)
    subprocess.run([godot, "--headless", "--path", str(proj), "--import"], capture_output=True, timeout=1800)
    run = subprocess.run([godot, "--headless", "--path", str(proj), "-s", "check.gd"],
                         capture_output=True, text=True, timeout=1800)
    log = run.stdout + run.stderr
    broken = "SHADER ERROR" in log or "Shader compilation failed" in log
    rows = {r["name"]: r for r in (json.loads(line.split(" ", 1)[1]) for line in log.splitlines()
                                   if line.startswith("MATTERLIFT "))}
    out = {}
    for n in names:
        r = rows.get(n)
        ok = (r and not broken and r["std"] and r["albedo"] > 0 and r["normal"] and r["roughness"] and r["ao"]
              and r["height"] and r["metal"] == metal and r["uniforms"] >= 15 and r["glb"] and r["glb_materials"] == 1)
        out[n] = (f"pass ({r['uniforms']} shader uniforms)" if ok
                  else f"FAIL {'shader error ' if broken else ''}{r}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--material", default="1a39196022", help="a material id in data/materials")
    ap.add_argument("--sizes", type=int, nargs="+", default=[512, 1024, 2048, 4096])
    args = ap.parse_args()
    mat = load_material(args.material, DATA_DIR)
    if mat is None:
        sys.exit(f"no material {args.material} in {DATA_DIR}")
    metal = mat.plan.metallic > 0

    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp) / "proj"
        (proj / "m").mkdir(parents=True)
        for size in args.sizes:
            for fmt in ("png", "jpg"):
                rows.append({"kind": "size", **_export(mat, size, fmt, proj / "m")})
                print(rows[-1], flush=True)
        for key, shading in SHADINGS.items():
            if key != "plain":
                rows.append({"kind": "shading", "shading": key,
                             **_export(mat, 512, "png", proj / "m", (key, shading))})
                print(rows[-1], flush=True)

        # the example, as downloaded: copied before Godot's import adds its own files next to it
        sample = next(r for r in rows if r["kind"] == "size" and r["size"] == 512 and r["format"] == "png")
        dest = ROOT / "samples" / "export" / sample["package"]
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(proj / "m" / sample["package"], dest)

        dirs = sorted((proj / "m").iterdir())
        khronos, godot = _khronos(dirs), _godot(proj, metal)
        for r in rows:
            d = proj / "m" / r["package"]
            r.update(gltf=khronos.get(r["package"], "not run"), materialx=_materialx(d), usd=_usd(d),
                     godot=godot.get(r["package"], "not run"))
            print(r["package"], r["gltf"], r["materialx"], r["usd"], r["godot"], flush=True)

    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    report = {"date": datetime.now(timezone.utc).isoformat(timespec="seconds"), "material": args.material,
              "name": mat.plan.name, "request": mat.request, "rows": rows}
    (out / "export_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    passed = sum(all(r[k].startswith("pass") for k in ("gltf", "materialx", "usd", "godot")) for r in rows)
    lines = [f"# Export report ({report['date'][:10]})", "",
             f"Material `{mat.plan.name}`, generated by MatterLift from the request \"{mat.request}\" "
             "(text only). Each package is exported the way `GET /materials/{id}/export` does it, then "
             "opened by the official tools: Khronos glTF-Validator (no error, no warning), MaterialX "
             "`validate()` plus every texture on disk, USD (every UsdUVTexture resolves), Godot 4 headless "
             "(StandardMaterial3D with all its textures, the live shader compiles, the .glb imports).", "",
             f"**{passed} of {len(rows)} packages pass all four tools.** The 512 PNG package is in "
             f"[samples/export/{sample['package']}](../samples/export/{sample['package']}).", "",
             "## Sizes and formats", "",
             "| Package | Files | Export + zip (s) | Zip (MB) | glTF | MaterialX | USD | Godot |",
             "|---|---|---|---|---|---|---|---|"]
    cell = lambda v: v.replace("|", "/")  # noqa: E731
    lines += [f"| {r['package']} | {r['files']} | {r['export_zip_s']} | {r['zip_mb']} | {cell(r['gltf'])} | "
              f"{cell(r['materialx'])} | {cell(r['usd'])} | {cell(r['godot'])} |" for r in rows if r["kind"] == "size"]
    lines += ["", "## Shading lobes (512 PNG)", "",
              "| Shading | glTF | MaterialX | USD | Godot |", "|---|---|---|---|---|"]
    lines += [f"| {r['shading']} | {cell(r['gltf'])} | {cell(r['materialx'])} | {cell(r['usd'])} | {cell(r['godot'])} |"
              for r in rows if r["kind"] == "shading"]
    (out / "export_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out / 'export_report.md'}")


if __name__ == "__main__":
    main()
