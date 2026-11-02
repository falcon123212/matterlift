"""Scripted screen takes of the MatterLift page for the demo video (docs/video/CAPTURE-RUNBOOK.md).

The installed Chrome shows the page; a drawn cursor glides to each control, pauses, then clicks for
real, so every take is steady and can be redone identically. Two recorders:
  obs    OBS records its `APP_AUTO` scene (window capture of this Chrome window, "Capture Cursor" OFF:
         the drawn cursor is the one on screen). Needs OBS's WebSocket server and OBS_PW in the env.
  video  Playwright records each take itself (a test take, no OBS needed).

    .venv/Scripts/python scripts/record_takes.py pregen                 # the shoot materials -> ids.json
    .venv/Scripts/python scripts/record_takes.py takes c06 c09b         # some takes
    .venv/Scripts/python scripts/record_takes.py takes all --recorder obs
    options: --site https://matterlift.vercel.app  --dir C:\\matterlift-video
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx
from PIL import Image, ImageOps
from playwright.sync_api import BrowserContext, Page, sync_playwright

SITE = "https://matterlift.vercel.app"
DIR = Path("C:/matterlift-video")
W, H = 1920, 1080

# What `pregen` makes (runbook §2): name -> text, or photo file in <dir>/photos with no text
TEXTS = {
    "oak": "very worn, scratched old oak parquet",
    "ruby": "a ruby",
    "diamond": "a diamond",
    "steel": "rusty painted steel plate, orange rust patches with bare grey metal and flaking blue paint",
    "moss": "mossy flagstone path, irregular grey stones with green moss in the joints",
    "limestone": "aged limestone blocks, weathered, fine cracks and mortar joints",
}
PHOTOS = {"cube": "cube.jpg", "plush": "plush.jpg"}

# The drawn cursor: an arrow above everything, never in the way of a click; a ring on each click.
CURSOR_JS = """
(() => {
  if (window.__cur || window !== window.top) return;  // the page only, not the Live RT frame
  const make = () => {
    const c = document.createElement('div');
    c.id = 'ml-cursor';
    c.innerHTML = '<svg width="26" height="34" viewBox="0 0 26 34"><path d="M2 2 L2 27 L8.5 21 L13 31 L17.5 29 L13 19.5 L22 19.5 Z" fill="white" stroke="black" stroke-width="2" stroke-linejoin="round"/></svg>';
    Object.assign(c.style, {position: 'fixed', left: '0', top: '0', zIndex: 2147483647, pointerEvents: 'none',
                            transform: 'translate(960px, 540px)', filter: 'drop-shadow(0 2px 3px rgba(0,0,0,.45))'});
    document.documentElement.appendChild(c);
    window.__cur = c;
  };
  if (document.body) make(); else addEventListener('DOMContentLoaded', make);
  window.__curAt = (x, y) => { if (window.__cur) window.__cur.style.transform = `translate(${x - 2}px, ${y - 2}px)`; };
  window.__curRing = (x, y) => {
    const r = document.createElement('div');
    Object.assign(r.style, {position: 'fixed', left: `${x - 18}px`, top: `${y - 18}px`, width: '36px', height: '36px',
      borderRadius: '50%', border: '3px solid rgba(214,170,96,.95)', zIndex: 2147483646, pointerEvents: 'none',
      transition: 'transform .45s ease-out, opacity .45s ease-out'});
    document.documentElement.appendChild(r);
    requestAnimationFrame(() => { r.style.transform = 'scale(1.8)'; r.style.opacity = '0'; });
    setTimeout(() => r.remove(), 600);
  };
  window.__liveReady = false;
  addEventListener('message', (e) => { if (e.data?.type === 'live-rt:ready') window.__liveReady = true; });
})();
"""


class Hand:
    """The drawn cursor, moved like a hand: eased travel, a pause, then a real click or drag."""

    def __init__(self, page: Page):
        self.page = page
        self.x, self.y = W / 2, H / 2

    def _step(self, x: float, y: float) -> None:
        self.page.mouse.move(x, y)
        self.page.evaluate("([x, y]) => window.__curAt(x, y)", [x, y])

    def move(self, x: float, y: float, secs: float = 0.55) -> None:
        x0, y0 = self.x, self.y
        n = max(1, int(secs * 50))
        for i in range(1, n + 1):
            t = i / n
            e = t * t * (3 - 2 * t)  # ease in and out
            self._step(x0 + (x - x0) * e, y0 + (y - y0) * e)
            time.sleep(secs / n)
        self.x, self.y = x, y

    def to(self, selector: str, secs: float = 0.55) -> None:
        loc = self.page.locator(selector).first
        loc.scroll_into_view_if_needed()
        b = loc.bounding_box()
        self.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, secs)

    def click(self, selector: str, pause: float = 0.4) -> None:
        self.to(selector)
        time.sleep(pause)
        self.page.evaluate("([x, y]) => window.__curRing(x, y)", [self.x, self.y])
        self.page.mouse.click(self.x, self.y)
        time.sleep(0.35)

    def drag(self, dx: float, dy: float = 0, secs: float = 2.0) -> None:
        """Press where the cursor is and pull, at an even pace (turns the view)."""
        self.page.mouse.down()
        x0, y0 = self.x, self.y
        n = max(1, int(secs * 50))
        for i in range(1, n + 1):
            self._step(x0 + dx * i / n, y0 + dy * math.sin(math.pi * i / n))
            time.sleep(secs / n)
        self.page.mouse.up()
        self.x, self.y = x0 + dx, y0

    def scroll_panel(self, selector: str, secs: float = 1.2, offset: int = 8) -> None:
        """Glide the right-hand panel until `selector` is at its top."""
        start, end = self.page.evaluate(
            """([sel, off]) => { const p = document.querySelector('.side'), el = document.querySelector(sel);
                 return [p.scrollTop, Math.max(0, p.scrollTop + el.getBoundingClientRect().top - p.getBoundingClientRect().top - off)]; }""",
            [selector, offset])
        n = max(1, int(secs * 50))
        for i in range(1, n + 1):
            t = i / n
            self.page.evaluate("y => { document.querySelector('.side').scrollTop = y; }",
                               start + (end - start) * t * t * (3 - 2 * t))
            time.sleep(secs / n)


# --- page helpers ---------------------------------------------------------------------------

def open_material(page: Page, site: str, mid: str) -> None:
    page.goto(f"{site}/?id={mid}")
    # the material is drawn once its maps are in (a fresh server instance pulls it from storage first)
    page.wait_for_function("""() => { const imgs = [...document.querySelectorAll('#maps figure img')];
        return imgs.length > 0 && imgs.every(i => i.complete && i.naturalWidth > 0)
               && (document.querySelector('#status')?.textContent || '').length > 0; }""", timeout=90_000)
    page.evaluate("document.querySelector('.side').scrollTop = 0")
    time.sleep(2.0)


def live_on(hand: Hand, settle: float = 3.0) -> None:
    hand.page.evaluate("window.__liveReady = false")
    hand.click("#live")
    hand.page.wait_for_function("window.__liveReady === true", timeout=120_000)
    hand.page.locator("iframe.live-frame").element_handle().content_frame().evaluate(
        "document.body.classList.add('hide-ui'); document.querySelector('#tip')?.remove()")
    time.sleep(settle)  # the path tracer converges


def canvas_point(page: Page, fy: float = 0.42) -> tuple[float, float]:
    b = page.locator("#canvas-wrap").bounding_box()
    return b["x"] + b["width"] * 0.5, b["y"] + b["height"] * fy


# --- the takes (runbook §3) -----------------------------------------------------------------

def c02(hand: Hand, ids: dict) -> None:
    hand.click('[data-light="raking"]')
    hand.move(*canvas_point(hand.page))
    hand.drag(260, 30, 2.2)
    hand.click('[data-shape="dragon"]')
    time.sleep(1.5)
    live_on(hand, 3.0)
    time.sleep(4.0)
    hand.click("#live")
    time.sleep(0.8)
    with hand.page.expect_download(timeout=180_000):
        hand.click("#export-link")


def c03(hand: Hand, ids: dict) -> None:
    hand.move(1500, 420)
    hand.scroll_panel("#tiling", 1.6, 40)
    time.sleep(2.0)
    hand.scroll_panel("#maps", 1.2, 40)
    time.sleep(0.6)
    for cap in ("albedo", "height"):
        hand.to(f'#maps figure:has(figcaption:text-is("{cap}")) img', 0.6)
        time.sleep(1.0)
    hand.scroll_panel("#fidelity", 1.6)
    time.sleep(2.0)


def c04(hand: Hand, ids: dict) -> None:
    hand.move(1500, 400)
    for sel in ("#critique-box", "#crit-before", "#crit-issues", "#crit-after-fig"):
        hand.scroll_panel(sel, 1.0)
        time.sleep(2.0)


def c05(hand: Hand, ids: dict) -> None:
    hand.click('[data-light="hdri"]')
    hand.move(*canvas_point(hand.page))
    hand.drag(320, 20, 3.0)
    hand.click('[data-shape="dragon"]')
    time.sleep(2.5)
    hand.move(*canvas_point(hand.page))
    hand.drag(240, 0, 2.0)


def c06(hand: Hand, ids: dict) -> None:
    hand.click('[data-shape="dragon"]')
    time.sleep(1.2)
    live_on(hand, 4.0)
    time.sleep(1.0)
    hand.move(*canvas_point(hand.page, 0.3))
    hand.drag(220, 0, 3.0)
    time.sleep(1.5)
    hand.click("#live")


def c09(hand: Hand, ids: dict) -> None:
    for aov in ("depth", "normal", "albedo", "roughness", "ao", "beauty"):
        hand.click(f'[data-aov="{aov}"]', 0.25)
        time.sleep(0.65)
    for shape in ("dragon", "buddha", "lucy"):
        hand.click(f'[data-shape="{shape}"]', 0.25)
        time.sleep(1.3)


def c09b(hand: Hand, ids: dict) -> None:
    hand.click('[data-shape="dragon"]')
    time.sleep(1.2)
    hand.click('[data-aov="thickness"]')
    time.sleep(2.0)
    hand.click('[data-aov="beauty"]')


def gallery(shape: str):
    def take(hand: Hand, ids: dict) -> None:
        hand.click(f'[data-shape="{shape}"]')
        time.sleep(1.2)
        live_on(hand, 4.0)
        hand.move(*canvas_point(hand.page, 0.3))
        hand.drag(300, 0, 5.0)
    return take


def desk(hand: Hand, ids: dict) -> None:
    hand.click('[data-shape="dragon"]')
    time.sleep(1.2)
    live_on(hand, 3.0)
    time.sleep(2.0)


# --- generation takes: they start from an empty page ----------------------------------------

def blank(critique: bool, size: str):
    """Start state (set before the recording starts): empty page, self-critique on or off, a size."""
    def prep(page: Page, site: str) -> None:
        page.goto(site)
        page.wait_for_selector("#request")
        page.evaluate("""([crit, size]) => { document.querySelector('#self-critique').checked = crit;
            document.querySelector('select[name="size"]').value = size; }""", [critique, size])
        time.sleep(1.5)
    return prep


def _done(page: Page, critique: bool, timeout: int = 280_000) -> None:
    """Until the material is on screen (and Spark's verdict, when self-critique is on)."""
    page.wait_for_function(r"""() => { const b = document.querySelector('#request button[type="submit"]');
        const st = document.querySelector('#status')?.textContent || '';
        return b && !b.disabled && st && !/ \d+ s$/.test(st); }""", timeout=timeout)
    if critique:
        page.wait_for_function(r"""() => /Spark: \d+\/10|Failed/.test(document.querySelector('#status')?.textContent || '')""",
                               timeout=timeout)


def _choose_photo(hand: Hand, path: Path) -> None:
    """Click Choose File; the file picker is answered by the script (no system dialog on screen)."""
    with hand.page.expect_file_chooser() as fc:
        hand.click('input[name="photo"]')
    fc.value.set_files(str(path))
    time.sleep(1.0)


def _remember(page: Page, folder: Path, name: str) -> None:
    mid = page.evaluate("new URLSearchParams(location.search).get('id')")
    if mid:
        path = folder / "ids.json"
        ids = json.loads(path.read_text(encoding="utf-8"))
        ids[name] = mid
        path.write_text(json.dumps(ids, indent=2), encoding="utf-8")
        print(f"  {name}: {mid}")


def c01(hand: Hand, ids: dict) -> None:
    """Photo, no text: Spark reads the framing, SAM masks the bowl, Muse paints, Spark critiques."""
    _choose_photo(hand, ids["_dir"] / "photos" / "bowl.jpg")
    hand.click('#request button[type="submit"]')
    hand.page.wait_for_selector("#understanding:not([hidden]) #und-text:not(:empty)", timeout=120_000)
    hand.move(1500, 300)
    time.sleep(3.0)  # the overlay and Spark's sentence
    _done(hand.page, critique=True)
    time.sleep(2.0)
    _remember(hand.page, ids["_dir"], "bowl")


def c07(hand: Hand, ids: dict) -> None:
    """Text: typed, sent, the material."""
    hand.click('textarea[name="text"]')
    hand.page.keyboard.type(TEXTS["oak"], delay=55)
    time.sleep(0.8)
    hand.click('#request button[type="submit"]')
    hand.move(760, 470, 0.8)
    _done(hand.page, critique=False)
    time.sleep(2.0)


# Points on the bowl photo (0..1 of the picker image): the bowl's glaze, the plush, the desk mat
SAM_POINTS = [(0.42, 0.52), (0.79, 0.21), (0.70, 0.86)]


def c16(hand: Hand, ids: dict) -> None:
    """SAM on the user's clicks: one material per surface pointed at."""
    _choose_photo(hand, ids["_dir"] / "photos" / "bowl.jpg")
    hand.click("#library-mode")
    hand.page.wait_for_selector("#lib-points:not([hidden]) #pick-img", timeout=10_000)
    time.sleep(0.8)
    b = hand.page.locator("#pick-img").bounding_box()
    for fx, fy in SAM_POINTS:
        hand.move(b["x"] + b["width"] * fx, b["y"] + b["height"] * fy, 0.6)
        time.sleep(0.35)
        hand.page.evaluate("([x, y]) => window.__curRing(x, y)", [hand.x, hand.y])
        hand.page.mouse.click(hand.x, hand.y)
        time.sleep(0.6)
    hand.click('#request button[type="submit"]')
    hand.page.wait_for_selector("#understanding:not([hidden]) #und-items button", timeout=150_000)
    hand.move(1500, 320)
    time.sleep(3.0)  # every mask on the photo, the cards
    hand.page.wait_for_function("/materials ready|Failed/.test(document.querySelector('#status')?.textContent || '')",
                                timeout=290_000)
    time.sleep(1.5)
    hand.click("#und-items button.main:not(.failed):not(.pending) >> nth=1")
    time.sleep(2.5)


# take name -> (material name in ids.json, or None for an empty page; what it does; start state)
TAKES = {
    "c01_bowl_auto": (None, c01, blank(True, "1024")),
    "c07_text_oak": (None, c07, blank(False, "512")),
    "c16_sam_points": (None, c16, blank(False, "512")),
    "c02_bowl_look": ("bowl", c02, None),
    "c03_bowl_maps": ("bowl", c03, None),
    "c04_bowl_critique": ("bowl", c04, None),
    "c05_diamond": ("diamond", c05, None),
    "c06_ruby_live": ("ruby", c06, None),
    "c09_passes": ("oak", c09, None),
    "c09b_thickness": ("ruby", c09b, None),
    "c10_gallery_live_steel": ("steel", gallery("dragon"), None),
    "c10_gallery_live_moss": ("moss", gallery("lucy"), None),
    "c10_gallery_live_limestone": ("limestone", gallery("buddha"), None),
    "c10_gallery_live_oak": ("oak", gallery("dragon"), None),
    "c15_desk_cube": ("cube", desk, None),
    "c15_desk_plush": ("plush", desk, None),
}


# --- recorders -------------------------------------------------------------------------------

class Obs:
    def __init__(self, out: Path):
        from obs_setup import client  # the password comes from OBS's config (or OBS_PW)
        self.c = client()
        self.c.set_current_program_scene("APP_AUTO")
        self.c.set_record_directory(str(out))

    def start(self, name: str) -> None:
        self.c.set_profile_parameter("Output", "FilenameFormatting", name)  # the file comes out named
        self.c.start_record()
        time.sleep(1.0)

    def stop(self) -> None:
        time.sleep(2.0)
        self.c.stop_record()
        time.sleep(1.5)


def chrome(p, site: str, out: Path, recorder: str) -> tuple[BrowserContext, Page]:
    args = ["--enable-unsafe-webgpu", "--lang=en-US", "--force-device-scale-factor=1",
            f"--window-size={W},{H}", "--window-position=0,0"]
    if recorder == "obs":
        # kiosk: the page alone, full screen at 1920x1080 (no title bar, tabs or address bar), and
        # without --enable-automation, whose "Chrome is controlled by automated test software" bar
        # would sit across the top of every take
        ctx = p.chromium.launch_persistent_context(str(out.parent / "chrome-profile"), channel="chrome",
                                                   headless=False, no_viewport=True,
                                                   args=[*args, "--kiosk", f"--app={site}"],
                                                   ignore_default_args=["--enable-automation"],
                                                   accept_downloads=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
    else:
        browser = p.chromium.launch(channel="chrome", headless=False, args=args)
        ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(out / "_video"),
                                  record_video_size={"width": W, "height": H}, accept_downloads=True)
        page = ctx.new_page()
    ctx.add_init_script(CURSOR_JS)
    ctx.add_init_script("localStorage.setItem('matterlift.tutorial.hidden', '1')")
    return ctx, page


def run_takes(names: list[str], site: str, folder: Path, recorder: str) -> None:
    path = folder / "ids.json"
    ids = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    out = folder / ("captures" if recorder == "obs" else "test-takes")
    out.mkdir(parents=True, exist_ok=True)
    names = list(TAKES) if names == ["all"] else [n for n in TAKES if any(n.startswith(a) for a in names)]
    with sync_playwright() as p:
        obs = Obs(out) if recorder == "obs" else None
        ctx, page = chrome(p, site, out, recorder)
        for name in names:
            mat, take, prep = TAKES[name]
            if mat is not None and mat not in ids:
                print(f"skip {name}: no '{mat}' in ids.json")
                continue
            if not obs:
                page = ctx.new_page()  # one page, so one video, per take
            opened = time.time()
            if mat is None:
                prep(page, site)
            else:
                open_material(page, site, ids[mat])
            page.evaluate(CURSOR_JS)
            hand = Hand(page)
            hand.move(W * 0.62, H * 0.55, 0.01)
            if obs:
                obs.start(name)
            else:
                time.sleep(1.0)  # the still second at the head
            t = time.time()
            try:
                take(hand, {**ids, "_dir": folder})
                if not obs:
                    time.sleep(2.0)
                print(f"{name}: {time.time() - t:.0f} s")
            except Exception as e:  # noqa: BLE001  a failed take is reported, the others still run
                print(f"{name}: FAILED {type(e).__name__}: {str(e)[:200]}")
            finally:
                if obs:
                    obs.stop()
                else:
                    video = page.video
                    page.close()
                    video.save_as(out / f"{name}.webm")
                    _trim(out / f"{name}.webm", t - 1.0 - opened)
        ctx.close()


def _trim(webm: Path, head: float) -> None:
    """A test take starts with the page loading: cut it, keep an mp4 (ffmpeg, if installed)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return
    mp4 = webm.with_suffix(".mp4")
    done = subprocess.run([ffmpeg, "-v", "error", "-y", "-ss", f"{max(0.0, head):.2f}", "-i", str(webm),
                           "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(mp4)])
    if done.returncode == 0:
        webm.unlink()


# --- pre-generation (runbook §2) ---------------------------------------------------------------

def _photo_bytes(path: Path) -> bytes:
    """As the page sends it: upright, 2048 px, JPEG."""
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    im.thumbnail((2048, 2048), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def pregen(site: str, folder: Path, only: list[str]) -> None:
    path = folder / "ids.json"
    ids = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    with httpx.Client(timeout=600) as c:
        c.get(f"{site}/health").raise_for_status()
        for name in [*TEXTS, *PHOTOS]:
            if (only and name not in only) or (name in ids and not only):
                continue
            t = time.time()
            if name in TEXTS:
                r = c.post(f"{site}/materials", data={"text": TEXTS[name], "size": "1024"})
            else:
                photo = folder / "photos" / PHOTOS[name]
                if not photo.exists():
                    print(f"skip {name}: {photo} is missing")
                    continue
                und = c.post(f"{site}/understand", files={"photo": (photo.name, _photo_bytes(photo), "image/jpeg")})
                und.raise_for_status()
                r = c.post(f"{site}/materials", data={"understanding": und.json()["id"], "size": "1024"})
            if r.status_code >= 400:
                print(f"{name}: FAILED {r.status_code} {r.text[:200]}")
                continue
            mid = r.json()["id"]
            if name in PHOTOS:  # with the critique, as the page does with self-critique on
                crit = c.post(f"{site}/materials/{mid}/critique")
                if crit.status_code < 400:
                    mid = crit.json()["chosen"]
            ids[name] = mid
            path.write_text(json.dumps(ids, indent=2), encoding="utf-8")
            print(f"{name}: {mid}  {time.time() - t:.0f} s  {site}/?id={mid}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pregen", "takes"])
    ap.add_argument("names", nargs="*", help="takes: names or prefixes (c06, c10) or 'all'; pregen: materials")
    ap.add_argument("--site", default=SITE)
    ap.add_argument("--dir", default=str(DIR))
    ap.add_argument("--recorder", choices=["video", "obs"], default="video")
    args = ap.parse_args()
    folder = Path(args.dir)
    folder.mkdir(parents=True, exist_ok=True)
    if args.cmd == "pregen":
        pregen(args.site.rstrip("/"), folder, args.names)
    else:
        run_takes(args.names or ["all"], args.site.rstrip("/"), folder, args.recorder)


if __name__ == "__main__":
    main()
