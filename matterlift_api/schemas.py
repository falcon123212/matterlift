from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from pbrforge.detail import KINDS as DETAIL_KINDS
from pbrforge.detail import infer_kind


class Shading(BaseModel):
    """Proposed by Spark, adjustable in the UI. Maps to glTF KHR_materials_* extensions."""
    transmission: float = 0.0
    ior: float = 1.5
    clearcoat: float = 0.0
    clearcoat_roughness: float = 0.1
    sheen: float = 0.0
    subsurface: float = 0.0
    anisotropy: float = 0.0


class MaterialPlan(BaseModel):
    name: str = "material"
    texture_prompt: str = Field("", description="What Muse Image should paint, material only")
    subject: str = Field("", description="With a photo: the object or surface whose material is taken")
    subject_reason: str = Field("", description="Why that one: what the request or the framing points at")
    sam_prompt: str = Field("", description="Short noun phrase for SAM to find the source surface")
    sam_alternatives: list[str] = Field(default_factory=list, description="Other names SAM may know it by")
    points: list[tuple[float, float]] = Field(default_factory=list, description="[x, y] in 0..1000 on the surface")
    roughness: float = 0.7
    roughness_variation: float = 0.25
    metallic: float = 0.0
    metal_on_desaturated: bool = False
    height_strength: float = 1.0
    normal_strength: float = 1.0
    detail: float = 1.0
    detail_kind: str = ""  # procedural detail layer: wood, stone, fabric, metal, plaster or none
    detail_strength: float = 0.5
    wear: float = 0.0
    # real-world width one tile of the texture covers, in cm (0 = unknown, as on materials made before it)
    tile_size_cm: float = 0.0
    shading: Shading = Shading()

    @classmethod
    def lenient(cls, raw: Any) -> "MaterialPlan":
        """Spark's plan, keeping every field that validates: a wrong type or a missing field falls
        back to its default instead of rejecting the whole plan; numbers are clamped to range."""
        data = dict(raw) if isinstance(raw, dict) else {}
        for _ in range(len(data) + 1):
            try:
                plan = cls.model_validate(data)
                break
            except ValidationError as e:
                bad = {err["loc"][0] for err in e.errors() if err["loc"]}
                if not bad & data.keys():
                    plan = cls()
                    break
                for key in bad:
                    data.pop(key, None)
        else:
            plan = cls()
        clamp = {"roughness": (0.02, 1), "roughness_variation": (0, 0.5), "metallic": (0, 1),
                 "height_strength": (0.1, 2), "normal_strength": (0.1, 3), "detail": (0.25, 3),
                 "detail_strength": (0, 1), "wear": (0, 1), "tile_size_cm": (0, 1000)}
        fixed = {k: min(hi, max(lo, getattr(plan, k))) for k, (lo, hi) in clamp.items()}
        fixed["points"] = [(min(1000, max(0, x)), min(1000, max(0, y))) for x, y in plan.points][:3]
        fixed["name"] = plan.name.strip().replace(" ", "_")[:48] or "material"
        kind = plan.detail_kind.strip().lower()
        fixed["detail_kind"] = kind if kind in DETAIL_KINDS else infer_kind(fixed["name"], plan.texture_prompt)
        return plan.model_copy(update=fixed)


class Material(BaseModel):
    id: str
    plan: MaterialPlan
    request: str
    source: str  # "photo" or "text"
    size: int
    maps: dict[str, str]  # name -> URL path
    scores: dict
    timings: dict[str, float]


LibraryItemPlan = MaterialPlan  # a room's material: same plan, its points place it in the photo


class LibraryItem(BaseModel):
    plan: LibraryItemPlan
    crops: list[str] = Field(default_factory=list)  # URLs: the photo samples for this material
    crop_from: str | None = None
    found_by: str | None = None
    sam_box: list[int] | None = None
    key: int | None = None  # names its files (crop_{key}_k.png, mask_{key}.png); index in older libraries
    regions: list[list[int]] = Field(default_factory=list)  # sampled squares [x, y, w, h], for the overlay
    manual: bool = False  # placed by the user's points rather than listed by Spark
    material: Material | None = None
    error: str | None = None


class Library(BaseModel):
    id: str
    request: str
    photo: str  # URL path
    overlay: str  # URL path: the photo with every material's mask and sample
    items: list[LibraryItem]
    status: str = "understood"  # then "built"
    timings: dict[str, float]


class Understanding(BaseModel):
    """What the tool understood from a photo, shown before generation."""
    id: str
    request: str
    plan: MaterialPlan
    matched: bool  # we have photo samples (by SAM's mask, or around Spark's points)
    crop_from: str | None = None  # "mask", "box" or "points"
    found_by: str | None = None  # which prompt located the surface, e.g. 'SAM "rush seat"'

    sam_box: list[int] | None = None
    overlay: str  # URL: photo + mask + sampled square + label
    crops: list[str] = Field(default_factory=list)  # URLs: the samples Muse turns into a texture
    timings: dict[str, float]


class Critique(BaseModel):
    """Spark's review of a material, the fixes it made, and its verdict on the result."""
    before: str  # material ids
    after: str
    chosen: str  # the better-scored of the two
    score_before: int
    score_after: int
    issues: list[str]
    remaining: list[str] = Field(default_factory=list)
    params_changed: dict[str, list[float]]  # name -> [old, new]
    albedo_fix: str
    colour_matched: bool = False
    review_before: str  # URLs of the review sheets Spark looked at
    review_after: str | None
    seconds: float
