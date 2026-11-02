"""README captures: the MatterLift page and Live RT on a few materials, in the installed Chrome
(headed, so WebGPU and the GPU are the real ones). Needs the page (npm --prefix web run dev) and the
API serving those materials (uvicorn ... --port 8001).

    .venv/Scripts/python scripts/capture_readme.py [--url http://localhost:5173] [--ids df73c74e41 ...]
        [--out docs/img/candidates] [--live-seconds 25]

Per material: ui_<name>.png (the whole page, sphere), dragon_<name>.png (the preview), live_<name>.png
(Live RT path tracing on the dragon). For the first one, passes_<name>.png: beauty, depth, normal,
thickness side by side.
"""
from __future__ import annotations

import argparse
import io
import time
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
# Made from text only (no user photo in them): ruby, oak parquet, limestone, rusty steel, flagstone, glass
DEFAULT_IDS = ["df73c74e41", "208f494a3e", "fde23b2cda", "c20b159460", "8cb20dd890", "afecc4a4d6"]


def _settle(page: Page, seconds: float = 2.5) -> None:
    page.wait_for_load_state("networkidle")
    time.sleep(seconds)


def _click(page: Page, selector: str, seconds: float = 1.0) -> None:
    page.locator(selector).click()
    time.sleep(seconds)


def _canvas(page: Page) -> Image.Image:
    return Image.open(io.BytesIO(page.locator("#canvas-wrap").screenshot()))


def trim_bars(shot: Image.Image) -> Image.Image:
    """The 16:9 render inside a taller frame: drop the black bars above and below (the frame's
    1 px border and corners do not count)."""
    a = np.asarray(shot.convert("RGB"))[4:-4, 8:-8]
    rows = np.flatnonzero(a.mean(axis=(1, 2)) > 6)
    return shot.convert("RGB").crop((8, int(rows[0]) + 4, shot.width - 8, int(rows[-1]) + 5))


def capture(page: Page, url: str, mid: str, out: Path, live_seconds: float, passes: bool) -> list[Path]:
    page.goto(f"{url}/?id={mid}")
    _settle(page)
    files = []

    _click(page, '[data-shape="sphere"]')
    files.append(out / f"ui_{mid}.png")
    page.screenshot(path=files[-1])

    _click(page, '[data-shape="dragon"]', 4)  # the scan downloads the first time
    files.append(out / f"dragon_{mid}.png")
    _canvas(page).save(files[-1])

    if passes:
        shots = []
        for aov in ("beauty", "depth", "normal", "thickness"):
            if page.locator(f'[data-aov="{aov}"]').is_disabled():
                continue
            _click(page, f'[data-aov="{aov}"]')
            shots.append(_canvas(page))
        _click(page, '[data-aov="beauty"]')
        w, h = shots[0].size
        sheet = Image.new("RGB", (w * len(shots), h))
        for k, s in enumerate(shots):
            sheet.paste(s.convert("RGB"), (k * w, 0))
        files.append(out / f"passes_{mid}.png")
        sheet.save(files[-1])

    page.evaluate("""() => { window.__liveReady = false;
        addEventListener('message', (e) => { if (e.data?.type === 'live-rt:ready') window.__liveReady = true; }); }""")
    _click(page, "#live", 0)
    page.wait_for_function("window.__liveReady === true", timeout=120_000)
    time.sleep(live_seconds)  # let the path tracer converge
    # the renderer's own overlay (stats, light controls) off, as its H key does
    page.frame(url=lambda u: "live.html" in u).evaluate(
        "document.body.classList.add('hide-ui'); document.querySelector('#tip')?.remove()")
    time.sleep(0.5)
    files.append(out / f"live_{mid}.png")
    trim_bars(_canvas(page)).save(files[-1])
    _click(page, "#live")  # off again: frees the GPU before the next material
    print(mid, [f.name for f in files], flush=True)
    return files


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:5173")
    ap.add_argument("--ids", nargs="+", default=DEFAULT_IDS)
    ap.add_argument("--out", default=str(ROOT / "docs" / "img" / "candidates"))
    ap.add_argument("--live-seconds", type=float, default=25)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        # --lang: the file picker's label follows Chrome's language, not the page's
        browser = p.chromium.launch(channel="chrome", headless=False, args=["--enable-unsafe-webgpu", "--lang=en-US"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1, locale="en-US")
        page.add_init_script("localStorage.setItem('matterlift.tutorial.hidden', '1')")
        for k, mid in enumerate(args.ids):
            capture(page, args.url.rstrip("/"), mid, out, args.live_seconds, passes=k == 0)
        browser.close()


if __name__ == "__main__":
    main()
