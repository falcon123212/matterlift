"""What users actually upload, through the HTTP API: every photo format a phone or a browser can
send, broken files, huge ones, odd audio, bad ids and parameters. Each one gives a material or a
clear 4xx error, never a crash. The Meta models are replaced by the fake client (no network)."""
import io
import struct
import wave
import zlib

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from matterlift_api import main
from matterlift_api.meta_client import to_asr_wav
from matterlift_api.pipeline import Pipeline, load_material

from .test_resilience import FakeClient, _noise


class ApiFake(FakeClient):
    def transcribe(self, audio, keywords=None):
        x = np.frombuffer(to_asr_wav(audio)[44:], dtype=np.int16)  # parses the WAV like the real one
        return "old oak planks" if np.abs(x).max(initial=0) > 300 else ""


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_pipeline", Pipeline(ApiFake(), data_dir=tmp_path / "m", understand_dir=tmp_path / "u"))
    monkeypatch.setattr(main, "load_material", lambda mid: load_material(mid, tmp_path / "m"))
    return TestClient(main.app, raise_server_exceptions=False)


def _bytes(img: Image.Image, fmt: str, **kw) -> bytes:
    b = io.BytesIO()
    img.save(b, fmt, **kw)
    return b.getvalue()


def _wav(samples: np.ndarray, rate=48_000) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(samples.astype(np.int16).tobytes())
    return b.getvalue()


def _png_claiming(width: int, height: int) -> bytes:
    """A tiny valid PNG whose header claims a huge size (a decompression bomb)."""
    data = bytearray(_bytes(Image.new("L", (1, 1)), "PNG"))
    ihdr = struct.pack(">II", width, height) + bytes(data[24:29])
    data[16:29] = ihdr
    data[29:33] = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
    return bytes(data)


def _exif_rotated() -> bytes:
    exif = Image.Exif()
    exif[0x0112] = 6  # phone held upright: rotate 90
    return _bytes(_noise(640, 480, seed=5), "JPEG", exif=exif)


PHOTOS = {
    "jpeg": lambda: _bytes(_noise(800, 600), "JPEG"),
    "png_rgba_transparent": lambda: _bytes(_noise(600, 600).convert("RGBA"), "PNG"),
    "png_palette": lambda: _bytes(_noise(600, 600).convert("P"), "PNG"),
    "png_16bit_grey": lambda: _bytes(Image.fromarray((np.random.default_rng(0).random((500, 500)) * 65535).astype(np.uint16)), "PNG"),
    "jpeg_greyscale": lambda: _bytes(_noise(600, 600).convert("L"), "JPEG"),
    "jpeg_cmyk": lambda: _bytes(_noise(600, 600).convert("CMYK"), "JPEG"),
    "webp": lambda: _bytes(_noise(600, 600), "WEBP"),
    "phone_exif_rotated": _exif_rotated,
    "panorama_4000x300": lambda: _bytes(_noise(4000, 300), "JPEG"),
    "tiny_24px": lambda: _bytes(_noise(24, 24), "PNG"),
    "huge_6000px": lambda: _bytes(_noise(6000, 4500), "JPEG", quality=70),
}


@pytest.mark.parametrize("kind", PHOTOS)
def test_every_photo_format_gives_a_material(api, kind):
    r = api.post("/materials", data={"text": "this surface", "size": "512"},
                 files={"photo": (f"p.{kind}", PHOTOS[kind](), "application/octet-stream")})
    assert r.status_code == 200, (kind, r.text[:300])
    assert r.json()["maps"]["albedo"]


@pytest.mark.parametrize("kind", PHOTOS)
def test_every_photo_format_can_be_understood(api, kind):
    r = api.post("/understand", data={"text": "the table"}, files={"photo": ("p", PHOTOS[kind](), "image/*")})
    assert r.status_code == 200, (kind, r.text[:300])


BROKEN = {
    "not_an_image": (b"hello, this is text", 400),
    "empty_file": (b"", 400),
    "truncated_jpeg": (_bytes(_noise(800, 600), "JPEG")[:2000], 400),
    "decompression_bomb": (_png_claiming(30_000, 30_000), 400),
    "too_big_upload": (b"\xff" * 31_000_000, 413),
}


@pytest.mark.parametrize("kind", BROKEN)
def test_broken_photos_are_refused_clearly(api, kind):
    data, status = BROKEN[kind]
    r = api.post("/materials", data={"text": "x"}, files={"photo": ("p.jpg", data, "image/jpeg")})
    assert r.status_code == status, (kind, r.status_code, r.text[:300])
    assert r.json()["detail"], kind


def test_voice_requests(api):
    speech = np.sin(np.linspace(0, 3000, 48_000)) * 8000
    r = api.post("/transcribe", files={"audio": ("v.wav", _wav(speech), "audio/wav")})
    assert r.status_code == 200 and r.json()["text"] == "old oak planks"
    r = api.post("/transcribe", files={"audio": ("v.wav", _wav(np.zeros(48_000)), "audio/wav")})
    assert r.status_code == 422 and "silent" in r.json()["detail"]
    r = api.post("/transcribe", files={"audio": ("v.webm", b"\x1aE\xdf\xa3 not a wav", "audio/webm")})
    assert r.status_code == 400 and "not a readable WAV" in r.json()["detail"]
    r = api.post("/materials", data={"size": "512"}, files={"audio": ("v.wav", _wav(speech), "audio/wav")})
    assert r.status_code == 200 and r.json()["request"] == "old oak planks"


@pytest.mark.parametrize("path", [
    "/materials/..%2F..%2Fetc%2Fpasswd", "/materials/abc-def", "/materials/nope/maps/..%2Fsecret.png",
    "/materials/nope/maps/albedo.png", "/materials/nope/export", "/libraries/..%2F..", "/understand/x/..%2F.env",
    "/libraries/nope/photo.jpg",
])
def test_bad_ids_and_paths_are_404(api, path):
    assert api.get(path).status_code == 404, path


@pytest.mark.parametrize("data,status", [
    ({"text": "oak", "size": "777"}, 400), ({"text": "oak", "size": "big"}, 422), ({"text": "   "}, 400),
    ({}, 400), ({"understanding": "../../x"}, 404), ({"understanding": "doesnotexist"}, 404),
])
def test_bad_material_parameters(api, data, status):
    assert api.post("/materials", data=data).status_code == status, data


def test_bad_export_parameters_and_empty_enrich(api):
    mid = api.post("/materials", data={"text": "oak", "size": "512"}).json()["id"]
    assert api.get(f"/materials/{mid}/export?size=300").status_code == 400
    assert api.get(f"/materials/{mid}/export?fmt=exr").status_code == 400
    assert api.post("/enhance", data={"text": "  "}).status_code == 400
