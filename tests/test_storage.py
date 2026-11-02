"""Saved work mirrored to Vercel Blob (the Vercel deployment), against an in-memory store with the
SDK's functions: a fresh instance gets every file back, a re-save sends only what changed, a newer
save on another instance wins, old folders are purged, and the API redirects images and exports to
Blob instead of answering over a function's 4.5 MB limit. On a PC nothing of this runs."""
import io
import json
import shutil
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from matterlift_api import storage


class FakeBlob:
    """vercel.blob.sync, in memory: put_blob, get_blob, query_blobs, delete_blob."""

    def __init__(self):
        self.store: dict[str, bytes] = {}
        self.puts: list[str] = []

    def _url(self, pathname):
        return f"https://store.public.blob.vercel-storage.com/{pathname}"

    def put_blob(self, pathname, body, *, access, allow_overwrite=False, content_type=None, cache_control_max_age=None):
        assert access == "public"
        self.store[pathname] = bytes(body)
        self.puts.append(pathname)
        return SimpleNamespace(url=self._url(pathname), download_url=self._url(pathname) + "?download=1", pathname=pathname)

    def get_blob(self, url_or_pathname, *, access):
        path = url_or_pathname.split(".vercel-storage.com/")[-1]
        return SimpleNamespace(body=self.store[path])

    def query_blobs(self, *, prefix=None):
        for p in sorted(self.store):
            if p.startswith(prefix or ""):
                yield SimpleNamespace(pathname=p, url=self._url(p))

    def delete_blob(self, targets):
        for t in [targets] if isinstance(targets, str) else targets:
            self.store.pop(t.split(".vercel-storage.com/")[-1], None)


@pytest.fixture
def blob(tmp_path, monkeypatch):
    fake = FakeBlob()
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "test")
    monkeypatch.setattr(storage, "_blob", fake)
    monkeypatch.setattr(storage, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(storage, "_checked", {})
    return fake


def _folder(root, name="materials/abc", files=None):
    d = root / name
    d.mkdir(parents=True)
    for n, data in (files or {"material.json": b'{"v": 1}', "albedo.png": b"PNG1", "normal.png": b"PNG2"}).items():
        (d / n).write_bytes(data)
    return d


def _new_instance(folder):
    """Another Vercel instance: an empty /tmp, nothing checked yet."""
    shutil.rmtree(folder)
    storage._checked.clear()


def test_a_fresh_instance_gets_every_file_back(blob, tmp_path):
    d = _folder(tmp_path)
    storage.push(d)
    assert any("/manifest-" in p for p in blob.store)
    _new_instance(d)
    assert storage.pull(d)
    assert (d / "material.json").read_bytes() == b'{"v": 1}' and (d / "albedo.png").read_bytes() == b"PNG1"


def test_files_are_immutable_and_a_resave_sends_only_what_changed(blob, tmp_path):
    d = _folder(tmp_path)
    storage.push(d)
    (d / "material.json").write_bytes(b'{"v": 2}')  # the critique rewrites it
    blob.puts.clear()
    storage.push(d)
    sent = [p for p in blob.puts if "/manifest-" not in p]
    assert len(sent) == 1 and sent[0].startswith("materials/abc/material.") and sent[0].endswith(".json")
    # the old version is still there under its own name: a CDN copy of it is never wrong
    assert sum(p.startswith("materials/abc/material.") for p in blob.store) == 2


def test_the_newest_save_wins_across_instances(blob, tmp_path):
    d = _folder(tmp_path)
    storage.push(d)
    (d / "material.json").write_bytes(b'{"v": 2}')
    storage.push(d)
    _new_instance(d)
    storage.pull(d)
    assert json.loads((d / "material.json").read_text()) == {"v": 2}


def test_a_folder_that_exists_nowhere_is_not_found(blob, tmp_path):
    assert storage.pull(tmp_path / "materials" / "missing") is False


def test_old_folders_are_purged(blob, tmp_path, monkeypatch):
    monkeypatch.setitem(storage.KEEP, "materials", 2)
    for k in range(4):
        storage.push(_folder(tmp_path, f"materials/m{k}"))
    kept = {p.split("/")[1] for p in blob.store}
    assert kept == {"m2", "m3"}  # the newest two
    assert not (tmp_path / "materials" / "m0").exists()


def test_nothing_happens_without_a_store(tmp_path, monkeypatch):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    monkeypatch.delenv("BLOB_STORE_ID", raising=False)
    monkeypatch.setattr(storage, "_blob", None)
    d = _folder(tmp_path)
    storage.push(d)  # no SDK call: _blob would be imported
    assert storage._blob is None and storage.pull(d) is True


def test_the_api_redirects_images_and_exports_to_blob(blob, tmp_path, monkeypatch):
    from matterlift_api import main
    from matterlift_api.schemas import Material, MaterialPlan

    mats = tmp_path / "materials"
    monkeypatch.setattr(main, "DATA_DIR", mats)
    d = mats / "abc"
    d.mkdir(parents=True)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, "PNG")
    (d / "albedo.png").write_bytes(buf.getvalue())
    mat = Material(id="abc", plan=MaterialPlan(name="test"), request="t", source="text", size=512,
                   maps={}, scores={}, timings={})
    (d / "material.json").write_text(mat.model_dump_json())
    storage.push(d)
    _new_instance(d)

    c = TestClient(main.app, follow_redirects=False)
    r = c.get("/materials/abc/maps/albedo.png")
    assert r.status_code == 307 and r.headers["location"].startswith("https://store.public.blob.vercel-storage.com/materials/abc/albedo.")
    assert c.get("/materials/abc/maps/nothing.png").status_code == 404

    zip_path = tmp_path / "out" / "Test_512-PNG.zip"
    zip_path.parent.mkdir()
    zip_path.write_bytes(b"PK zip")
    monkeypatch.setattr(main, "load_material", lambda mid: mat)
    monkeypatch.setattr(main, "export_material", lambda m, size, fmt: zip_path)
    r = c.get("/materials/abc/export", params={"size": 512})
    assert r.status_code == 307 and "exports/" in r.headers["location"] and r.headers["location"].endswith("?download=1")
    assert not zip_path.parent.exists()  # the local copy is gone once uploaded


def test_sizes_follow_the_deployment(monkeypatch):
    from matterlift_api import main
    assert main.health()["max_size"] == storage.MAX_SIZE
    assert max(main.SIZES) == storage.MAX_SIZE
