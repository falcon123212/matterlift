"""Thin client for the Meta Model API (OpenAI-compatible, https://api.meta.ai/v1).

Endpoints as observed on 2026-11-01:
- Spark: /chat/completions (reasoning model, needs a generous max_completion_tokens)
- Muse Image: /images/generations and /images/edits (no `mask` field), returns WebP as b64_json
- SAM 3.1: /responses only. Output text is a list of `<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..|>`
  followed by an entropy-coded `<|mask;...|>` we do not decode; boxes are used instead.
- Voice Transcribe: /audio/transcriptions
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
from dotenv import load_dotenv
from PIL import Image

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

BASE_URL = os.environ.get("META_BASE_URL", "https://api.meta.ai/v1").rstrip("/")
MODEL_SPARK = os.environ.get("META_MODEL_SPARK", "muse-spark-1.3")
MODEL_IMAGE = os.environ.get("META_MODEL_IMAGE", "muse-image-1.0")
MODEL_SAM = os.environ.get("META_MODEL_SAM", "sam-3.1")
MODEL_TRANSCRIBE = os.environ.get("META_MODEL_TRANSCRIBE", "muse-voice-transcribe-1.0")

_BOX_RE = re.compile(r"<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)\|>")


@dataclass
class Box:
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def area(self) -> int:
        return (self.x2 - self.x1) * (self.y2 - self.y1)

    def scaled(self, sx: float, sy: float) -> "Box":
        return Box(round(self.x1 * sx), round(self.y1 * sy), round(self.x2 * sx), round(self.y2 * sy))


def image_to_data_url(img: Image.Image, max_side: int = 1024) -> str:
    img = img.convert("RGB")
    if max(img.size) > max_side:
        img = img.copy()
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _decode_image(b64: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")


def _extract_json(text: str) -> dict:
    """Spark sometimes wraps JSON in prose or code fences."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


class MetaClient:
    def __init__(self, api_key: str | None = None, timeout: float = 240.0):
        key = api_key or os.environ.get("META_API_KEY")
        if not key:
            raise RuntimeError("META_API_KEY is not set (see .env.example)")
        self.http = httpx.Client(
            base_url=BASE_URL, headers={"Authorization": f"Bearer {key}"}, timeout=timeout
        )

    def _post(self, path: str, **kw) -> dict:
        r = self.http.post(path, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{path} {r.status_code}: {r.text[:500]}")
        return r.json()

    def models(self) -> list[str]:
        r = self.http.get("/models")
        r.raise_for_status()
        return [m["id"] for m in r.json()["data"]]

    # --- Muse Spark -------------------------------------------------------
    def chat(self, system: str, user: str, images: list[Image.Image] | None = None,
             max_tokens: int = 6000) -> str:
        content: list[dict] | str = user
        if images:
            content = [{"type": "text", "text": user}] + [
                {"type": "image_url", "image_url": {"url": image_to_data_url(i)}} for i in images
            ]
        j = self._post("/chat/completions", json={
            "model": MODEL_SPARK,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "max_completion_tokens": max_tokens,
        })
        return j["choices"][0]["message"]["content"] or ""

    def chat_json(self, system: str, user: str, images: list[Image.Image] | None = None) -> dict:
        return _extract_json(self.chat(system, user, images))

    # --- Muse Image -------------------------------------------------------
    def generate_image(self, prompt: str, size: str = "1024x1024") -> Image.Image:
        j = self._post("/images/generations", json={
            "model": MODEL_IMAGE, "prompt": prompt, "n": 1, "size": size,
        })
        return _decode_image(j["data"][0]["b64_json"])

    def edit_image(self, image: Image.Image, prompt: str) -> Image.Image:
        buf = io.BytesIO()
        image.convert("RGB").save(buf, "PNG")
        j = self._post("/images/edits", data={"model": MODEL_IMAGE, "prompt": prompt},
                       files={"image": ("image.png", buf.getvalue(), "image/png")})
        return _decode_image(j["data"][0]["b64_json"])

    # --- SAM 3.1 ----------------------------------------------------------
    def segment_boxes(self, image: Image.Image, prompt: str, max_side: int = 1024) -> list[Box]:
        """Boxes in the original image's pixel coordinates, largest first."""
        j = self._post("/responses", json={
            "model": MODEL_SAM,
            "input": [{"role": "user", "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": image_to_data_url(image, max_side)},
            ]}],
        })
        text = "".join(
            c.get("text", "") for o in j.get("output", []) for c in o.get("content", [])
        )
        boxes = []
        for x1, y1, x2, y2, w, h in _BOX_RE.findall(text):
            b = Box(int(x1), int(y1), int(x2), int(y2))
            boxes.append(b.scaled(image.width / int(w), image.height / int(h)))
        return sorted(boxes, key=lambda b: b.area, reverse=True)

    # --- Voice ------------------------------------------------------------
    def transcribe(self, audio: bytes, filename: str = "audio.webm") -> str:
        j = self._post("/audio/transcriptions", data={"model": MODEL_TRANSCRIBE},
                       files={"file": (filename, audio, "application/octet-stream")})
        return j.get("text", "")
