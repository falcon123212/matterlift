"""Spark reviews a finished material like a senior material artist, fixes it, and judges the result.

1. A review sheet: the material on a sphere under a raking light (relief, seams, flat normals),
   tiled 3x3 (repetition, standout features) and, for a photo material, the photo sample (fidelity).
2. Spark scores it, lists what is wrong, and proposes new parameter values and, only for faults in
   the colour texture itself, one instruction for Muse to repaint the albedo.
3. Parameter fixes are re-derived at once (no new image); a repaint goes back through Muse and
   pbrforge. Spark reviews the new version too, and the better-scored one is kept.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import pbrforge
from pbrforge import color, contact, delight
from pbrforge import io as pio
from pbrforge.metrics import luminance

from .pipeline import Pipeline, load_material
from .schemas import Critique, Material, MaterialPlan

TUNABLE = ("normal_strength", "height_strength", "roughness", "roughness_variation", "detail_strength", "wear")

CRITIQUE_SYSTEM = """You are a senior material artist reviewing a game-ready PBR material before it ships. The image shows, left to right: the material on a sphere under a low raking light (reveals relief, flat or noisy normals, seams), the texture tiled 3x3 and, when present, the photo sample it was made from. The 3x3 view repeats ONE tile on purpose: repetition of the whole tile is expected and is not a fault. Judge only: visible seams at tile edges, a single standout feature or blotch that forms a grid, baked shadows or highlights, relief too flat or too strong, wrong shininess, missing wear the request asked for, colour unlike the photo sample. Score anchors: 9-10 ships in a AAA game, 7-8 good indie quality, 5-6 usable with visible flaws, 3-4 clearly wrong. Answer with ONE JSON object only:
{
 "score": integer 1..10,
 "issues": [short sentences, each one visible problem; empty if none],
 "params": {only the parameters to change, with new absolute values, among: "normal_strength" 0.3..2.5, "height_strength" 0.3..1.5, "roughness" 0..1, "roughness_variation" 0..0.5, "detail_strength" 0..1, "wear" 0..1},
 "match_photo_colour": true only if the colour clearly differs from the photo sample,
 "albedo_fix": "" or ONE instruction to repaint the colour texture, only for baked shadows or highlights, a standout feature that forms a grid, or seams; never for colour (use match_photo_colour), relief or shininess (use params), and never to "break the repetition"
}"""

COMPARE_SYSTEM = """You are a senior material artist. Two versions of the same PBR material are shown, A on top and B below, each as: sphere under raking light, the texture tiled 3x3 (one tile repeated on purpose, not a fault), and the photo sample when present. Same score anchors: 9-10 AAA, 7-8 good indie, 5-6 usable with flaws, 3-4 clearly wrong. Answer with ONE JSON object only:
{"score_a": integer 1..10, "score_b": integer 1..10, "better": "A" or "B", "remaining": [short sentences: problems still visible in the better one]}"""


def review_sheet(mat: Material, data_dir: Path, size: int = 384) -> Image.Image:
    """Sphere under raking light | 3x3 tiling | photo sample (if any), labelled."""
    d = data_dir / mat.id
    maps = {k: pio.load(d / f"{k}.png") for k in ("albedo", "normal")}
    for k in ("ao", "roughness", "metallic"):
        maps[k] = luminance(pio.load(d / f"{k}.png"))
    panels = [("raking light", pio.to_pil(contact.render_sphere(maps, size, tiles=2, light=(-0.9, 0.3, 0.3)))),
              ("tiled 3x3", pio.to_pil(contact.tiled(maps["albedo"], 3, size)))]
    sample = d / "photo_sample_0.png"
    if sample.exists():
        im = Image.open(sample).convert("RGB")
        side = min(im.size)
        panels.append(("photo sample", im.crop((0, 0, side, side)).resize((size, size), Image.LANCZOS)))
    sheet = Image.new("RGB", (len(panels) * (size + 8) + 8, size + 40), (20, 20, 22))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=18)
    for i, (label, im) in enumerate(panels):
        x = 8 + i * (size + 8)
        sheet.paste(im, (x, 32))
        draw.text((x, 6), label, fill=(230, 230, 230), font=font)
    return sheet


def _ask(pipe: Pipeline, mat: Material, sheet: Image.Image) -> dict:
    current = {k: round(getattr(mat.plan, k), 2) for k in TUNABLE}
    user = (f"Material: {mat.plan.name}. Requested as: \"{mat.request}\". Current parameters: {current}. "
            f"Detail layer: {mat.plan.detail_kind}.")
    raw = pipe.client.chat_json(CRITIQUE_SYSTEM, user, [sheet])
    raw = raw if isinstance(raw, dict) else {}
    try:
        score = int(round(float(raw.get("score", 5))))
    except (TypeError, ValueError):
        score = 5
    listed = raw.get("issues")
    listed = listed if isinstance(listed, list) else [listed] if isinstance(listed, str) and listed else []
    issues = [str(i)[:200] for i in listed if isinstance(i, (str, int, float))][:6]
    params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
    params = {k: v for k, v in params.items() if k in TUNABLE and isinstance(v, (int, float))}
    fix = raw.get("albedo_fix") if isinstance(raw.get("albedo_fix"), str) else ""
    return {"score": max(1, min(10, score)), "issues": issues, "params": params, "albedo_fix": fix.strip()[:300],
            "colour": raw.get("match_photo_colour") is True}


def _int(v, default: int) -> int:
    try:
        return max(1, min(10, int(round(float(v)))))
    except (TypeError, ValueError):
        return default


def _compare(pipe: Pipeline, before: Image.Image, after: Image.Image) -> dict:
    """One side-by-side judgement: steadier than two separate scores."""
    w = max(before.width, after.width)
    both = Image.new("RGB", (w, before.height + after.height + 30), (20, 20, 22))
    both.paste(before, (0, 0))
    both.paste(after, (0, before.height + 30))
    d = ImageDraw.Draw(both)
    font = ImageFont.load_default(size=22)
    d.text((w - 40, 6), "A", fill=(255, 220, 80), font=font)
    d.text((w - 40, before.height + 36), "B", fill=(255, 220, 80), font=font)
    raw = pipe.client.chat_json(COMPARE_SYSTEM, "Compare A (before) and B (after the fixes).", [both])
    raw = raw if isinstance(raw, dict) else {}
    a, b = _int(raw.get("score_a"), 5), _int(raw.get("score_b"), 5)
    better = raw.get("better") if raw.get("better") in ("A", "B") else ("B" if b > a else "A")
    rem = raw.get("remaining")
    rem = rem if isinstance(rem, list) else [rem] if isinstance(rem, str) and rem else []
    return {"score_a": a, "score_b": b, "better": better, "remaining": [str(r)[:200] for r in rem][:6]}


def _revise(pipe: Pipeline, mat: Material, params: dict, albedo_fix: str, colour: bool = False) -> Material:
    d = pipe.data_dir / mat.id
    plan = MaterialPlan.lenient({**mat.plan.model_dump(), **params})
    samples = [Image.open(p).convert("RGB") for p in sorted(d.glob("photo_sample_*.png"))]
    keep = {k: v for k, v in mat.scores.items() if k not in ("critique",)}
    timings: dict[str, float] = {}
    if albedo_fix:
        t = time.perf_counter()
        albedo = pio.to_pil(pio.load(d / "albedo_source.png"))
        raw = pipe.client.edit_image(
            # Not "tileable": that word makes Muse lay copies side by side with visible joins.
            albedo, f"{albedo_fix}. Keep one continuous top-down texture of the same material filling "
                    "the whole frame, same pattern scale, flat even lighting.")
        timings["muse_repaint"] = time.perf_counter() - t
        extra = {k: v for k, v in keep.items() if k not in ("before", "after", "fidelity")}
        return pipe.finish(plan, mat.request, raw, mat.source, {**extra, "samples": samples}, mat.size, timings)
    guide_path = d / "muse_height.png"
    guide = luminance(pio.load(guide_path)) if guide_path.exists() else None
    albedo = pio.load(d / "albedo_source.png")
    if colour and samples:  # deterministic, unlike a repaint: full-strength match to the photo
        albedo, fidelity = color.match_to_samples(albedo, [pio.from_pil(s) for s in samples],
                                                  strength=(0.85, 1.0, 1.0))
        albedo = delight.fit_pbr_range(albedo)
        keep["fidelity"] = fidelity
    return pipe.save_material(plan, mat.request, mat.source, albedo, guide, keep, samples, mat.size, timings)


def critique(pipe: Pipeline, mat: Material) -> Critique:
    t0 = time.perf_counter()
    sheet = review_sheet(mat, pipe.data_dir)
    sheet.save(pipe.data_dir / mat.id / "review.png")
    first = _ask(pipe, mat, sheet)
    if not first["params"] and not first["albedo_fix"] and not first["colour"]:
        return Critique(before=mat.id, after=mat.id, chosen=mat.id, score_before=first["score"],
                        score_after=first["score"], issues=first["issues"], params_changed={}, albedo_fix="",
                        review_before=f"/materials/{mat.id}/maps/review.png", review_after=None,
                        seconds=round(time.perf_counter() - t0, 1))
    try:
        after = _revise(pipe, mat, first["params"], first["albedo_fix"], first["colour"])
    except RuntimeError:  # the repaint failed: parameter and colour fixes alone
        after = _revise(pipe, mat, first["params"], "", first["colour"])
        first["albedo_fix"] = ""
    sheet_after = review_sheet(after, pipe.data_dir)
    sheet_after.save(pipe.data_dir / after.id / "review.png")
    verdict = _compare(pipe, sheet, sheet_after)
    chosen = after if verdict["better"] == "B" else mat
    result = Critique(
        before=mat.id, after=after.id, chosen=chosen.id, score_before=verdict["score_a"],
        score_after=verdict["score_b"], issues=first["issues"], remaining=verdict["remaining"],
        params_changed={k: [round(getattr(mat.plan, k), 2), round(float(v), 2)] for k, v in first["params"].items()},
        albedo_fix=first["albedo_fix"], colour_matched=first["colour"],
        review_before=f"/materials/{mat.id}/maps/review.png",
        review_after=f"/materials/{after.id}/maps/review.png", seconds=round(time.perf_counter() - t0, 1))
    _record(pipe, after, result)
    return result


def _record(pipe: Pipeline, mat: Material, result: Critique) -> None:
    """Keep the critique with the revised material, so reopening it shows the story."""
    updated = mat.model_copy(update={"scores": {**mat.scores, "critique": result.model_dump()}})
    (pipe.data_dir / mat.id / "material.json").write_text(updated.model_dump_json(indent=2), encoding="utf-8")


def critique_by_id(pipe: Pipeline, mid: str) -> Critique | None:
    mat = load_material(mid, pipe.data_dir)
    return critique(pipe, mat) if mat else None
