"""Find the surface Spark named in the photo, falling back step by step instead of failing.

1. SAM with Spark's noun phrase, then with its alternatives, then with the plan's name
   (one concept per request; Spark's points pick the right instance).
2. SAM with Spark's points as a point prompt (selects the object under them).
3. No mask at all: a square sample centred on Spark's points.
Only when Spark gave no points either is the material painted from its description alone.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image

from . import sampling
from .meta_client import MetaClient, Segment
from .sampling import Region
from .schemas import MaterialPlan

MIN_POINT_MASK = 0.004  # a point mask smaller than this share of the photo is a detail, not a surface


@dataclass
class Located:
    seg: Segment | None = None
    regions: list[Region] = field(default_factory=list)
    samples: list[Image.Image] = field(default_factory=list)
    how: str | None = None  # "mask", "box" or "points"
    found_by: str | None = None
    tried: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.samples)


def prompts_for(plan: MaterialPlan) -> list[str]:
    seen, out = set(), []
    for p in [plan.sam_prompt, *plan.sam_alternatives, plan.name.replace("_", " ")]:
        p = (p or "").strip()
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out[:4]


def pixel_points(plan: MaterialPlan, photo: Image.Image) -> list[tuple[int, int]]:
    return [(min(photo.width - 1, int(x * photo.width / 1000)), min(photo.height - 1, int(y * photo.height / 1000)))
            for x, y in plan.points]


def pick(segments: list[Segment], points: list[tuple[int, int]]) -> Segment | None:
    """The instance under Spark's points, else the largest."""
    for s in segments:
        if any(0 <= y < s.mask.shape[0] and 0 <= x < s.mask.shape[1] and s.mask[y, x] for x, y in points):
            return s
    return segments[0] if segments else None


def _from_segment(photo: Image.Image, seg: Segment, found_by: str, tried: list[str]) -> Located:
    regions = sampling.sample_regions(seg.mask)
    how = "mask"
    if not regions:
        regions, how = [sampling.box_fallback(seg.box, photo.size)], "box"
    return Located(seg, regions, [sampling.crop(photo, r) for r in regions], how, found_by, tried)


def around_points(photo: Image.Image, points: list[tuple[int, int]], frac: float = 0.18) -> Region:
    cx = sum(x for x, _ in points) / len(points)
    cy = sum(y for _, y in points) / len(points)
    side = int(min(photo.size) * frac)
    x = int(min(max(0, cx - side / 2), photo.width - side))
    y = int(min(max(0, cy - side / 2), photo.height - side))
    return x, y, side, side


def locate(client: MetaClient, photo: Image.Image, plan: MaterialPlan, frame: bool = True) -> Located:
    """frame=False skips Spark's noun phrases: SAM takes the object under the points directly."""
    pts = pixel_points(plan, photo)
    tried: list[str] = []
    for prompt in prompts_for(plan) if frame else []:
        tried.append(f'SAM "{prompt}"')
        try:
            seg = pick(client.segment(photo, prompt), pts)
        except RuntimeError:
            continue
        if seg is not None and seg.mask.any():
            return _from_segment(photo, seg, f'SAM "{prompt}"', tried)
    if pts:
        tried.append("SAM on Spark's points")
        try:
            seg = client.segment_points(photo, {1: pts}).get(1)
        except (RuntimeError, ValueError):
            seg = None
        if seg is not None and seg.mask.mean() >= MIN_POINT_MASK:
            return _from_segment(photo, seg, "SAM on Spark's points", tried)
        region = around_points(photo, pts)
        return Located(None, [region], [sampling.crop(photo, region)], "points", "Spark's points", tried)
    return Located(tried=tried)
