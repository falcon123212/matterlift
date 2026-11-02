"""The 15-second opening of the demo video, from opening_scenes.py's scenes and materials:

  0.0-6.3 s   nine places, 0.7 s each, a shutter flash on every cut, a slow push in, the place name
  6.3-10.3 s  the nine as a 3x3 mosaic; tile by tile, each flips to the material MatterLift made of it
  10.3-13.9 s the Stanford dragon path traced in Live RT, changing material on every beat as it turns
  13.9-15 s   the title

    .venv/Scripts/python scripts/opening_video.py capture     # Live RT frames of each material (local page)
    .venv/Scripts/python scripts/opening_video.py render      # -> <out>/opening_15s.mp4

`capture` needs the page (npm --prefix web run dev) and the API (uvicorn ... --port 8001) running locally.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from pbrforge import contact  # noqa: E402
from pbrforge import io as pio  # noqa: E402

W, H, FPS = 1920, 1080, 30
GOLD = (214, 170, 96)
BG = (11, 12, 16)
FONTS = Path("C:/Windows/Fonts")
PLACES = ["kyoto", "lagos", "norway", "lisbon", "utah", "mumbai", "mexico", "scotland", "seoul"]
LABEL = {"kyoto": "KYOTO", "lagos": "LAGOS", "norway": "ÅLESUND, NORWAY", "lisbon": "LISBON", "utah": "UTAH",
         "mumbai": "MUMBAI", "mexico": "MEXICO CITY", "scotland": "CAIRNGORMS, SCOTLAND", "seoul": "SEOUL"}
DRAGON_FRAMES = 12  # per material in the Live RT beat


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "segoeuib.ttf" if bold else "segoeui.ttf"
    return ImageFont.truetype(str(FONTS / name), size) if (FONTS / name).exists() else ImageFont.load_default(size)


def ease(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def cover(img: Image.Image, w: int, h: int, zoom: float = 1.0) -> Image.Image:
    """Fill w x h from img (centre crop), pushed in by `zoom`."""
    k = max(w / img.width, h / img.height) * zoom
    big = img.resize((max(w, round(img.width * k)), max(h, round(img.height * k))), Image.LANCZOS)
    x, y = (big.width - w) // 2, (big.height - h) // 2
    return big.crop((x, y, x + w, y + h))


# --- capture: Live RT frames of every material -------------------------------------------------

def capture(out: Path, site: str) -> None:
    from playwright.sync_api import sync_playwright
    from capture_readme import trim_bars
    from record_takes import CURSOR_JS  # noqa: F401  (not drawn: no cursor in this beat)

    mats = json.loads((out / "materials.json").read_text(encoding="utf-8"))
    frames_dir = out / "dragon"
    frames_dir.mkdir(exist_ok=True)
    step = 9  # pixels dragged per frame: a slow turn, continued from one material to the next
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=False,
                                    args=["--enable-unsafe-webgpu", "--lang=en-US"],
                                    ignore_default_args=["--enable-automation"])
        page = browser.new_page(viewport={"width": 2400, "height": 1350}, device_scale_factor=1)
        page.add_init_script("localStorage.setItem('matterlift.tutorial.hidden', '1')")
        for k, place in enumerate(PLACES):
            if (frames_dir / f"{place}_{DRAGON_FRAMES - 1:02d}.png").exists():
                continue
            page.goto(f"{site}/?id={mats[place]}")
            page.wait_for_function("document.querySelectorAll('#maps figure img').length > 0", timeout=90_000)
            page.evaluate("""() => { window.__ready = false;
                addEventListener('message', e => { if (e.data?.type === 'live-rt:ready') window.__ready = true; }); }""")
            page.locator('[data-shape="dragon"]').click()
            time.sleep(1.0)
            page.locator("#live").click()
            page.wait_for_function("window.__ready === true", timeout=120_000)
            page.locator("iframe.live-frame").element_handle().content_frame().evaluate(
                "document.body.classList.add('hide-ui'); document.querySelector('#tip')?.remove()")
            box = page.locator("#canvas-wrap").bounding_box()
            cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] * 0.3
            # turn to where the previous material's beat ended, then let the image settle
            for _ in range(k):
                page.mouse.move(cx, cy); page.mouse.down(); page.mouse.move(cx + step * DRAGON_FRAMES, cy, steps=6)
                page.mouse.up()
            time.sleep(4.0)
            for f in range(DRAGON_FRAMES):
                page.mouse.move(cx, cy); page.mouse.down(); page.mouse.move(cx + step, cy, steps=2); page.mouse.up()
                time.sleep(0.35)
                shot = trim_bars(Image.open(io.BytesIO(page.locator("#canvas-wrap").screenshot())))
                shot.save(frames_dir / f"{place}_{f:02d}.png")
            print("dragon", place, flush=True)
        browser.close()


# --- render ----------------------------------------------------------------------------------

def sphere_tile(mid: str, size: int) -> Image.Image:
    d = ROOT / "data" / "materials" / mid
    maps = {k: pio.load(d / f"{k}.png") for k in ("albedo", "normal", "height", "roughness", "ao", "metallic")
            if (d / f"{k}.png").exists()}
    for k in ("height", "roughness", "ao", "metallic"):  # single-channel maps, saved as grey PNGs
        if k in maps and maps[k].ndim == 3:
            maps[k] = maps[k][..., 0]
    return pio.to_pil(contact.render_sphere(maps, size)).convert("RGB")


def shutter(frame: Image.Image, i: int) -> Image.Image:
    """The cut: two frames of white fading out, as a camera flash."""
    a = {0: 0.85, 1: 0.45, 2: 0.15}.get(i, 0.0)
    return Image.blend(frame, Image.new("RGB", frame.size, (255, 255, 255)), a) if a else frame


def caption(frame: Image.Image, text: str, alpha: float, y: int = H - 96, size: int = 34) -> None:
    if alpha <= 0:
        return
    d = ImageDraw.Draw(frame, "RGBA")
    f = font(size, True)
    w = d.textlength(text, font=f)
    d.text(((W - w) / 2, y), text, font=f, fill=(255, 255, 255, int(255 * alpha)),
           stroke_width=3, stroke_fill=(0, 0, 0, int(160 * alpha)))


def render(out: Path) -> Path:
    mats = json.loads((out / "materials.json").read_text(encoding="utf-8"))
    scenes = {p: Image.open(next((out / "scenes").glob(f"*_{p}.png"))).convert("RGB") for p in PLACES}
    tiles = {p: sphere_tile(mats[p], 300) for p in PLACES}
    dragons = {p: [Image.open(out / "dragon" / f"{p}_{f:02d}.png").convert("RGB") for f in range(DRAGON_FRAMES)]
               for p in PLACES}
    label_font = font(30, True)
    frames: list[Image.Image] = []

    # A. nine places, 0.7 s each
    per = 21
    for k, place in enumerate(PLACES):
        for i in range(per):
            f = cover(scenes[place], W, H, 1.0 + 0.07 * i / per)
            f = shutter(f, i)
            d = ImageDraw.Draw(f, "RGBA")
            d.text((64, H - 92), LABEL[place], font=label_font, fill=(255, 255, 255, 235),
                   stroke_width=2, stroke_fill=(0, 0, 0, 140))
            d.rectangle((64, H - 50, 64 + 56, H - 46), fill=GOLD + (255,))
            frames.append(f)

    # B. the mosaic, then each tile flips to its material
    tw, th, gap = 544, 306, 12  # leaves a band at the bottom for the caption
    x0, y0 = (W - 3 * tw - 2 * gap) // 2, 36
    scene_tiles = {p: cover(scenes[p], tw, th) for p in PLACES}
    mat_tiles = {}
    for p in PLACES:
        t = Image.new("RGB", (tw, th), (18, 19, 24))
        s = tiles[p].resize((th - 30, th - 30), Image.LANCZOS)
        mask = Image.new("L", s.size, 0)
        ImageDraw.Draw(mask).ellipse((1, 1, s.width - 2, s.height - 2), fill=255)
        t.paste(s, ((tw - s.width) // 2, 15), mask.filter(ImageFilter.GaussianBlur(1)))
        mat_tiles[p] = t
    n_b = 120
    for i in range(n_b):
        f = Image.new("RGB", (W, H), BG)
        intro = ease(i / 8)  # the last scene shrinks into the grid
        for k, p in enumerate(PLACES):
            r, c = divmod(k, 3)
            x, y = x0 + c * (tw + gap), y0 + r * (th + gap)
            start = 16 + k * 5  # cascade
            u = (i - start) / 10  # 10 frames per flip
            if u <= 0:
                img = scene_tiles[p]
            elif u >= 1:
                img = mat_tiles[p]
            else:
                img = scene_tiles[p] if u < 0.5 else mat_tiles[p]
                sx = abs(math.cos(math.pi * u))
                w = max(1, round(tw * sx))
                img = img.resize((w, th), Image.LANCZOS)
                x += (tw - w) // 2
            if intro < 1:
                a = Image.new("RGB", img.size, BG)
                img = Image.blend(a, img, intro)
            f.paste(img, (x, y))
        caption(f, "Scenes painted by Muse Image.  Materials made by MatterLift.", ease((i - 70) / 12), H - 82, 36)
        frames.append(f)

    # C. the dragon, a new material on every beat
    for k, place in enumerate(PLACES):
        for j in range(DRAGON_FRAMES):
            f = cover(dragons[place][j], W, H, 1.04)
            if j < 2:  # a soft flash marks the beat
                f = Image.blend(f, Image.new("RGB", f.size, (255, 255, 255)), 0.08 if j == 0 else 0.03)
            caption(f, "Path traced live in the browser", 1.0, H - 92, 30)
            frames.append(f)

    # D. the title
    for i in range(36):
        f = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(f, "RGBA")
        a = ease(i / 10)
        tf = font(150, True)
        tw_ = d.textlength("MatterLift", font=tf)
        d.text(((W - tw_) / 2, H / 2 - 150), "MatterLift", font=tf, fill=(245, 242, 236, int(255 * a)))
        sub = "Point at anything. Say what you want. Get a game-ready material."
        sf = font(40)
        sw = d.textlength(sub, font=sf)
        d.text(((W - sw) / 2, H / 2 + 50), sub, font=sf, fill=GOLD + (int(255 * ease((i - 6) / 10)),))
        frames.append(f)

    path = out / "opening_15s.mp4"
    ff = subprocess.Popen([shutil.which("ffmpeg"), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "16",
                           "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)],
                          stdin=subprocess.PIPE)
    for f in frames:
        ff.stdin.write(np.asarray(f.convert("RGB"), np.uint8).tobytes())
    ff.stdin.close()
    ff.wait()
    print(path, len(frames), "frames", f"{len(frames) / FPS:.1f} s")
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["capture", "render"])
    ap.add_argument("--out", default="C:/matterlift-video/opening")
    ap.add_argument("--site", default="http://localhost:5173")
    args = ap.parse_args()
    out = Path(args.out)
    capture(out, args.site) if args.stage == "capture" else render(out)


if __name__ == "__main__":
    main()
