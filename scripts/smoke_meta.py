"""Check that every Meta model MatterLift uses answers. Usage: python scripts/smoke_meta.py"""
import sys
import time
from pathlib import Path

from matterlift_api import meta_client as mc  # noqa: E402

c = mc.MetaClient()
print("models:", ", ".join(c.models()))

t = time.time()
img = c.generate_image("seamless tileable texture, top-down photo of oak planks, flat even lighting")
print(f"muse-image: {img.size} in {time.time() - t:.1f}s")

t = time.time()
plan = c.chat_json("Answer with a JSON object only.",
                   'Describe this material as {"name": str, "roughness": 0..1, "metallic": 0..1}.',
                   images=[img])
print(f"spark (vision+json): {plan} in {time.time() - t:.1f}s")

t = time.time()
boxes = c.segment_boxes(img, "plank")
print(f"sam-3.1: {len(boxes)} boxes, largest {boxes[0] if boxes else None} in {time.time() - t:.1f}s")
