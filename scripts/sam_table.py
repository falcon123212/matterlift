"""Photo chain check: Spark names the surface, SAM 3.1 masks it, we crop inside the mask, Muse
turns the sample into a texture.

Usage: python scripts/sam_table.py [--photo path/to/table.jpg] [--request "take this wood"]
Without --photo, reuses (or generates) a stand-in photo: plumbing test only, not a quality test.
Writes samples/gate/sam_*.png.
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from matterlift_api.pipeline import Pipeline, _square_crop, largest_square_in_mask  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--photo", type=Path)
    ap.add_argument("--request", default="take the wood of this table")
    args = ap.parse_args()
    out = ROOT / "samples" / "gate"
    out.mkdir(parents=True, exist_ok=True)
    pipe = Pipeline()
    c = pipe.client

    stand_in = out / "sam_photo_generated.png"
    if args.photo:
        photo = Image.open(args.photo).convert("RGB")
    elif stand_in.exists():
        photo = Image.open(stand_in).convert("RGB")
    else:
        photo = c.generate_image(
            "Smartphone photo of a solid walnut wooden dining table in a bright living room, "
            "three-quarter view, natural window light, chairs around it, a bowl of fruit on it")
        photo.save(stand_in)

    t = time.perf_counter()
    plan = pipe.plan(args.request, photo)
    print(f"spark: name={plan.name!r} sam_prompt={plan.sam_prompt!r} ({time.perf_counter() - t:.1f}s)")

    t = time.perf_counter()
    segments = c.segment(photo, plan.sam_prompt or "table")
    print(f"sam: {len(segments)} masks ({time.perf_counter() - t:.1f}s)")
    if not segments:
        sys.exit("SAM found nothing")
    seg = segments[0]
    print(f"  largest: box {seg.box}, mask covers {seg.mask.mean() * 100:.1f}% of the photo")

    # Overlay: mask in orange, box-centre crop (old) in yellow, mask square (new) in green.
    vis = np.asarray(photo).astype(float)
    vis[seg.mask] = vis[seg.mask] * 0.5 + np.array([255, 120, 40]) * 0.5
    vis = Image.fromarray(vis.astype(np.uint8))
    d = ImageDraw.Draw(vis)
    old = _square_crop(photo, seg.box)  # just for its size
    b = seg.box
    cx, cy, s = (b.x1 + b.x2) // 2, (b.y1 + b.y2) // 2, old.width
    d.rectangle([cx - s // 2, cy - s // 2, cx + s // 2, cy + s // 2], outline=(255, 220, 0), width=6)
    square = largest_square_in_mask(seg.mask)
    if square:
        x, y, s = square
        d.rectangle([x, y, x + s, y + s], outline=(40, 230, 90), width=8)
        crop = photo.crop((x, y, x + s, y + s))
    else:
        crop = old
    vis.save(out / "sam_mask_overlay.png")
    crop.save(out / "sam_crop.png")

    t = time.perf_counter()
    albedo, source, extra = pipe.albedo(plan, photo)
    albedo.save(out / "sam_muse_albedo.png")
    print(f"muse from crop ({extra.get('crop_from')}): {albedo.size} ({time.perf_counter() - t:.1f}s)")

    strip = Image.new("RGB", (1536, 512), (20, 20, 22))
    for i, im in enumerate((vis, crop, albedo)):
        im = im.copy()
        im.thumbnail((512, 512))
        strip.paste(im, (i * 512, 0))
    strip.save(out / "sam_strip.png")
    print("strip:", out / "sam_strip.png")


if __name__ == "__main__":
    main()
