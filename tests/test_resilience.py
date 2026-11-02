"""Failure injection: every Meta model can miss or fail, and a material must still come out."""
import io

import httpx
import numpy as np
import pytest
from PIL import Image

from matterlift_api import meta_client
from matterlift_api.library import build_library, understand_library
from matterlift_api.meta_client import Box, MetaClient, Segment
from matterlift_api.pipeline import SUBJECT_REQUEST, Pipeline, normalize_photo

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


def test_enhance_returns_spark_brief_or_the_original(tmp_path):
    class Spark(FakeClient):
        def __init__(self, answer):
            super().__init__()
            self.answer = answer

        def chat_json(self, system, user, images=None):
            return self.answer

    good = _pipe(tmp_path, Spark({"text": "Vieux chêne patiné, lames de 12 cm, finition mate cirée."}))
    assert good.enhance("vieux bois").startswith("Vieux chêne")
    for garbage in ("not json", {"text": ""}, {"text": 42}, {}):
        assert _pipe(tmp_path, Spark(garbage)).enhance("vieux bois") == "vieux bois"


def test_audio_level_tells_silence_from_speech():
    import io
    import wave

    from matterlift_api.meta_client import audio_level

    def wav(x):
        b = io.BytesIO()
        with wave.open(b, "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(48_000)
            w.writeframes((x * 32767).astype(np.int16).tobytes())
        return b.getvalue()

    seconds, peak = audio_level(wav(np.zeros(96_000)))
    assert abs(seconds - 2) < 0.01 and peak == 0
    _, peak = audio_level(wav(0.5 * np.sin(np.linspace(0, 2000, 48_000))))
    assert 0.45 < peak < 0.55


def test_library_manual_points_frame_with_spark(tmp_path, photo):
    from matterlift_api.library import clean_points
    client = FakeClient(found={"table": (100, 100, 700, 500)})  # SAM finds Spark's noun phrase
    pipe = _pipe(tmp_path, client)
    points = clean_points([[[500, 500]], [[100, 900], [150, 950]]])
    lib = understand_library(pipe, photo, root=tmp_path / "libraries", points=points)
    assert len(lib.items) == 2 and all(i.manual for i in lib.items)
    assert lib.items[0].plan.points == [(500.0, 500.0)]  # the user's points, not Spark's
    assert lib.items[0].crop_from == "mask" and lib.items[0].found_by == 'SAM "table"'
    # the second group is outside the table: SAM's instance does not contain it, the largest is kept
    assert "spark_points" in lib.timings and "spark_list" not in lib.timings
    assert (tmp_path / "libraries" / lib.id / "mask_0.png").exists()


def test_library_manual_points_without_spark_framing(tmp_path, photo):
    client = FakeClient(found={"table": (100, 100, 700, 500)}, point_box=(200, 200, 600, 450))
    lib = understand_library(_pipe(tmp_path, client), photo, root=tmp_path / "libraries",
                             points=[[(500.0, 500.0)]], frame=False)
    assert lib.items[0].found_by == "SAM on Spark's points"
    assert not any(c.startswith("sam:table") for c in client.calls)  # no noun phrase sent to SAM


def test_library_edit_add_redo_remove_then_build(tmp_path, photo):
    from matterlift_api.library import point_item, remove_item
    root = tmp_path / "libraries"
    listing = {"materials": [{"name": "brick_wall", "texture_prompt": "red brick", "sam_prompt": "brick wall"}]}
    client = FakeClient(library=listing, found={"brick wall": (0, 0, 800, 300), "table": (100, 350, 700, 590)})
    pipe = _pipe(tmp_path, client)
    lib = build_library(pipe, understand_library(pipe, photo, root=root), 256, root=root)
    built_first = lib.items[0].material
    client.library = None  # point plans come from PLAN_SYSTEM
    overlay_before = lib.overlay
    lib = point_item(pipe, lib, [(500.0, 800.0)], root=root)  # add the table
    assert len(lib.items) == 2 and lib.items[1].key == 1 and lib.items[1].material is None
    assert lib.overlay != overlay_before and lib.status == "understood"
    lib = point_item(pipe, lib, [(400.0, 700.0)], index=1, root=root)  # redo it
    assert lib.items[1].key == 2 and (root / lib.id / "crop_2_0.png").exists()
    lib = build_library(pipe, lib, 256, root=root)
    assert lib.items[0].material == built_first  # only the new item was made
    assert lib.items[1].material is not None
    lib = remove_item(lib, 0, root=root)
    assert [i.plan.name for i in lib.items] == ["oak_table"]


def test_library_points_are_validated():
    from matterlift_api.library import clean_points
    assert clean_points([[[1200, -5]]]) == [[(1000.0, 0.0)]]
    for bad in [[], [[]], [[[1, 2, 3]]], [["a", "b"]], "x", [[[0, 0]] * 4]]:
        with pytest.raises(ValueError):
            clean_points(bad)


def test_same_export_twice_at_once(tmp_path, photo):
    """Two downloads of the same package at the same time must not delete each other's files."""
    from concurrent.futures import ThreadPoolExecutor
    from matterlift_api.pipeline import export_material
    mat = _pipe(tmp_path, FakeClient(found={"table": (100, 100, 700, 500)})).run("oak", photo, 256)
    with ThreadPoolExecutor(2) as ex:
        zips = list(ex.map(lambda _: export_material(mat, 256, "png", tmp_path / "materials"), range(2)))
    assert zips[0] != zips[1] and all(z.exists() and z.stat().st_size > 0 for z in zips)
    assert zips[0].name == zips[1].name  # same download name


def test_chat_json_retries_an_empty_answer_with_a_larger_budget():
    from matterlift_api.meta_client import MetaClient

    client = MetaClient.__new__(MetaClient)  # no network: _complete is replaced
    budgets = []

    def complete(system, user, images, max_tokens, json_mode):
        budgets.append(max_tokens)
        return ("", "length") if len(budgets) == 1 else ('{"materials": []}', "stop")

    client._complete = complete
    assert client.chat_json("s", "u") == {"materials": []}
    assert budgets == [6000, 18000]

    client._complete = lambda *a, **k: ("", "length")
    with pytest.raises(RuntimeError, match="answer was empty, stop: length"):
        client.chat_json("s", "u")


class _Recorder(FakeClient):
    """Keeps what Spark was asked, to check the prompt."""

    def chat_json(self, system, user, images=None):
        self.asked = user
        return super().chat_json(system, user, images)


@pytest.mark.parametrize("request_text, words", [(SUBJECT_REQUEST, False), ("le papier froissé", True)])
def test_spark_reads_the_framing_when_the_request_names_no_surface(tmp_path, request_text, words):
    """No words: Spark is told the user framed the photo on what they want, and that the table under
    it is context (a receipt on a glass table once gave glass). Named surface: it wins."""
    client = _Recorder(plan={**PLAN, "subject": "crumpled receipt",
                             "subject_reason": "centred and in focus; the glass table is what it lies on"})
    und = Pipeline(client, tmp_path / "m", tmp_path / "u").understand(request_text, Image.new("RGB", (64, 64)))
    assert "composition" in client.asked and "context, not the subject" in client.asked
    assert ("le papier froissé" in client.asked) == words
    assert ("Request: none" in client.asked) == (not words)
    assert und.plan.subject == "crumpled receipt" and "glass table" in und.plan.subject_reason


def test_photo_without_words_asks_for_the_subject(monkeypatch):
    from fastapi.testclient import TestClient

    from matterlift_api import main

    class Stub:
        client = None

        def understand(self, request, img):
            self.request = request
            raise RuntimeError("stop here")

    stub = Stub()
    monkeypatch.setattr(main, "_pipeline", stub)
    buf = io.BytesIO()
    Image.new("RGB", (32, 32)).save(buf, "PNG")
    r = TestClient(main.app).post("/understand", files={"photo": ("p.png", buf.getvalue(), "image/png")})
    assert r.status_code == 502 and stub.request == SUBJECT_REQUEST
