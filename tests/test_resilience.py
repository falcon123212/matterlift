"""Failure injection: every Meta model can miss or fail, and a material must still come out."""
import io

import httpx
import numpy as np
import pytest
from PIL import Image

from matterlift_api import meta_client
from matterlift_api.library import build_library, understand_library
from matterlift_api.meta_client import Box, MetaClient, Segment
from matterlift_api.pipeline import Pipeline, normalize_photo

PLAN = {"name": "oak_table", "texture_prompt": "warm oak planks", "sam_prompt": "table",
        "sam_alternatives": ["wooden tabletop"], "points": [[500, 500], [550, 520]], "roughness": 0.6}


def _noise(w=512, h=512, seed=0):
    rng = np.random.default_rng(seed)
    return Image.fromarray((rng.random((h, w, 3)) * 255).astype(np.uint8))


def _seg(photo, x0, y0, x1, y1, oid=0):
    mask = np.zeros((photo.height, photo.width), dtype=bool)
    mask[y0:y1, x0:x1] = True
    return Segment(oid, Box(x0, y0, x1 - 1, y1 - 1), mask)


class FakeClient:
    """Stands in for MetaClient. `found` maps SAM prompts to a box; anything else finds nothing."""

    def __init__(self, plan=PLAN, found=None, point_box=None, edit_fails=False, height_fails=False,
                 library=None):
        self.plan, self.found, self.point_box = plan, found or {}, point_box
        self.edit_fails, self.height_fails, self.library = edit_fails, height_fails, library
        self.calls = []

    def chat_json(self, system, user, images=None):
        self.calls.append("spark")
        return self.library if self.library is not None and "materials" in system else self.plan

    def segment(self, photo, prompt, max_side=1024):
        self.calls.append(f"sam:{prompt}")
        box = self.found.get(prompt)
        return [_seg(photo, *box)] if box else []

    def segment_points(self, photo, points, max_side=1024):
        self.calls.append("sam:points")
        return {1: _seg(photo, *self.point_box, oid=1)} if self.point_box else {}

    def generate_image(self, prompt, size="1024x1024", reasoning="low"):
        self.calls.append("muse:text")
        return _noise(seed=1)

    def edit_image(self, image, prompt, reasoning="low"):
        is_height = "height map" in prompt
        self.calls.append("muse:height" if is_height else "muse:edit")
        if (self.height_fails if is_height else self.edit_fails):
            raise RuntimeError("/images/edits 503: overloaded")
        return _noise(seed=2).convert("L").convert("RGB") if is_height else _noise(seed=3)


@pytest.fixture
def photo():
    return _noise(800, 600, seed=4)


def _pipe(tmp_path, client):
    return Pipeline(client, data_dir=tmp_path / "materials", understand_dir=tmp_path / "understand")


def test_sam_misses_main_name_but_finds_alternative(tmp_path, photo):
    client = FakeClient(found={"wooden tabletop": (100, 100, 700, 500)})
    und = _pipe(tmp_path, client).understand("take this wood", photo)
    assert und.matched and und.crop_from == "mask"
    assert und.found_by == 'SAM "wooden tabletop"'
    assert client.calls[:3] == ["spark", "sam:table", "sam:wooden tabletop"]


def test_sam_finds_nothing_falls_back_to_spark_points(tmp_path, photo):
    client = FakeClient()
    pipe = _pipe(tmp_path, client)
    und = pipe.understand("take this wood", photo)
    assert und.matched and und.crop_from == "points" and len(und.crops) == 1
    mat = pipe.run_understood(und, 256)
    assert mat.source == "photo"
    assert "sam:points" in client.calls


def test_garbage_plan_still_gives_a_material(tmp_path, photo):
    client = FakeClient(plan={"name": 42, "roughness": "rough", "points": "here", "shading": None})
    mat = _pipe(tmp_path, client).run("vieux bois", photo, 256)
    assert mat.plan.texture_prompt == "vieux bois"  # the request stands in for the missing description
    assert {"albedo", "normal", "height"} <= mat.maps.keys()


def test_muse_edit_and_height_fail_still_gives_a_material(tmp_path, photo):
    client = FakeClient(found={"table": (100, 100, 700, 500)}, edit_fails=True, height_fails=True)
    mat = _pipe(tmp_path, client).run("take this wood", photo, 256)
    assert mat.source == "text" and "muse_edit_failed" in mat.scores
    assert "muse_height" not in mat.maps  # maps fell back to luminance
    assert "muse:text" in client.calls


def test_library_builds_found_and_missing_materials(tmp_path, photo):
    listing = {"materials": [
        {"name": "brick_wall", "texture_prompt": "red brick", "sam_prompt": "brick wall"},
        {"name": "rush_seat", "texture_prompt": "woven rush", "sam_prompt": "rush seat"},  # no points
        "not a plan",
    ]}
    client = FakeClient(library=listing, found={"brick wall": (0, 0, 800, 300)})
    pipe = _pipe(tmp_path, client)
    lib = understand_library(pipe, photo, root=tmp_path / "libraries")
    assert [i.plan.name for i in lib.items] == ["brick_wall", "rush_seat"]
    assert lib.items[0].crops and not lib.items[1].crops
    assert "painted from its description" in lib.items[1].error
    lib = build_library(pipe, lib, 256, root=tmp_path / "libraries")
    assert all(i.material is not None for i in lib.items)
    assert lib.items[1].material.source == "text"


def test_phone_photo_is_turned_upright():
    img = Image.new("RGB", (400, 200))
    exif = img.getexif()
    exif[0x0112] = 6  # rotated 90 degrees, as phones store portrait shots
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    upright = normalize_photo(Image.open(buf))
    assert upright.size == (200, 400)


def test_big_photo_is_scaled_down():
    assert max(normalize_photo(Image.new("RGB", (6000, 4000))).size) == 2048


def _client_with(handler, monkeypatch):
    monkeypatch.setattr(meta_client, "_BACKOFF", (0, 0, 0))
    c = MetaClient(api_key="test")
    c.http = httpx.Client(base_url="https://api.test", transport=httpx.MockTransport(handler))
    return c


def test_retries_transient_errors(monkeypatch):
    answers = iter([httpx.Response(503), httpx.Response(429), httpx.Response(200, json={"ok": 1})])
    c = _client_with(lambda req: next(answers), monkeypatch)
    assert c._post("/x") == {"ok": 1}


def test_does_not_retry_client_errors(monkeypatch):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(400, json={"error": "bad"})

    c = _client_with(handler, monkeypatch)
    with pytest.raises(RuntimeError, match="400"):
        c._post("/x")
    assert len(calls) == 1


def test_network_failure_becomes_runtime_error(monkeypatch):
    def handler(req):
        raise httpx.ConnectError("no route")

    c = _client_with(handler, monkeypatch)
    with pytest.raises(RuntimeError, match="ConnectError"):
        c._post("/x")
