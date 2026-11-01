"""photo + request -> Spark (plan) -> SAM 3.1 (mask) -> sample -> [understanding shown to the user]
-> Muse Image -> pbrforge -> Muse height -> maps."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

import pbrforge
from pbrforge import io as pio
from pbrforge import color, contact, delight, export, seamless
from pbrforge.metrics import luminance

from . import overlay
from .locate import locate
from .meta_client import MetaClient
from .schemas import Material, MaterialPlan, Understanding

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "materials"
UNDERSTAND_DIR = DATA_DIR.parent / "understand"

TEXTURE_SUFFIX = (
    "Seamless tileable PBR albedo texture, orthographic top-down view, the material fills the "
    "whole frame edge to edge, flat even diffuse lighting, no shadows, no specular highlights, "
    "no perspective, no objects, no text, no single standout feature."
)

HEIGHT_PROMPT = (
    "Convert this texture into its grayscale height map (displacement map) for 3D rendering: "
    "joints, gaps and cracks black, raised surfaces white with subtle surface relief, keep every "
    "edge exactly aligned with the input, same framing, no shading, no colour."
)

PLAN_SYSTEM ="""You are the technical artist of MatterLift. You turn a user's request (and an \
optional photo) into a plan for a game-ready PBR material. Answer with ONE JSON object only:
{
 "name": short snake_case name,
 "texture_prompt": what the albedo should show, material only, as a painter would describe the \
surface seen straight on (colour, pattern, wear, scale); never mention lighting or 3D objects,
 "sam_prompt": if a photo is given, a 1-3 word noun phrase naming the surface to sample in it \
(the object it covers works best: "table", "floor", "brick wall"), else "",
 "sam_alternatives": if a photo is given, two other short noun phrases for the same surface, \
else [],
 "points": if a photo is given, two [x, y] points in 0..1000 image coordinates (0,0 top-left) on \
clean, flat, unoccluded areas of that surface, far from its edges and from objects on it, else [],
 "roughness": 0..1, "roughness_variation": 0..0.5, "metallic": 0..1,
 "metal_on_desaturated": true only for rusty or painted metal where grey areas are bare metal,
 "height_strength": 0.3..1.5, "normal_strength": 0.3..2 (rough stone 1.5, brick 1, wood 0.6, fabric 0.5, metal 0.4),
 "detail": 0.5..2 (fine surface grain),
 "detail_kind": the procedural micro-detail layered on top, one of "wood", "stone", "fabric", \
"metal", "plaster", "none",
 "detail_strength": 0..1 (0.3 subtle, 0.6 clearly visible up close),
 "wear": 0..1 (0 new, 0.4 used, 0.8 old and worn: lighter rubbed edges, dirt in recesses),
 "shading": {"transmission": 0..1, "ior": 1..2.4, "clearcoat": 0..1, "clearcoat_roughness": 0..1,
             "sheen": 0..1, "subsurface": 0..1, "anisotropy": 0..1}
}
Values must be physically plausible for the material."""


MAX_PHOTO_SIDE = 2048


def normalize_photo(img: Image.Image) -> Image.Image:
    """Upright (phone photos carry their rotation in EXIF), RGB, at most MAX_PHOTO_SIDE px.
    SAM's coordinates and Spark's points are only consistent on the upright image."""
    img = ImageOps.exif_transpose(img).convert("RGB")
    if max(img.size) > MAX_PHOTO_SIDE:
        img.thumbnail((MAX_PHOTO_SIDE, MAX_PHOTO_SIDE), Image.LANCZOS)
    return img


class Pipeline:
    def __init__(self, client: MetaClient | None = None, data_dir: Path = DATA_DIR,
                 understand_dir: Path = UNDERSTAND_DIR):
        self.client = client or MetaClient()
        self.data_dir = data_dir
        self.understand_dir = understand_dir

    def plan(self, request: str, photo: Image.Image | None) -> MaterialPlan:
        user = f"Request: {request}"
        if photo is not None:
            user += "\nThe photo shows the real surface to sample."
        raw = self.client.chat_json(PLAN_SYSTEM, user, [photo] if photo is not None else None)
        plan = MaterialPlan.lenient(raw)
        if not plan.texture_prompt:  # the one field Muse cannot do without
            plan = plan.model_copy(update={"texture_prompt": request})
        return plan

    def albedo_from_text(self, plan: MaterialPlan) -> Image.Image:
        return self.client.generate_image(f"{plan.texture_prompt}. {TEXTURE_SUFFIX}")

    def albedo_with_fallback(self, plan: MaterialPlan, samples: list[Image.Image]) -> tuple[Image.Image, str, dict]:
        """From the photo samples when there are some; from the description if there are none or
        the edit fails, so a material always comes out."""
        if samples:
            try:
                return self.albedo_from_samples(plan, samples), "photo", {}
            except RuntimeError as e:
                note = {"muse_edit_failed": str(e)[:200]}
        else:
            note = {}
        return self.albedo_from_text(plan), "text", note

    def albedo_from_samples(self, plan: MaterialPlan, samples: list[Image.Image]) -> Image.Image:
        """Muse turns the photo samples (one surface, several areas) into a flat, tileable texture."""
        prompt = f"{plan.texture_prompt}. {TEXTURE_SUFFIX}"
        lead = ("Turn this photo sample" if len(samples) == 1 else
                f"These {len(samples)} photos are samples of the same real surface. Turn them")
        return self.client.edit_image(
            samples,
            f"{lead} into one {prompt[0].lower()}{prompt[1:]} Keep the pattern elements (tiles, bricks, "
            "planks, grain, weave) as large relative to the frame as they appear in the first sample.",
        )

    def understand(self, request: str, photo: Image.Image) -> Understanding:
        """Spark reads the request and the photo, SAM masks the surface, we pick the sample.
        Saved so generation can resume from it; shown to the user before Muse runs."""
        uid = uuid.uuid4().hex[:10]
        d = self.understand_dir / uid
        d.mkdir(parents=True, exist_ok=True)
        photo = normalize_photo(photo)
        photo.save(d / "photo.jpg", quality=92)
        timings: dict[str, float] = {}

        t = time.perf_counter()
        plan = self.plan(request, photo)
        timings["spark_plan"] = time.perf_counter() - t

        t = time.perf_counter()
        loc = locate(self.client, photo, plan)
        timings["sam_mask"] = time.perf_counter() - t
        crops = []
        for k, im in enumerate(loc.samples):
            im.save(d / f"crop_{k}.png")
            crops.append(f"/understand/{uid}/crop_{k}.png")
        if loc.seg is not None:
            Image.fromarray(loc.seg.mask).save(d / "mask.png")
        overlay.draw(photo, [(plan.name, loc.seg.mask if loc.seg else None, loc.regions)]).save(
            d / "overlay.jpg", quality=90)

        b = loc.seg.box if loc.seg else None
        und = Understanding(id=uid, request=request, plan=plan, matched=loc.found, crop_from=loc.how,
                            found_by=loc.found_by, sam_box=[b.x1, b.y1, b.x2, b.y2] if b else None,
                            overlay=f"/understand/{uid}/overlay.jpg", crops=crops,
                            timings={k: round(v, 2) for k, v in timings.items()})
        (d / "understanding.json").write_text(und.model_dump_json(indent=2), encoding="utf-8")
        return und

    def run_understood(self, und: Understanding, size: int = 1024) -> Material:
        """Generation step after `understand`: no second Spark or SAM call."""
        d = self.understand_dir / und.id
        timings = dict(und.timings)
        t = time.perf_counter()
        samples = [Image.open(d / f"crop_{k}.png").convert("RGB") for k in range(len(und.crops))]
        raw, source, note = self.albedo_with_fallback(und.plan, samples)
        timings["muse_image"] = time.perf_counter() - t
        extra = {"sam_box": und.sam_box, "crop_from": und.crop_from, "found_by": und.found_by,
                 "samples": samples, "understanding": und.id, **note}
        mask = d / "mask.png"
        if mask.exists():
            extra["mask"] = np.asarray(Image.open(mask)).astype(bool)
        return self.finish(und.plan, und.request, raw, source, extra, size, timings)

    def height_guide(self, albedo: np.ndarray) -> np.ndarray | None:
        """Muse Image paints the height map from the clean albedo; aligned with it, and far closer
        to a real displacement than luminance (r=0.71 vs 0.24 on Bricks113A)."""
        try:
            h = self.client.edit_image(pio.to_pil(albedo), HEIGHT_PROMPT)
        except RuntimeError:
            return None  # maps fall back to luminance
        g = luminance(pio.from_pil(h))
        g = pio.resize(g, albedo.shape[0])
        return seamless.periodic_component(g)  # match the albedo's wrap

    def run(self, request: str, photo: Image.Image | None = None, size: int = 1024) -> Material:
        if photo is not None:
            return self.run_understood(self.understand(request, photo), size)
        timings: dict[str, float] = {}
        t = time.perf_counter()
        plan = self.plan(request, None)
        timings["spark_plan"] = time.perf_counter() - t
        t = time.perf_counter()
        raw = self.albedo_from_text(plan)
        timings["muse_image"] = time.perf_counter() - t
        return self.finish(plan, request, raw, "text", {}, size, timings)

    def finish(self, plan: MaterialPlan, request: str, raw: Image.Image, source: str, extra: dict,
               size: int, timings: dict[str, float]) -> Material:
        """Muse albedo -> pbrforge clean-up -> Muse height -> maps, saved as a material."""
        mid = uuid.uuid4().hex[:10]
        out_dir = self.data_dir / mid
        out_dir.mkdir(parents=True, exist_ok=True)
        extra = dict(extra)
        raw.save(out_dir / "muse_raw.png")
        samples = extra.pop("samples", [])
        for k, im in enumerate(samples):
            im.save(out_dir / f"photo_sample_{k}.png")
        if "mask" in extra:
            Image.fromarray(extra.pop("mask")).save(out_dir / "sam_mask.png")

        t = time.perf_counter()
        albedo, scores = pbrforge.fix_albedo(pio.from_pil(raw))
        if samples and source == "photo":  # Muse repaints: bring the colours back to the real surface
            albedo, fidelity = color.match_to_samples(albedo, [pio.from_pil(s) for s in samples])
            albedo = delight.fit_pbr_range(albedo)
            scores["fidelity"] = fidelity
        pio.save(out_dir / "albedo_source.png", albedo)  # native resolution, for exports
        timings["pbrforge_albedo"] = time.perf_counter() - t

        t = time.perf_counter()
        guide = self.height_guide(albedo)
        timings["muse_height"] = time.perf_counter() - t
        if guide is not None:
            pio.save(out_dir / "muse_height.png", guide)

        t = time.perf_counter()
        params = pbrforge.MapParams(**plan.model_dump(include=set(pbrforge.MapParams.__dataclass_fields__)))
        maps = pbrforge.derive(albedo, params, size=size, height_guide=guide)
        timings["pbrforge_maps"] = time.perf_counter() - t

        urls = {}
        for name, arr in maps.items():
            pio.save(out_dir / f"{name}.png", arr)
            urls[name] = f"/materials/{mid}/maps/{name}.png"
        urls["muse_raw"] = f"/materials/{mid}/maps/muse_raw.png"
        if samples:
            urls["photo_sample"] = f"/materials/{mid}/maps/photo_sample_0.png"
        if guide is not None:
            urls["muse_height"] = f"/materials/{mid}/maps/muse_height.png"

        mat = Material(id=mid, plan=plan, request=request, source=source, size=size,
                       maps=urls, scores={**scores, **extra},
                       timings={k: round(v, 2) for k, v in timings.items()})
        (out_dir / "material.json").write_text(mat.model_dump_json(indent=2), encoding="utf-8")
        return mat


def export_material(mat: Material, size: int, fmt: str, data_dir: Path = DATA_DIR) -> Path:
    """Recompute the maps at `size` from the stored albedo and Muse height, write the
    ambientCG-style package and return its zip."""
    d = data_dir / mat.id
    src = d / "albedo_source.png"
    albedo = pio.load(src if src.exists() else d / "albedo.png")
    guide_path = d / "muse_height.png"
    guide = luminance(pio.load(guide_path)) if guide_path.exists() else None
    params = pbrforge.MapParams(**mat.plan.model_dump(include=set(pbrforge.MapParams.__dataclass_fields__)))
    maps = pbrforge.derive(albedo, params, size=size, height_guide=guide)
    preview = pio.to_pil(contact.render_sphere(maps, 512))
    folder = export.export_package(maps, mat.plan.name, d / "export", fmt, preview)
    return export.zip_package(folder)


def load_understanding(uid: str, root: Path = UNDERSTAND_DIR) -> Understanding | None:
    p = root / uid / "understanding.json"
    return Understanding.model_validate(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else None


def load_material(mid: str, data_dir: Path = DATA_DIR) -> Material | None:
    p = data_dir / mid / "material.json"
    if not p.exists():
        return None
    return Material.model_validate(json.loads(p.read_text(encoding="utf-8")))
