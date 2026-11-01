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
                 library=None, reviews=None):
        self.plan, self.found, self.point_box = plan, found or {}, point_box
        self.edit_fails, self.height_fails, self.library = edit_fails, height_fails, library
        self.reviews = list(reviews or [])
        self.calls = []

    def chat_json(self, system, user, images=None):
        if "senior material artist" in system:
            self.calls.append("spark:review")
            return self.reviews.pop(0) if self.reviews else {"score": 7, "issues": []}
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


def test_photo_material_reports_colour_fidelity(tmp_path, photo):
    client = FakeClient(found={"table": (100, 100, 700, 500)})
    mat = _pipe(tmp_path, client).run("take this wood", photo, 256)
    fid = mat.scores["fidelity"]
    assert fid["delta_e_after"] <= fid["delta_e_before"]
    assert "photo_sample" in mat.maps


def _material(tmp_path, client, photo):
    pipe = _pipe(tmp_path, client)
    return pipe, pipe.run("take this wood", photo, 256)


def test_critique_param_fix_is_kept_when_spark_likes_it(tmp_path, photo):
    from matterlift_api.critique import critique

    client = FakeClient(found={"table": (100, 100, 700, 500)}, reviews=[
        {"score": 5, "issues": ["normals too flat"], "params": {"normal_strength": 1.8, "bogus": 3}, "albedo_fix": ""},
        {"score_a": 5, "score_b": 8, "better": "B", "remaining": []},
    ])
    pipe, mat = _material(tmp_path, client, photo)
    calls_before = client.calls.count("muse:edit")
    c = critique(pipe, mat)
    assert (c.score_before, c.score_after) == (5, 8) and c.chosen == c.after != c.before
    assert c.params_changed == {"normal_strength": [mat.plan.normal_strength, 1.8]}
    assert client.calls.count("muse:edit") == calls_before  # parameters only: no new image
    assert (tmp_path / "materials" / c.after / "normal.png").exists()


def test_critique_repaint_goes_through_muse(tmp_path, photo):
    from matterlift_api.critique import critique

    client = FakeClient(found={"table": (100, 100, 700, 500)}, reviews=[
        {"score": 4, "issues": ["baked shadow"], "params": {}, "albedo_fix": "remove the dark shadow"},
        {"score_a": 4, "score_b": 7, "better": "B"},
    ])
    pipe, mat = _material(tmp_path, client, photo)
    c = critique(pipe, mat)
    assert c.albedo_fix == "remove the dark shadow" and c.chosen == c.after
    assert client.calls[-3:] == ["muse:edit", "muse:height", "spark:review"]


def test_critique_keeps_original_when_the_fix_is_worse(tmp_path, photo):
    from matterlift_api.critique import critique

    client = FakeClient(found={"table": (100, 100, 700, 500)}, reviews=[
        {"score": 7, "issues": ["a bit shiny"], "params": {"roughness": 0.9}},
        {"score_a": 7, "score_b": 5, "better": "A", "remaining": ["now too matte"]},
    ])
    pipe, mat = _material(tmp_path, client, photo)
    assert critique(pipe, mat).chosen == mat.id


def test_critique_survives_a_failed_repaint_and_a_garbage_review(tmp_path, photo):
    from matterlift_api.critique import critique

    client = FakeClient(found={"table": (100, 100, 700, 500)}, reviews=[
        {"score": "six", "issues": "not a list", "params": {"wear": 0.5}, "albedo_fix": "repaint"},
        "garbage",
    ])
    pipe, mat = _material(tmp_path, client, photo)
    client.edit_fails = True  # Muse is down for the repaint
    c = critique(pipe, mat)
    assert c.albedo_fix == "" and c.params_changed == {"wear": [mat.plan.wear, 0.5]}
    assert c.issues == ["not a list"] and c.score_before == 5  # garbage verdict -> neutral 5s


def test_critique_colour_fix_is_deterministic_no_muse(tmp_path, photo):
    from matterlift_api.critique import critique

    client = FakeClient(found={"table": (100, 100, 700, 500)}, reviews=[
        {"score": 5, "issues": ["too orange"], "params": {}, "match_photo_colour": True},
        {"score_a": 5, "score_b": 7, "better": "B"},
    ])
    pipe, mat = _material(tmp_path, client, photo)
    edits = client.calls.count("muse:edit")
    c = critique(pipe, mat)
    assert c.colour_matched and c.chosen == c.after
    assert client.calls.count("muse:edit") == edits
