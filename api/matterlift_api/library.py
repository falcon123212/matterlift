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
from .meta_client import Segment
from .pipeline import PLAN_SYSTEM, Pipeline, sample_square
from .schemas import Library, LibraryItem, LibraryItemPlan

LIBRARY_DIR = Path(__file__).resolve().parents[2] / "data" / "libraries"
MAX_MATERIALS = 8
WORKERS = 6

LIBRARY_SYSTEM = PLAN_SYSTEM.replace(
    "into a plan for a game-ready PBR material. Answer with ONE JSON object only:\n{",
    "into plans for game-ready PBR materials. The photo shows a room or a scene: list the distinct "
    f"surface materials worth turning into textures (walls, floors, furniture tops, metal, fabric), "
    f"at most {MAX_MATERIALS}, largest first, each one once. Answer with ONE JSON object only:\n"
    '{"materials": [{\n "points": two [x, y] points in 0..1000 image coordinates (0,0 top-left) on '
    "clean, flat, unoccluded areas of that surface, far from its edges and from objects on it,",
).replace("\n}\nValues must be physically plausible",
          "\n}]}\nsam_prompt is required for every material. Values must be physically plausible")


def _pick(segments: list[Segment], points: list[tuple[int, int]]) -> Segment | None:
    """The instance under Spark's points, else the largest."""
    for s in segments:
        if any(0 <= y < s.mask.shape[0] and 0 <= x < s.mask.shape[1] and s.mask[y, x] for x, y in points):
            return s
    return segments[0] if segments else None


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
    photo = photo.convert("RGB")
    photo.save(out / "photo.jpg", quality=92)
    timings: dict[str, float] = {}

    t = time.perf_counter()
    user = "List the materials in this photo." + (f" The user asks: {request}" if request else "")
    raw = pipe.client.chat_json(LIBRARY_SYSTEM, user, [photo])
    plans = [LibraryItemPlan.model_validate(m) for m in raw.get("materials", [])][:MAX_MATERIALS]
    timings["spark_list"] = time.perf_counter() - t

    def segment(plan: LibraryItemPlan) -> Segment | None:
        pts = [(int(x * photo.width / 1000), int(y * photo.height / 1000)) for x, y in plan.points]
        return _pick(pipe.client.segment(photo, plan.sam_prompt or plan.name.replace("_", " ")), pts)

    t = time.perf_counter()
    with ThreadPoolExecutor(WORKERS) as ex:
        segments = list(ex.map(lambda p: _try(segment, p), plans))
    timings["sam_masks"] = time.perf_counter() - t

    items, drawn = [], []
    for i, (plan, seg) in enumerate(zip(plans, segments)):
        if isinstance(seg, Exception) or seg is None:
            err = f"SAM found no '{plan.sam_prompt}'" if seg is None else str(seg)[:300]
            items.append(LibraryItem(plan=plan, error=err))
            drawn.append((plan.name, None, None))
            continue
        crop, how, square = sample_square(photo, seg)
        crop.save(out / f"crop_{i}.png")
        items.append(LibraryItem(plan=plan, crop=f"/libraries/{lid}/crop_{i}.png", crop_from=how,
                                 sam_box=[seg.box.x1, seg.box.y1, seg.box.x2, seg.box.y2]))
        drawn.append((plan.name, seg.mask, square))
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
        if item.crop is None or item.material is not None:
            return item
        try:
            t0 = time.perf_counter()
            crop = Image.open(out / f"crop_{i}.png").convert("RGB")
            raw = pipe.albedo_from_crop(item.plan, crop)
            extra = {"sam_box": item.sam_box, "crop_from": item.crop_from, "crop": crop, "library": lib.id}
            mat = pipe.finish(item.plan, f"{lib.request} [{item.plan.name}]".strip(), raw, "photo", extra,
                              size, {"muse_image": time.perf_counter() - t0})
            return item.model_copy(update={"material": mat})
        except Exception as e:
            return item.model_copy(update={"error": str(e)[:300]})

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
