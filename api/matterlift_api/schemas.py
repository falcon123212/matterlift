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
    normal_strength: float = 4.0
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
