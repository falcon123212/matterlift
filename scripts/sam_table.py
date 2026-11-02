"""Photo chain check: understand (Spark plan, SAM mask, sample) then generate the albedo.

Usage: python scripts/sam_table.py [--photo path/to/table.jpg] [--request "take this wood"]
Without --photo, reuses (or generates) a stand-in photo: plumbing test only, not a quality test.
Writes samples/gate/sam_*.png.
"""
import argparse
import shutil
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from matterlift_api.pipeline import UNDERSTAND_DIR, Pipeline  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--photo", type=Path)
    ap.add_argument("--request", default="take the wood of this table")
    args = ap.parse_args()
    out = ROOT / "samples" / "gate"
    out.mkdir(parents=True, exist_ok=True)
    pipe = Pipeline()

    stand_in = out / "sam_photo_generated.png"
    if args.photo:
        photo = Image.open(args.photo).convert("RGB")
    elif stand_in.exists():
        photo = Image.open(stand_in).convert("RGB")
    else:
        photo = pipe.client.generate_image(
            "Smartphone photo of a solid walnut wooden dining table in a bright living room, "
            "three-quarter view, natural window light, chairs around it, a bowl of fruit on it")
        photo.save(stand_in)

    t = time.perf_counter()
    und = pipe.understand(args.request, photo)
    print(f"understood in {time.perf_counter() - t:.1f}s: {und.plan.name!r}, SAM '{und.plan.sam_prompt}' "
          f"matched={und.matched} samples={len(und.crops)} from {und.crop_from}")
    shutil.copy(UNDERSTAND_DIR / und.id / "overlay.jpg", out / "sam_understanding.jpg")

    t = time.perf_counter()
    samples = [Image.open(UNDERSTAND_DIR / und.id / f"crop_{k}.png") for k in range(len(und.crops))]
    albedo = pipe.albedo_from_samples(und.plan, samples)
    albedo.save(out / "sam_muse_albedo.png")
    print(f"muse from crop: {albedo.size} ({time.perf_counter() - t:.1f}s)")


if __name__ == "__main__":
    main()
