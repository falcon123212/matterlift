"""An orbit around a material in Live RT, as an animated GIF for the README: the camera is dragged a
few pixels between frames, the path tracer refines for a moment, the frame is kept.

    .venv/Scripts/python scripts/capture_orbit.py [--url http://localhost:5173] [--id df73c74e41]
        [--frames 40] [--step 22] [--settle 0.6] [--width 720] [--out docs/img/orbit_ruby.gif]
"""
from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_readme import trim_bars  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:5173")
    ap.add_argument("--id", default="df73c74e41")
    ap.add_argument("--frames", type=int, default=40)
    ap.add_argument("--step", type=int, default=22, help="pixels dragged between frames")
    ap.add_argument("--settle", type=float, default=0.6, help="seconds of refinement per frame")
    ap.add_argument("--width", type=int, default=720)
    ap.add_argument("--out", default="docs/img/orbit_ruby.gif")
    args = ap.parse_args()

    frames = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=False, args=["--enable-unsafe-webgpu", "--lang=en-US"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
        page.add_init_script("localStorage.setItem('matterlift.tutorial.hidden', '1')")
        page.goto(f"{args.url}/?id={args.id}")
        page.wait_for_load_state("networkidle")
        page.evaluate("""() => { window.__liveReady = false;
            addEventListener('message', (e) => { if (e.data?.type === 'live-rt:ready') window.__liveReady = true; }); }""")
        page.locator("#live").click()
        page.wait_for_function("window.__liveReady === true", timeout=120_000)
        time.sleep(8)  # first frames converge
        page.locator("iframe.live-frame").element_handle().content_frame().evaluate(
            "document.body.classList.add('hide-ui'); document.querySelector('#tip')?.remove()")
        box = page.locator("#canvas-wrap").bounding_box()
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] * 0.35  # above the model
        for _ in range(args.frames):
            page.mouse.move(cx, cy)
            page.mouse.down()
            page.mouse.move(cx + args.step, cy, steps=4)
            page.mouse.up()
            time.sleep(args.settle)
            shot = trim_bars(Image.open(io.BytesIO(page.locator("#canvas-wrap").screenshot())))
            frames.append(shot.resize((args.width, round(shot.height * args.width / shot.width)), Image.LANCZOS))
        browser.close()

    # the camera's inertia makes the turn uneven: close the loop on the frame most like the first,
    # once past half the frames, so the GIF does not jump when it starts over
    first = np.asarray(frames[0], np.float32)
    errs = [float(((np.asarray(f, np.float32) - first) ** 2).mean()) for f in frames]
    end = len(frames) // 2 + int(np.argmin(errs[len(frames) // 2:]))
    frames = frames[:end]
    print("loop closed at frame", end, "of", len(errs), "error", round(errs[end]))
    pal = [f.convert("P", palette=Image.ADAPTIVE, colors=192) for f in frames]
    out = Path(args.out)
    pal[0].save(out, save_all=True, append_images=pal[1:], duration=90, loop=0, optimize=True)
    print(out, len(frames), "frames", out.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
