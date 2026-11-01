"""Thin client for the Meta Model API (OpenAI-compatible, https://api.meta.ai/v1).

Endpoints (docs: https://dev.meta.ai/docs):
- Spark: /chat/completions (reasoning model, needs a generous max_completion_tokens)
- Muse Image: /images/generations and /images/edits (no `mask` field); tools off and PNG out for textures
- SAM 3.1: /responses only. Output text: per instance a box token and a mask token; we request
  one_bit masks (metadata.mask_encoding) and decode them in sam_mask.py.
- Voice Transcribe: /asr/transcribe, multipart `request` (JSON settings) + `audio`
  (WAV, mono 16-bit PCM at 16 or 24 kHz only)
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import wave
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np
from dotenv import load_dotenv
from PIL import Image

from .sam_mask import decode_one_bit

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

BASE_URL = os.environ.get("META_BASE_URL", "https://api.meta.ai/v1").rstrip("/")
MODEL_SPARK = os.environ.get("META_MODEL_SPARK", "muse-spark-1.3")
MODEL_IMAGE = os.environ.get("META_MODEL_IMAGE", "muse-image-1.0")
MODEL_SAM = os.environ.get("META_MODEL_SAM", "sam-3.1")
MODEL_TRANSCRIBE = os.environ.get("META_MODEL_TRANSCRIBE", "muse-voice-transcribe-1.0")

# One SAM record: object id, box (with the frame size SAM saw), one_bit mask over the box.
_RECORD_RE = re.compile(
    r"(\d+)<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)(?:;c=[\d.]+)?\|>"
    r"<\|mask;x=0;y=0(?:;c=[\d.]+)?;data=(\d+),(\d+),([^|]*)\|>"
)


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


@dataclass
class Segment:
    id: int
    box: Box
    mask: np.ndarray  # bool, original image size


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
    def _image_options(self, reasoning: str) -> dict:
        # A texture needs no grounding: web/image search and the shell only add latency.
        return {"output_format": "png", "reasoning_strength": reasoning,
                "tool_enablement": {"enable_image_search": False, "enable_web_search": False,
                                    "enable_shell": False}}

    def generate_image(self, prompt: str, size: str = "1024x1024", reasoning: str = "low") -> Image.Image:
        j = self._post("/images/generations", json={
            "model": MODEL_IMAGE, "prompt": prompt, "n": 1, "size": size, **self._image_options(reasoning),
        })
        return _decode_image(j["data"][0]["b64_json"])

    def edit_image(self, image: Image.Image | list[Image.Image], prompt: str,
                   reasoning: str = "low") -> Image.Image:
        """Meta's JSON form of /images/edits (the multipart form cannot carry tool_enablement)."""
        images = image if isinstance(image, list) else [image]
        j = self._post("/images/edits", json={
            "model": MODEL_IMAGE, "prompt": prompt, "n": 1,
            "images": [{"image_url": image_to_data_url(i, 2048)} for i in images],
            **self._image_options(reasoning),
        })
        return _decode_image(j["data"][0]["b64_json"])

    # --- SAM 3.1 ----------------------------------------------------------
    def segment(self, image: Image.Image, prompt: str, max_side: int = 1024) -> list[Segment]:
        """Every instance SAM finds for `prompt`, largest mask first, in original image pixels."""
        j = self._post("/responses", json={
            "model": MODEL_SAM,
            "metadata": {"mask_encoding": "one_bit"},
            "input": [{"role": "user", "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": image_to_data_url(image, max_side)},
            ]}],
        })
        text = "".join(
            c.get("text", "") for o in j.get("output", []) for c in o.get("content", [])
        )
        segments = []
        for oid, x1, y1, x2, y2, w, h, mh, mw, payload in _RECORD_RE.findall(text):
            box = Box(int(x1), int(y1), int(x2), int(y2))
            raster = decode_one_bit(payload, int(mh), int(mw))
            full = np.zeros((int(h), int(w)), dtype=bool)  # mask in the frame SAM saw
            full[box.y1 : box.y1 + raster.shape[0], box.x1 : box.x1 + raster.shape[1]] = raster
            if full.shape != (image.height, image.width):
                full = np.asarray(Image.fromarray(full).resize(image.size, Image.NEAREST))
            segments.append(Segment(int(oid), box.scaled(image.width / int(w), image.height / int(h)), full))
        return sorted(segments, key=lambda s: int(s.mask.sum()), reverse=True)

    def segment_boxes(self, image: Image.Image, prompt: str, max_side: int = 1024) -> list[Box]:
        return [s.box for s in self.segment(image, prompt, max_side)]

    # --- Voice ------------------------------------------------------------
    def transcribe(self, audio: bytes, keywords: list[str] | None = None,
                   languages: tuple[str, ...] = ("French", "English")) -> str:
        """One push-to-talk turn. Any WAV is normalised to what the endpoint accepts."""
        settings = {"model": MODEL_TRANSCRIBE, "audioEncoding": "WAV", "mode": "PUSH_TO_TALK",
                    "languageBias": list(languages)}
        if keywords:
            settings["keywords"] = keywords
        j = self._post("/asr/transcribe", files={
            "request": (None, json.dumps(settings), "application/json"),
            "audio": ("audio.wav", to_asr_wav(audio), "audio/wav"),
        })
        return j.get("transcript", "").strip()


def to_asr_wav(data: bytes, rate: int = 24_000) -> bytes:
    """Any PCM WAV -> mono 16-bit PCM WAV at 24 kHz (the model's native rate)."""
    with wave.open(io.BytesIO(data)) as w:
        ch, width, src_rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        frames = w.readframes(w.getnframes())
    if width not in (1, 2, 4):
        raise ValueError(f"unsupported WAV sample width {width}")
    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}[width]
    x = np.frombuffer(frames, dtype=dtype).astype(np.float64)
    if width == 1:
        x = (x - 128) / 128
    else:
        x /= float(np.iinfo(dtype).max)
    x = x.reshape(-1, ch).mean(axis=1)
    if src_rate != rate:
        n = int(round(len(x) * rate / src_rate))
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    return out.getvalue()
