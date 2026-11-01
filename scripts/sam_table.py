"""Photo chain check: Spark names the surface, SAM 3.1 finds it, we crop, Muse turns it into a texture.

Usage: python scripts/sam_table.py [--photo path/to/table.jpg] [--request "take this wood"]
Without --photo, Muse Image generates a stand-in photo (plumbing test only, not a quality test).
Writes samples/gate/sam_*.png.
"""
import argparse
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from matterlift_api.pipeline import Pipeline, _square_crop  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--photo", type=Path)
    ap.add_argument("--request", default="take the wood of this table")
    args = ap.parse_args()
    out = ROOT / "samples" / "gate"
    out.mkdir(parents=True, exist_ok=True)
    pipe = Pipeline()
    c = pipe.client

    if args.photo:
        photo = Image.open(args.photo).convert("RGB")
    else:
        photo = c.generate_image(
            "Smartphone photo of a solid walnut wooden dining table in a bright living room, "
            "three-quarter view, natural window light, chairs around it")
        photo.save(out / "sam_photo_generated.png")

    t = time.perf_counter()
    plan = pipe.plan(args.request, photo)
    print(f"spark: name={plan.name!r} sam_prompt={plan.sam_prompt!r} ({time.perf_counter() - t:.1f}s)")

    t = time.perf_counter()
    boxes = c.segment_boxes(photo, plan.sam_prompt or "table")
    print(f"sam: {len(boxes)} boxes ({time.perf_counter() - t:.1f}s), largest {boxes[0] if boxes else None}")
    if not boxes:
        sys.exit("SAM found nothing")

    vis = photo.copy()
    d = ImageDraw.Draw(vis)
    for i, b in enumerate(boxes[:5]):
        d.rectangle([b.x1, b.y1, b.x2, b.y2], outline=(255, 80, 60) if i == 0 else (255, 220, 0), width=6)
    vis.save(out / "sam_boxes.png")
    crop = _square_crop(photo, boxes[0])
    crop.save(out / "sam_crop.png")

    t = time.perf_counter()
    albedo, source, extra = pipe.albedo(plan, photo)
    albedo.save(out / "sam_muse_albedo.png")
    print(f"muse from crop: {albedo.size} source={source} ({time.perf_counter() - t:.1f}s)")

    strip = Image.new("RGB", (1536, 512), (20, 20, 22))
    for i, im in enumerate((vis, crop, albedo)):
        im = im.copy()
        im.thumbnail((512, 512))
        strip.paste(im, (i * 512, 0))
    strip.save(out / "sam_strip.png")
    print("strip:", out / "sam_strip.png")


if __name__ == "__main__":
    main()
