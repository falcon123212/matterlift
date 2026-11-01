"""Library mode: one photo of a room -> every material in it, in two steps.

1. understand_library: Spark lists the materials (each one's plan plus two points on it), SAM 3.1
   masks each one from its noun phrase (one concept per request, all in parallel; Spark's points
   pick the right instance), and we pick each sample. The overlay is shown to the user right away.
2. build_library: each sample goes through Muse Image and pbrforge, in parallel.

Box/point prompts can segment 16 objects in one SAM pass, but a point selects an object, not a
surface (one brick instead of the wall) and the masks overlap, so concept prompts win here.
"""
from __future__ import annotations

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from . import overlay
from .locate import Located, locate
from .pipeline import PLAN_SYSTEM, Pipeline, normalize_photo
from .schemas import Library, LibraryItem, LibraryItemPlan

LIBRARY_DIR = Path(__file__).resolve().parents[2] / "data" / "libraries"
MAX_MATERIALS = 8
WORKERS = 6

LIBRARY_SYSTEM = PLAN_SYSTEM.replace(
    "into a plan for a game-ready PBR material. Answer with ONE JSON object only:\n{",
    "into plans for game-ready PBR materials. The photo shows a room or a scene: list the distinct "
    f"surface materials worth turning into textures (walls, floors, furniture tops, metal, fabric), "
    f"at most {MAX_MATERIALS}, largest first, each one once. Answer with ONE JSON object only:\n"
    '{"materials": [{',
).replace("\n}\nValues must be physically plausible",
          "\n}]}\nsam_prompt is required for every material. Values must be physically plausible")


def _try(fn, arg):
    try:
        return fn(arg)
    except Exception as e:  # one failed material must not sink the library
        return e


def understand_library(pipe: Pipeline, photo: Image.Image, request: str = "",
                       root: Path = LIBRARY_DIR) -> Library:
    lid = uuid.uuid4().hex[:10]
    out = root / lid
    out.mkdir(parents=True, exist_ok=True)
    photo = normalize_photo(photo)
    photo.save(out / "photo.jpg", quality=92)
    timings: dict[str, float] = {}

    t = time.perf_counter()
    user = "List the materials in this photo." + (f" The user asks: {request}" if request else "")
    raw = pipe.client.chat_json(LIBRARY_SYSTEM, user, [photo])
    listed = raw.get("materials", []) if isinstance(raw, dict) else []
    plans = [LibraryItemPlan.lenient(m) for m in listed if isinstance(m, dict)][:MAX_MATERIALS]
    if not plans:
        raise RuntimeError("Spark listed no material in this photo")
    timings["spark_list"] = time.perf_counter() - t

    t = time.perf_counter()
    with ThreadPoolExecutor(WORKERS) as ex:
        located = list(ex.map(lambda p: _try(lambda q: locate(pipe.client, photo, q), p), plans))
    timings["sam_masks"] = time.perf_counter() - t

    items, drawn = [], []
    for i, (plan, loc) in enumerate(zip(plans, located)):
        if isinstance(loc, Exception):
            loc = Located(tried=[f"error: {str(loc)[:120]}"])
        crops = []
        for k, im in enumerate(loc.samples):
            im.save(out / f"crop_{i}_{k}.png")
            crops.append(f"/libraries/{lid}/crop_{i}_{k}.png")
        b = loc.seg.box if loc.seg else None
        note = None if loc.found else f"not found in the photo ({', '.join(loc.tried)}): painted from its description"
        items.append(LibraryItem(plan=plan, crops=crops, crop_from=loc.how, found_by=loc.found_by,
                                 sam_box=[b.x1, b.y1, b.x2, b.y2] if b else None, error=note))
        drawn.append((plan.name, loc.seg.mask if loc.seg else None, loc.regions))
    overlay.draw(photo, drawn).save(out / "overlay.jpg", quality=90)

    lib = Library(id=lid, request=request, photo=f"/libraries/{lid}/photo.jpg",
                  overlay=f"/libraries/{lid}/overlay.jpg", items=items, status="understood",
                  timings={k: round(v, 2) for k, v in timings.items()})
    _save(lib, root)
    return lib


def build_library(pipe: Pipeline, lib: Library, size: int = 1024, root: Path = LIBRARY_DIR) -> Library:
    out = root / lib.id

    def build(args) -> LibraryItem:
        i, item = args
        if item.material is not None:
            return item
        try:
            t0 = time.perf_counter()
            samples = [Image.open(out / f"crop_{i}_{k}.png").convert("RGB") for k in range(len(item.crops))]
            raw, source, note = pipe.albedo_with_fallback(item.plan, samples)
            extra = {"sam_box": item.sam_box, "crop_from": item.crop_from, "found_by": item.found_by,
                     "samples": samples, "library": lib.id, **note}
            mat = pipe.finish(item.plan, f"{lib.request} [{item.plan.name}]".strip(), raw, source, extra,
                              size, {"muse_image": time.perf_counter() - t0})
            return item.model_copy(update={"material": mat})
        except Exception as e:
            return item.model_copy(update={"error": f"generation failed: {str(e)[:250]}"})

    t = time.perf_counter()
    with ThreadPoolExecutor(WORKERS) as ex:
        items = list(ex.map(build, enumerate(lib.items)))
    timings = {**lib.timings, "materials": round(time.perf_counter() - t, 2)}
    lib = lib.model_copy(update={"items": items, "status": "built", "timings": timings})
    _save(lib, root)
    return lib


def _save(lib: Library, root: Path) -> None:
    (root / lib.id / "library.json").write_text(lib.model_dump_json(indent=2), encoding="utf-8")


def load_library(lid: str, root: Path = LIBRARY_DIR) -> Library | None:
    p = root / lid / "library.json"
    return Library.model_validate(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else None
