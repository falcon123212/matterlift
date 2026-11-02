"""The opening of the demo video: nine places around the world painted by Muse Image, and the
material MatterLift takes from each (Spark + SAM on the scene, Muse paints, pbrforge cleans).
Resumable: a scene or a material already made is kept.

    .venv/Scripts/python scripts/opening_scenes.py [--out C:\\matterlift-video\\opening]

Writes <out>/scenes/<n>_<place>.png and <out>/materials.json (place -> material id, saved in data/).
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from matterlift_api.pipeline import Pipeline  # noqa: E402

PHOTO = "Photograph, natural light, shallow depth of field, photorealistic, no people, no text."
# place: (what Muse paints, what MatterLift is asked to take from it)
SCENES = {
    "kyoto": ("Rain-soaked dark cedar veranda of a Kyoto temple, wet weathered wooden planks with puddles "
              "reflecting paper lanterns, overcast", "the wet weathered wooden planks"),
    "lagos": ("Stacks of hand-dyed indigo adire fabric at a market stall in Lagos, bold patterns, warm "
              "afternoon light", "the indigo dyed fabric"),
    "norway": ("Red hull of an old fishing boat in a Norwegian harbour, peeling paint and rust streaks, cold "
               "blue light", "the rusty painted steel hull"),
    "lisbon": ("Blue and white azulejo tiles on a Lisbon facade, slightly worn and chipped, golden hour",
               "the blue azulejo tiles"),
    "utah": ("Layered red sandstone cliff in the Utah desert, wind-carved strata, warm late sun",
             "the layered red sandstone"),
    "mumbai": ("Hammered brass pots stacked in a Mumbai bazaar, warm reflections and patina",
               "the hammered brass"),
    "mexico": ("Weathered pink lime stucco wall in Mexico City, fine cracks and sun-faded paint, bright sun",
               "the pink stucco wall"),
    "scotland": ("Mossy bark of an old Scots pine in a misty Scottish forest, deep furrows",
                 "the pine bark"),
    "seoul": ("Wet asphalt street at night in Seoul reflecting neon signs, close view of the road surface",
              "the wet asphalt"),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="C:/matterlift-video/opening")
    ap.add_argument("--size", type=int, default=1024)
    args = ap.parse_args()
    out = Path(args.out)
    (out / "scenes").mkdir(parents=True, exist_ok=True)
    pipe = Pipeline()

    def scene(item):
        k, (place, (prompt, _)) = item
        path = out / "scenes" / f"{k + 1}_{place}.png"
        if not path.exists():
            pipe.client.generate_image(f"{prompt}. {PHOTO}").convert("RGB").save(path)
            print("scene", path.name, flush=True)
        return place, path

    with ThreadPoolExecutor(3) as ex:
        paths = dict(ex.map(scene, enumerate(SCENES.items())))

    index = out / "materials.json"
    mats = json.loads(index.read_text(encoding="utf-8")) if index.exists() else {}

    def material(place):
        if place in mats:
            return place, mats[place]
        from PIL import Image
        und = pipe.understand(SCENES[place][1], Image.open(paths[place]))
        mat = pipe.run_understood(und, args.size)
        print("material", place, mat.id, mat.plan.name, "| SAM:", und.found_by, flush=True)
        return place, mat.id

    with ThreadPoolExecutor(3) as ex:
        for place, mid in ex.map(material, SCENES):
            mats[place] = mid
            index.write_text(json.dumps(mats, indent=2), encoding="utf-8")
    print(json.dumps(mats, indent=2))


if __name__ == "__main__":
    main()
