"""README art: the hero banner and the "words -> maps -> render" strip, built from the gallery's
Live RT captures and a committed export (samples/export). Run after capture_readme.py.

    .venv/Scripts/python scripts/readme_art.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "docs" / "img"
BG = (11, 12, 16)
ACCENT = (214, 170, 96)  # the page's gold
FONTS = Path("C:/Windows/Fonts")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for name in (("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")):
        if (FONTS / name).exists():
            return ImageFont.truetype(str(FONTS / name), size)
    return ImageFont.load_default(size)


def backdrop(w: int, h: int) -> Image.Image:
    """Near-black with a warm glow on the right, where the renders stand."""
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    glow = np.exp(-(((x - w * 0.72) / (w * 0.35)) ** 2 + ((y - h * 0.55) / (h * 0.6)) ** 2))
    base = np.array(BG, np.float32)
    warm = np.array([46, 36, 24], np.float32)
    return Image.fromarray((base + glow[..., None] * warm).clip(0, 255).astype(np.uint8))


def soft(img: Image.Image, size: tuple[int, int], feather: float = 0.22) -> tuple[Image.Image, Image.Image]:
    """The render scaled to `size` and an elliptic alpha that fades its frame into the backdrop."""
    img = img.convert("RGB").resize(size, Image.LANCZOS)
    w, h = size
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((x - w / 2) / (w / 2)) ** 2 + ((y - h / 2) / (h / 2)) ** 2)
    a = np.clip((1 - d) / feather, 0, 1) ** 1.5
    return img, Image.fromarray((a * 255).astype(np.uint8))


def hero() -> Path:
    W, H = 1800, 720
    im = backdrop(W, H)
    # one render, large, its render fading into the backdrop (several showed their floor's edge)
    layer, alpha = soft(Image.open(IMG / "live_ruby.jpg"), (1180, 673), feather=0.35)
    im.paste(layer, (760, 40), alpha)
    # a dark veil on the left so the title reads over anything
    veil = np.linspace(1, 0, 900, dtype=np.float32) ** 1.4
    v = np.zeros((H, W), np.float32)
    v[:, :900] = veil[None, :]
    arr = np.asarray(im, np.float32)
    arr = arr * (1 - v[..., None] * 0.85) + np.array(BG, np.float32) * v[..., None] * 0.85
    im = Image.fromarray(arr.clip(0, 255).astype(np.uint8))

    d = ImageDraw.Draw(im)
    d.text((90, 150), "MatterLift", font=font(132, True), fill=(245, 242, 236))
    for k, line in enumerate(("Point at anything.", "Say what you want.", "Get a game-ready material.")):
        d.text((96, 330 + k * 62), line, font=font(46), fill=ACCENT if k == 2 else (215, 212, 205))
    d.text((98, 548), "Photo or voice  →  tileable PBR maps  →  Godot · Blender · glTF · MaterialX · USD",
           font=font(26), fill=(150, 150, 158))
    d.text((98, 598), "Built on Muse Spark · SAM 3.1 · Muse Image · Muse Voice Transcribe", font=font(22),
           fill=(120, 120, 130))
    d.text((98, 632), "META GLOBAL AI HACKATHON 2026", font=font(20, True), fill=ACCENT)
    out = IMG / "hero.jpg"
    im.save(out, quality=90)
    return out


def flow() -> Path:
    """The prompt, the six maps of its export, the material in Live RT."""
    W, H = 1800, 600
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    pkg = ROOT / "samples" / "export" / "OldWornOakParquet_512-PNG"
    stem = pkg.name

    # 1. the words
    d.rounded_rectangle((40, 170, 420, 430), 22, fill=(24, 25, 31), outline=(60, 60, 70), width=2)
    d.text((70, 196), "YOU SAY", font=font(20, True), fill=ACCENT)
    y = 236
    for line in ("“very worn,", "scratched old", "oak parquet”"):
        d.text((70, y), line, font=font(40), fill=(240, 238, 232))
        y += 52

    # 2. the maps
    maps = [("Color", "Color"), ("NormalGL", "Normal"), ("Roughness", "Roughness"),
            ("AmbientOcclusion", "AO"), ("Displacement", "Height"), (None, "Preview")]
    S, G, x0, y0 = 170, 14, 500, 95
    for k, (key, label) in enumerate(maps):
        path = pkg / (f"{stem}_{key}.png" if key else "OldWornOakParquet.png")
        src = Image.open(path)
        if src.mode.startswith("I"):  # the 16-bit height: to 8 bits before RGB, or it saturates white
            a = np.asarray(src, np.float32)
            src = Image.fromarray(((a - a.min()) / max(float(np.ptp(a)), 1) * 255).astype(np.uint8))
        tile = src.convert("RGB").resize((S, S), Image.LANCZOS)
        x, y = x0 + (k % 3) * (S + G), y0 + (k // 3) * (S + G + 34)
        im.paste(tile, (x, y))
        d.text((x, y + S + 6), label, font=font(20), fill=(170, 170, 178))
    d.text((x0, 40), "MATTERLIFT MAKES", font=font(20, True), fill=ACCENT)

    # 3. the render
    rx, ry, rw = 1120, 120, 640
    render = Image.open(IMG / "live_oak_parquet.jpg").convert("RGB")
    render = render.resize((rw, round(render.height * rw / render.width)), Image.LANCZOS)
    im.paste(render, (rx, ry))
    d.text((rx, 70), "PATH TRACED IN YOUR BROWSER", font=font(20, True), fill=ACCENT)
    d.text((rx, ry + render.height + 10), "Live RT · WebGPU ReSTIR · material study", font=font(20),
           fill=(150, 150, 158))

    for ax in (450, 1075):  # arrows
        d.line((ax, 300, ax + 32, 300), fill=ACCENT, width=4)
        d.polygon([(ax + 32, 290), (ax + 46, 300), (ax + 32, 310)], fill=ACCENT)
    out = IMG / "flow.jpg"
    im.save(out, quality=90)
    return out


def photo_strips(run: Path, names: list[str]) -> list[Path]:
    """Per photo of a photo_test run: the square sampled from the photo beside the texture made from it
    (<run>/<k>_crop.jpg, and <run>/<k>_albedo_kept.jpg when the critique kept a fixed version, else
    <run>/<k>_albedo.jpg), labelled, as docs/img/photo_<name>_texture.jpg."""
    outs = []
    for k, name in enumerate(names, 1):
        S, G, top = 440, 12, 30
        im = Image.new("RGB", (2 * S + G, S + top), (17, 18, 22))
        d = ImageDraw.Draw(im)
        albedo = f"{k}_albedo_kept.jpg" if (run / f"{k}_albedo_kept.jpg").exists() else f"{k}_albedo.jpg"
        for col, (f, label) in enumerate(((f"{k}_crop.jpg", "photo sample"), (albedo, "texture (tileable albedo)"))):
            src = Image.open(run / f).convert("RGB")
            side = min(src.size)  # the square middle, as the page shows it
            src = src.crop(((src.width - side) // 2, (src.height - side) // 2,
                            (src.width + side) // 2, (src.height + side) // 2)).resize((S, S), Image.LANCZOS)
            im.paste(src, (col * (S + G), top))
            d.text((col * (S + G) + 4, 3), label, font=font(20), fill=(200, 200, 205))
        outs.append(IMG / f"photo_{name}_texture.jpg")
        im.save(outs[-1], quality=90)
    return outs


if __name__ == "__main__":
    for p in (hero(), flow()):
        print(p.relative_to(ROOT), Image.open(p).size, p.stat().st_size // 1024, "KB")
