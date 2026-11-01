from __future__ import annotations

from pydantic import BaseModel, Field


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
    sam_prompt: str = Field("", description="Short noun phrase for SAM to find the source surface")
    roughness: float = 0.7
    roughness_variation: float = 0.25
    metallic: float = 0.0
    metal_on_desaturated: bool = False
    height_strength: float = 1.0
    normal_strength: float = 1.0
    detail: float = 1.0
    shading: Shading = Shading()


class Material(BaseModel):
    id: str
    plan: MaterialPlan
    request: str
    source: str  # "photo" or "text"
    size: int
    maps: dict[str, str]  # name -> URL path
    scores: dict
    timings: dict[str, float]


class LibraryItemPlan(MaterialPlan):
    """One material of a room, as listed by Spark: its plan plus where it is in the photo."""
    points: list[tuple[float, float]] = Field(default_factory=list, description="[x, y] in 0..1000")


class LibraryItem(BaseModel):
    plan: LibraryItemPlan
    crops: list[str] = Field(default_factory=list)  # URLs: the photo samples for this material
    crop_from: str | None = None
    sam_box: list[int] | None = None
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
    matched: bool  # SAM found the surface Spark named
    crop_from: str | None = None  # "mask" or "box"
    sam_box: list[int] | None = None
    overlay: str  # URL: photo + mask + sampled square + label
    crops: list[str] = Field(default_factory=list)  # URLs: the samples Muse turns into a texture
    timings: dict[str, float]
