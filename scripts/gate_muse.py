"""Evening gate: are three materials credible? Raw Muse vs MatterLift, one contact sheet.

Usage: python scripts/gate_muse.py [--size 1024]
Writes samples/gate/gate_sheet.png and samples/gate/gate.json.
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from matterlift_api.pipeline import DATA_DIR, Pipeline  # noqa: E402
from pbrforge import contact, io, maps  # noqa: E402
from pbrforge.metrics import luminance  # noqa: E402

REQUESTS = {
    "stone": "weathered grey flagstone floor, irregular stones, a little moss in the joints",
    "wood": "old oak planks, worn and slightly scratched",
    "rusty_metal": "rusty painted steel plate, orange rust patches with bare grey metal and flaking blue paint",
}


def _load_maps(mid: str) -> dict:
    d = DATA_DIR / mid
    m = {k: io.load(d / f"{k}.png") for k in ("albedo", "normal")}
    for k in ("ao", "roughness", "metallic", "height"):
        m[k] = luminance(io.load(d / f"{k}.png"))
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=1024)
    args = ap.parse_args()
    out = ROOT / "samples" / "gate"
    out.mkdir(parents=True, exist_ok=True)
    pipe = Pipeline()

    def run(item):
        name, text = item
        t = time.perf_counter()
        mat = pipe.run(text, None, args.size)
        print(f"{name}: {mat.id} in {time.perf_counter() - t:.0f}s, after {mat.scores['after']}", flush=True)
        return name, mat

    with ThreadPoolExecutor(3) as ex:
        results = dict(ex.map(run, REQUESTS.items()))

    rows, summary = [], {}
    for name, mat in results.items():
        raw = io.load(DATA_DIR / mat.id / "muse_raw.png")
        rows.append((f"{name} RAW Muse (luminance relief, no clean-up) seam {mat.scores['before']['seam']}",
                     maps.derive(raw, maps.MapParams(), size=args.size)))
        rows.append((f"{name} MATTERLIFT seam {mat.scores['after']['seam']}, "
                     f"blobs {mat.scores['after']['repetition']}%  [{mat.id}]", _load_maps(mat.id)))
        summary[name] = {"id": mat.id, "plan": mat.plan.model_dump(), "scores": mat.scores, "timings": mat.timings}
    contact.sheet(rows, size=384).save(out / "gate_sheet.png")
    (out / "gate.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print("sheet:", out / "gate_sheet.png")


if __name__ == "__main__":
    main()
