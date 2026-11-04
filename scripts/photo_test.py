"""Real photos through the deployed API, the way the page drives it: understand (Spark + SAM),
generate, Spark's critique, 1K export. Times every step and keeps what each one returned.

    .venv/Scripts/python scripts/photo_test.py photo1.jpg photo2.jpg[::"what to take"] ... \
        [--api https://matterlift.vercel.app] [--out results/photo_test]

Writes <out>/photo_test.json, and per photo the sampled square (crop) and the albedo. The
photos themselves and SAM's overlay (the whole photo) go to <out>/private/, which is not committed.
"""
from __future__ import annotations

import argparse
import io
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from PIL import Image

API = "https://matterlift.vercel.app"  # the page and the API, one Vercel project


def _timed(fn):
    t = time.perf_counter()
    try:
        return fn(), round(time.perf_counter() - t, 1), None
    except Exception as e:  # noqa: BLE001  every failure is a result here
        return None, round(time.perf_counter() - t, 1), f"{type(e).__name__}: {str(e)[:300]}"


def _ok(r: httpx.Response) -> httpx.Response:
    if r.status_code >= 400:
        raise RuntimeError(f"{r.status_code} {r.text[:300]}")
    return r


def run_one(c: httpx.Client, api: str, path: Path, text: str, out: Path, k: int) -> dict:
    row: dict = {"photo": path.name, "request": text or "(none: the main material)"}
    data = path.read_bytes()
    with Image.open(io.BytesIO(data)) as im:
        row["photo_px"] = list(im.size)

    und, row["understand_s"], err = _timed(lambda: _ok(c.post(
        f"{api}/understand", files={"photo": (path.name, data, "image/jpeg")}, data={"text": text})).json())
    if err:
        return {**row, "error": f"understand: {err}"}
    row.update(understood=und["plan"]["name"], sam_prompt=und["plan"].get("sam_prompt"), matched=und["matched"],
               crop_from=und.get("crop_from"), found_by=und.get("found_by"), spark_sam_s=und["timings"])
    private = out / "private"
    private.mkdir(parents=True, exist_ok=True)
    (private / f"{k}_overlay.jpg").write_bytes(_ok(c.get(api + und["overlay"])).content)
    if und["crops"]:
        Image.open(io.BytesIO(_ok(c.get(api + und["crops"][0])).content)).convert("RGB").save(
            out / f"{k}_crop.jpg", quality=90)

    mat, row["generate_s"], err = _timed(lambda: _ok(c.post(
        f"{api}/materials", data={"understanding": und["id"], "size": "1024"})).json())
    if err:
        return {**row, "error": f"generate: {err}"}
    after = mat["scores"].get("after", {})
    row.update(material_id=mat["id"], plan={k2: mat["plan"][k2] for k2 in ("roughness", "metallic", "detail_kind", "wear")},
               shading={k2: v for k2, v in mat["plan"]["shading"].items() if v and k2 != "ior"} | {"ior": mat["plan"]["shading"]["ior"]},
               stages_s=mat["timings"], seam_before=mat["scores"].get("before", {}).get("seam"),
               seam_after=after.get("seam"), delta_e=mat["scores"].get("fidelity"))
    Image.open(io.BytesIO(_ok(c.get(api + mat["maps"]["albedo"])).content)).convert("RGB").resize(
        (512, 512), Image.LANCZOS).save(out / f"{k}_albedo.jpg", quality=90)

    crit, row["critique_s"], err = _timed(lambda: _ok(c.post(f"{api}/materials/{mat['id']}/critique")).json())
    if err:
        row["critique_error"] = err
    else:
        row.update(score_before=crit["score_before"], score_after=crit["score_after"], kept=crit["chosen"],
                   issues=crit["issues"][:3], params_changed=crit["params_changed"],
                   albedo_fix=crit.get("albedo_fix"))  # a repaint, which the parameters do not show

    chosen = row.get("kept", mat["id"])
    if chosen != mat["id"]:  # the albedo of the version the critique kept
        Image.open(io.BytesIO(_ok(c.get(f"{api}/materials/{chosen}/maps/albedo.png")).content)).convert("RGB").resize(
            (512, 512), Image.LANCZOS).save(out / f"{k}_albedo_kept.jpg", quality=90)
    z, row["export_1k_s"], err = _timed(lambda: _ok(c.get(f"{api}/materials/{chosen}/export",
                                                           params={"size": 1024, "fmt": "png"})).content)
    if err:
        row["export_error"] = err
    else:
        row["export_1k_mb"] = round(len(z) / 1e6, 1)
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("photos", nargs="+", help='photo, or photo::"what to take"')
    ap.add_argument("--api", default=API)
    ap.add_argument("--out", default="results/photo_test")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    with httpx.Client(timeout=600, follow_redirects=True) as c:  # on Vercel, images and zips redirect to Blob
        _ok(c.get(f"{args.api}/health"))  # wakes the container: the first photo is not timed with a cold start
        for k, spec in enumerate(args.photos, 1):
            path, _, text = spec.partition("::")
            row = run_one(c, args.api, Path(path), text, out, k)
            row["n"] = k
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    report = {"date": datetime.now(timezone.utc).isoformat(timespec="seconds"), "api": args.api, "rows": rows}
    (out / "photo_test.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
