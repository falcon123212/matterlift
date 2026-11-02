"""Library mode: one photo of a room -> every material in it, in two steps.

1. understand_library: Spark lists the materials (each one's plan plus two points on it), SAM 3.1
   masks each one from its noun phrase (one concept per request, all in parallel; Spark's points
   pick the right instance), and we pick each sample. The overlay is shown to the user right away.
   Manual mode: the user's points replace Spark's listing. For each group of points Spark sees the
   photo with markers and plans the material under them; SAM then masks it, framed by Spark's noun
   phrase (the instance under the points) or, unframed, by the points alone.
2. build_library: each sample goes through Muse Image and pbrforge, in parallel.

The user can then add a material at new points, redo one item's mask, or remove one; build again
makes only the items that have no material yet.

Box/point prompts can segment 16 objects in one SAM pass, but a point selects an object, not a
surface (one brick instead of the wall) and the masks overlap, so concept prompts win here.
"""
from __future__ import annotations

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import overlay
from .locate import Located, locate
from .pipeline import PLAN_SYSTEM, Pipeline, normalize_photo
from .schemas import Library, LibraryItem, LibraryItemPlan

LIBRARY_DIR = Path(__file__).resolve().parents[2] / "data" / "libraries"
MAX_MATERIALS = 8
MAX_MANUAL = 12  # point groups in one library
MAX_POINTS = 3  # points per group
WORKERS = 6

LIBRARY_SYSTEM = PLAN_SYSTEM.replace(
    "into a plan for a game-ready PBR material. Answer with ONE JSON object only:\n{",
    "into plans for game-ready PBR materials. The photo shows a room or a scene: list the distinct "
    f"surface materials worth turning into textures (walls, floors, furniture tops, metal, fabric), "
    f"at most {MAX_MATERIALS}, largest first, each one once. Answer with ONE JSON object only:\n"
    '{"materials": [{',
).replace("\n}\nValues must be physically plausible",
          "\n}]}\nsam_prompt is required for every material. Values must be physically plausible")

POINT_REQUEST = (
    "The user clicked this photo where the red marker{s} with a white ring {are}. They want the "
    "material of the surface or object under {it} as a texture: plan that one material only. "
    "sam_prompt and sam_alternatives must name that surface as SAM would find it (the one under "
    "the marker, not the whole scene)."
)

Points = list[tuple[float, float]]  # [x, y] in 0..1000, as in a plan


def _try(fn, arg):
    try:
        return fn(arg)
    except Exception as e:  # one failed material must not sink the library
        return e


def clean_points(groups) -> list[Points]:
    """The user's point groups, clamped to 0..1000; rejects anything that is not [[x, y], ...]."""
    if not isinstance(groups, list) or not groups or len(groups) > MAX_MANUAL:
        raise ValueError(f"points: 1 to {MAX_MANUAL} groups of [x, y] in 0..1000")
    out = []
    for g in groups:
        if not isinstance(g, list) or not 1 <= len(g) <= MAX_POINTS:
            raise ValueError(f"points: each group has 1 to {MAX_POINTS} [x, y]")
        pts = []
        for p in g:
            if not (isinstance(p, list) and len(p) == 2 and all(isinstance(v, (int, float)) for v in p)):
                raise ValueError("points: each point is [x, y]")
            pts.append((min(1000.0, max(0.0, float(p[0]))), min(1000.0, max(0.0, float(p[1])))))
        out.append(pts)
    return out


def _marked(photo: Image.Image, points: Points) -> Image.Image:
    """The photo with a ringed marker on each point, for Spark."""
    img = photo.copy()
    d = ImageDraw.Draw(img)
    r = max(6, round(min(img.size) / 60))
    for x, y in points:
        cx, cy = x * img.width / 1000, y * img.height / 1000
        d.ellipse([cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3], outline=(255, 255, 255), width=3)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(230, 30, 40))
    return img


def plan_at(pipe: Pipeline, photo: Image.Image, points: Points, request: str = "") -> LibraryItemPlan:
    many = len(points) > 1
    user = POINT_REQUEST.format(s="s" if many else "", are="are" if many else "is", it="them" if many else "it")
    if request:
        user += f" The user also says: {request}"
    plan = LibraryItemPlan.lenient(pipe.client.chat_json(PLAN_SYSTEM, user, [_marked(photo, points)]))
    if not plan.texture_prompt:
        plan = plan.model_copy(update={"texture_prompt": plan.name.replace("_", " ") or request or "surface"})
    # the user's points place it, whatever Spark answered
    return plan.model_copy(update={"points": points})


def _store(out: Path, lid: str, key: int, plan: LibraryItemPlan, loc: Located | Exception,
           manual: bool) -> LibraryItem:
    if isinstance(loc, Exception):
        loc = Located(tried=[f"error: {str(loc)[:120]}"])
    crops = []
    for k, im in enumerate(loc.samples):
        im.save(out / f"crop_{key}_{k}.png")
        crops.append(f"/libraries/{lid}/crop_{key}_{k}.png")
    if loc.seg is not None:
        Image.fromarray(loc.seg.mask).save(out / f"mask_{key}.png")
    b = loc.seg.box if loc.seg else None
    note = None if loc.found else f"not found in the photo ({', '.join(loc.tried)}): painted from its description"
    return LibraryItem(plan=plan, crops=crops, crop_from=loc.how, found_by=loc.found_by,
                       sam_box=[b.x1, b.y1, b.x2, b.y2] if b else None, error=note, key=key,
                       regions=[list(r) for r in loc.regions], manual=manual)


def _redraw(lib: Library, root: Path) -> Library:
    """Overlay of every item from its saved mask and regions; a new URL so browsers reload it."""
    out = root / lib.id
    photo = Image.open(out / "photo.jpg").convert("RGB")
    drawn = []
    for i, item in enumerate(lib.items):
        key = item.key if item.key is not None else i
        m = out / f"mask_{key}.png"
        mask = np.asarray(Image.open(m)).astype(bool) if m.exists() else None
        drawn.append((item.plan.name, mask, [tuple(r) for r in item.regions]))
    overlay.draw(photo, drawn).save(out / "overlay.jpg", quality=90)
    return lib.model_copy(update={"overlay": f"/libraries/{lib.id}/overlay.jpg?v={int(time.time() * 1000)}"})


def understand_library(pipe: Pipeline, photo: Image.Image, request: str = "",
                       root: Path = LIBRARY_DIR, points: list[Points] | None = None,
                       frame: bool = True) -> Library:
    lid = uuid.uuid4().hex[:10]
    out = root / lid
    out.mkdir(parents=True, exist_ok=True)
    photo = normalize_photo(photo)
    photo.save(out / "photo.jpg", quality=92)
    timings: dict[str, float] = {}

    t = time.perf_counter()
    if points:
        with ThreadPoolExecutor(WORKERS) as ex:
            plans = list(ex.map(lambda g: plan_at(pipe, photo, g, request), points))
        timings["spark_points"] = time.perf_counter() - t
    else:
        user = "List the materials in this photo." + (f" The user asks: {request}" if request else "")
        raw = pipe.client.chat_json(LIBRARY_SYSTEM, user, [photo])
        listed = raw.get("materials", []) if isinstance(raw, dict) else []
        plans = [LibraryItemPlan.lenient(m) for m in listed if isinstance(m, dict)][:MAX_MATERIALS]
        if not plans:
            raise RuntimeError("Spark listed no material in this photo")
        timings["spark_list"] = time.perf_counter() - t

    t = time.perf_counter()
    with ThreadPoolExecutor(WORKERS) as ex:
        located = list(ex.map(lambda p: _try(lambda q: locate(pipe.client, photo, q, frame), p), plans))
    timings["sam_masks"] = time.perf_counter() - t

    items = [_store(out, lid, i, plan, loc, bool(points)) for i, (plan, loc) in enumerate(zip(plans, located))]
    lib = Library(id=lid, request=request, photo=f"/libraries/{lid}/photo.jpg",
                  overlay=f"/libraries/{lid}/overlay.jpg", items=items, status="understood",
                  timings={k: round(v, 2) for k, v in timings.items()})
    lib = _redraw(lib, root)
    _save(lib, root)
    return lib


def point_item(pipe: Pipeline, lib: Library, points: Points, frame: bool = True, index: int | None = None,
               root: Path = LIBRARY_DIR) -> Library:
    """Adds a material at the user's points, or (index) redoes that item's mask and plan from them.
    The new item has no material yet: build_library makes it."""
    if index is not None and not 0 <= index < len(lib.items):
        raise IndexError("no such item")
    if index is None and len(lib.items) >= MAX_MANUAL + MAX_MATERIALS:
        raise ValueError("this library is full")
    out = root / lib.id
    photo = Image.open(out / "photo.jpg").convert("RGB")
    plan = plan_at(pipe, photo, points, lib.request)
    loc = _try(lambda p: locate(pipe.client, photo, p, frame), plan)
    used = [i.key if i.key is not None else n for n, i in enumerate(lib.items)]
    item = _store(out, lib.id, max(used, default=-1) + 1, plan, loc, True)
    items = list(lib.items)
    if index is None:
        items.append(item)
    else:
        items[index] = item
    lib = lib.model_copy(update={"items": items, "status": "understood"})
    lib = _redraw(lib, root)
    _save(lib, root)
    return lib


def remove_item(lib: Library, index: int, root: Path = LIBRARY_DIR) -> Library:
    if not 0 <= index < len(lib.items):
        raise IndexError("no such item")
    items = [it for n, it in enumerate(lib.items) if n != index]
    lib = _redraw(lib.model_copy(update={"items": items}), root)
    _save(lib, root)
    return lib


def build_library(pipe: Pipeline, lib: Library, size: int = 1024, root: Path = LIBRARY_DIR) -> Library:
    out = root / lib.id

    def build(item: LibraryItem) -> LibraryItem:
        if item.material is not None:
            return item
        try:
            t0 = time.perf_counter()
            samples = [Image.open(out / Path(url).name).convert("RGB") for url in item.crops]
            raw, source, note = pipe.albedo_with_fallback(item.plan, samples)
            extra = {"sam_box": item.sam_box, "crop_from": item.crop_from, "found_by": item.found_by,
                     "samples": samples, "library": lib.id, **note}
            mat = pipe.finish(item.plan, f"{lib.request} [{item.plan.name}]".strip(), raw, source, extra,
                              size, {"muse_image": time.perf_counter() - t0})
            # a previous failure is cleared; the "painted from its description" note stays
            failed = item.error and item.error.startswith("generation failed")
            return item.model_copy(update={"material": mat, "error": None if failed else item.error})
        except Exception as e:
            return item.model_copy(update={"error": f"generation failed: {str(e)[:250]}"})

    t = time.perf_counter()
    with ThreadPoolExecutor(WORKERS) as ex:
        items = list(ex.map(build, lib.items))
    timings = {**lib.timings, "materials": round(time.perf_counter() - t, 2)}
    lib = lib.model_copy(update={"items": items, "status": "built", "timings": timings})
    _save(lib, root)
    return lib


def _save(lib: Library, root: Path) -> None:
    (root / lib.id / "library.json").write_text(lib.model_dump_json(indent=2), encoding="utf-8")


def load_library(lid: str, root: Path = LIBRARY_DIR) -> Library | None:
    p = root / lid / "library.json"
    return Library.model_validate(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else None
