"""photo + request -> Spark (plan + target) -> SAM 3.1 (box) -> crop -> Muse Image -> pbrforge -> maps."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from PIL import Image

import pbrforge
from pbrforge import io as pio

from .meta_client import Box, MetaClient
from .schemas import Material, MaterialPlan

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "materials"

TEXTURE_SUFFIX = (
    "Seamless tileable PBR albedo texture, orthographic top-down view, the material fills the "
    "whole frame edge to edge, flat even diffuse lighting, no shadows, no specular highlights, "
    "no perspective, no objects, no text, no single standout feature."
)

PLAN_SYSTEM = """You are the technical artist of MatterLift. You turn a user's request (and an \
optional photo) into a plan for a game-ready PBR material. Answer with ONE JSON object only:
{
 "name": short snake_case name,
 "texture_prompt": what the albedo should show, material only, as a painter would describe the \
surface seen straight on (colour, pattern, wear, scale); never mention lighting or 3D objects,
 "sam_prompt": if a photo is given, a 1-3 word noun phrase naming the surface to sample in it, \
else "",
 "roughness": 0..1, "roughness_variation": 0..0.5, "metallic": 0..1,
 "metal_on_desaturated": true only for rusty or painted metal where grey areas are bare metal,
 "height_strength": 0.3..1.5, "normal_strength": 1..8 (stone 4, wood 2, fabric 1.5, metal 2),
 "detail": 0.5..2 (fine surface grain),
 "shading": {"transmission": 0..1, "ior": 1..2.4, "clearcoat": 0..1, "clearcoat_roughness": 0..1,
             "sheen": 0..1, "subsurface": 0..1, "anisotropy": 0..1}
}
Values must be physically plausible for the material."""


def _square_crop(img: Image.Image, box: Box, margin: float = 0.08) -> Image.Image:
    """Largest square inside the box, shrunk by a margin to stay off the object's edges."""
    w, h = box.x2 - box.x1, box.y2 - box.y1
    side = int(min(w, h) * (1 - 2 * margin))
    cx, cy = (box.x1 + box.x2) // 2, (box.y1 + box.y2) // 2
    return img.crop((cx - side // 2, cy - side // 2, cx + side // 2, cy + side // 2))


class Pipeline:
    def __init__(self, client: MetaClient | None = None, data_dir: Path = DATA_DIR):
        self.client = client or MetaClient()
        self.data_dir = data_dir

    def plan(self, request: str, photo: Image.Image | None) -> MaterialPlan:
        user = f"Request: {request}"
        if photo is not None:
            user += "\nThe photo shows the real surface to sample."
        raw = self.client.chat_json(PLAN_SYSTEM, user, [photo] if photo is not None else None)
        return MaterialPlan.model_validate(raw)

    def albedo(self, plan: MaterialPlan, photo: Image.Image | None) -> tuple[Image.Image, str, dict]:
        prompt = f"{plan.texture_prompt}. {TEXTURE_SUFFIX}"
        if photo is None:
            return self.client.generate_image(prompt), "text", {}
        boxes = self.client.segment_boxes(photo, plan.sam_prompt or plan.name.replace("_", " "))
        if not boxes:
            return self.client.generate_image(prompt), "text", {"sam": "no match, fell back to text"}
        crop = _square_crop(photo, boxes[0])
        edited = self.client.edit_image(
            crop, f"Turn this photo sample into a {prompt[0].lower()}{prompt[1:]}"
        )
        b = boxes[0]
        return edited, "photo", {"sam_box": [b.x1, b.y1, b.x2, b.y2], "crop": crop}

    def run(self, request: str, photo: Image.Image | None = None, size: int = 1024) -> Material:
        mid = uuid.uuid4().hex[:10]
        out_dir = self.data_dir / mid
        out_dir.mkdir(parents=True, exist_ok=True)
        timings: dict[str, float] = {}

        t = time.perf_counter()
        plan = self.plan(request, photo)
        timings["spark_plan"] = time.perf_counter() - t

        t = time.perf_counter()
        raw, source, extra = self.albedo(plan, photo)
        timings["muse_image"] = time.perf_counter() - t
        raw.save(out_dir / "muse_raw.png")
        if "crop" in extra:
            extra.pop("crop").save(out_dir / "photo_crop.png")

        t = time.perf_counter()
        albedo, scores = pbrforge.fix_albedo(pio.from_pil(raw))
        params = pbrforge.MapParams(**plan.model_dump(include=set(pbrforge.MapParams.__dataclass_fields__)))
        maps = pbrforge.derive(albedo, params, size=size)
        timings["pbrforge"] = time.perf_counter() - t

        urls = {}
        for name, arr in maps.items():
            pio.save(out_dir / f"{name}.png", arr)
            urls[name] = f"/materials/{mid}/maps/{name}.png"
        urls["muse_raw"] = f"/materials/{mid}/maps/muse_raw.png"

        mat = Material(id=mid, plan=plan, request=request, source=source, size=size,
                       maps=urls, scores={**scores, **extra},
                       timings={k: round(v, 2) for k, v in timings.items()})
        (out_dir / "material.json").write_text(mat.model_dump_json(indent=2), encoding="utf-8")
        return mat


def load_material(mid: str, data_dir: Path = DATA_DIR) -> Material | None:
    p = data_dir / mid / "material.json"
    if not p.exists():
        return None
    return Material.model_validate(json.loads(p.read_text(encoding="utf-8")))
