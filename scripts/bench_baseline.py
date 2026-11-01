"""Compare maps derived from a reference Color map against the reference's own maps.

Usage: python scripts/bench_baseline.py <ambientCG folder> [--size 1024]
Reference layout: <name>_Color.jpg, _NormalGL.jpg, _Roughness.jpg, _AmbientOcclusion.jpg, _Displacement.jpg
"""
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pbrforge import contact, io, maps  # noqa: E402
from pbrforge.metrics import luminance  # noqa: E402


def _load(folder: Path, suffix: str, size: int) -> np.ndarray | None:
    files = list(folder.glob(f"*_{suffix}.*"))
    if not files:
        return None
    a = io.load(files[0])
    a = io.resize(a, size).clip(0, 1)
    return a if suffix.startswith("Normal") or suffix == "Color" else luminance(a)


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.corrcoef(a.ravel(), b.ravel())[0, 1])


def _angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = a * 2 - 1, b * 2 - 1
    na /= np.linalg.norm(na, axis=-1, keepdims=True)
    nb /= np.linalg.norm(nb, axis=-1, keepdims=True)
    return float(np.degrees(np.arccos(np.clip((na * nb).sum(-1), -1, 1))).mean())


def bench(folder: Path, size: int, params: maps.MapParams,
          guide: np.ndarray | None = None) -> tuple[dict, dict, dict]:
    ref = {
        "albedo": _load(folder, "Color", size),
        "normal": _load(folder, "NormalGL", size),
        "roughness": _load(folder, "Roughness", size),
        "ao": _load(folder, "AmbientOcclusion", size),
        "height": _load(folder, "Displacement", size),
    }
    ref["metallic"] = np.zeros((size, size), np.float32)
    ours = maps.derive(ref["albedo"], params, height_guide=guide)
    flat = np.zeros_like(ref["normal"])
    flat[..., 2] = 1.0
    scores = {
        "height_corr": _corr(ours["height"], ref["height"]),
        "normal_err_deg": _angle_deg(ours["normal"], ref["normal"]),
        "normal_err_flat_deg": _angle_deg(flat * 0.5 + 0.5, ref["normal"]),  # do-nothing baseline
        "ao_corr": _corr(ours["ao"], ref["ao"]),
        "roughness_corr": _corr(ours["roughness"], ref["roughness"]),
        "roughness_mae": float(np.abs(ours["roughness"] - ref["roughness"]).mean()),
        "ref_roughness_mean": float(ref["roughness"].mean()),
    }
    return {k: round(v, 3) for k, v in scores.items()}, ref, ours


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--size", type=int, default=1024)
    ap.add_argument("--out", type=Path, default=Path("samples/out/bench_sheet.png"))
    ap.add_argument("--guide", type=Path, help="height painted by Muse Image from the Color map")
    ap.add_argument("--normal-strength", type=float, default=maps.MapParams.normal_strength)
    args = ap.parse_args()
    guide = luminance(io.load(args.guide)) if args.guide else None
    scores, ref, ours = bench(args.folder, args.size,
                              maps.MapParams(normal_strength=args.normal_strength), guide)
    for k, v in scores.items():
        print(f"{k:22s} {v}")
    contact.sheet([(f"REFERENCE {args.folder.name}", ref),
                   (f"PBRFORGE from Color only: height r={scores['height_corr']}, "
                    f"normal err {scores['normal_err_deg']} deg", ours)]).save(args.out)
    print("sheet:", args.out)
