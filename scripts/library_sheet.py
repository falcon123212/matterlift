"""Contact sheet for a library: the photo with SAM's masks, then one lit sphere per material.

Usage: python scripts/library_sheet.py <library id> [--out samples/gate/library_sheet.png]
"""
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from matterlift_api.library import LIBRARY_DIR, load_library
from matterlift_api.overlay import PALETTE  # noqa: E402
from matterlift_api.pipeline import DATA_DIR  # noqa: E402
from pbrforge import contact, io  # noqa: E402
from pbrforge.metrics import luminance  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("library")
    ap.add_argument("--out", type=Path, default=ROOT / "samples" / "gate" / "library_sheet.png")
    args = ap.parse_args()
    lib = load_library(args.library)
    overlay = Image.open(LIBRARY_DIR / lib.id / "overlay.jpg")
    overlay.thumbnail((1200, 800))
    cell, cols = 290, 4
    rows = (len(lib.items) + cols - 1) // cols
    sheet = Image.new("RGB", (max(overlay.width, cols * cell), overlay.height + rows * (cell + 24) + 10), (20, 20, 22))
    sheet.paste(overlay, (0, 0))
    d = ImageDraw.Draw(sheet)
    for i, item in enumerate(lib.items):
        x, y = (i % cols) * cell, overlay.height + 10 + (i // cols) * (cell + 24)
        d.text((x + 8, y + 4), f"{i + 1} {item.plan.name}", fill=PALETTE[i % len(PALETTE)])
        if item.material is None:
            d.text((x + 8, y + 30), f"failed: {item.error}"[:40], fill=(230, 90, 90))
            continue
        m = DATA_DIR / item.material.id
        maps = {k: io.load(m / f"{k}.png") for k in ("albedo", "normal")}
        for k in ("ao", "roughness", "metallic"):
            maps[k] = luminance(io.load(m / f"{k}.png"))
        sheet.paste(io.to_pil(contact.render_sphere(maps, cell - 20, tiles=2)), (x + 10, y + 22))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.out)
    print(args.out)


if __name__ == "__main__":
    main()
