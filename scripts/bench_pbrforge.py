"""pbrforge performance: map derivation and export at every size the UI offers, from a 1600 px
albedo (what Muse Image delivers). Offline, no API calls. Writes results/perf_pbrforge.json and
results/perf_pbrforge.md.

    .venv/Scripts/python scripts/bench_pbrforge.py [--repeat 3] [--sizes 512 1024 2048 4096]
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
import tempfile
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pbrforge import export, maps, shaders  # noqa: E402
from tests.test_pbrforge import _noise  # noqa: E402

PARAMS = maps.MapParams(metallic=1.0, detail_kind="stone", detail_strength=0.6, wear=0.4)


def _timed(fn, repeat: int) -> tuple[float, float, object]:
    """Median seconds over `repeat` runs, peak traced memory (MB) of the last one, its result."""
    times, peak, out = [], 0.0, None
    for _ in range(repeat):
        tracemalloc.start()
        t = time.perf_counter()
        out = fn()
        times.append(time.perf_counter() - t)
        peak = tracemalloc.get_traced_memory()[1] / 1e6
        tracemalloc.stop()
    return float(np.median(times)), peak, out


def _machine() -> dict:
    cpu = platform.processor() or platform.machine()
    return {"os": f"{platform.system()} {platform.release()}", "cpu": cpu, "cores": os.cpu_count(),
            "python": platform.python_version(), "numpy": np.__version__}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--sizes", type=int, nargs="+", default=[512, 1024, 2048, 4096])
    args = ap.parse_args()

    albedo = _noise(1600, seed=1)
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for size in args.sizes:
            repeat = 1 if size >= 4096 else args.repeat
            t_derive, mem, m = _timed(lambda: maps.derive(albedo, PARAMS, size=size), repeat)
            lay = shaders.layers(albedo, PARAMS, size, None)
            for fmt in ("png", "jpg"):
                def run():
                    d = export.export_package(m, "bench", Path(tmp) / fmt, fmt, shader_layers=(lay, PARAMS))
                    return export.zip_package(d)
                t_export, _, z = _timed(run, 1)
                rows.append({"size": size, "format": fmt, "derive_s": round(t_derive, 2),
                             "derive_peak_mb": round(mem), "export_zip_s": round(t_export, 2),
                             "zip_mb": round(z.stat().st_size / 1e6, 1)})
                print(rows[-1], flush=True)
                shutil.rmtree(Path(tmp) / fmt)

    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    report = {"date": datetime.now(timezone.utc).isoformat(timespec="seconds"), "machine": _machine(),
              "input": "1600x1600 albedo (Muse Image size), stone detail, wear 0.4, metal", "rows": rows}
    (out / "perf_pbrforge.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    m = report["machine"]
    lines = [f"# pbrforge performance ({report['date'][:10]})", "",
             f"{m['os']}, {m['cpu']}, {m['cores']} threads, Python {m['python']}, NumPy {m['numpy']}. "
             f"Input: {report['input']}. Derive is the median of {args.repeat} runs (1 at 4K); peak memory "
             "is what NumPy allocates during derive.", "",
             "| Size | Format | Derive (s) | Derive peak (MB) | Export + zip (s) | Zip (MB) |",
             "|---|---|---|---|---|---|"]
    lines += [f"| {r['size']} | {r['format'].upper()} | {r['derive_s']} | {r['derive_peak_mb']} | "
              f"{r['export_zip_s']} | {r['zip_mb']} |" for r in rows]
    (out / "perf_pbrforge.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out / 'perf_pbrforge.md'}")


if __name__ == "__main__":
    main()
