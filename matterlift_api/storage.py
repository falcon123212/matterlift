"""Where saved work lives between requests.

On a machine with a disk (a PC, a server) that is the data folder, and nothing in this module does
anything. On Vercel each request may run on a fresh instance whose /tmp is empty, so every folder a
step saves (a material, an understanding, a library) is mirrored to Vercel Blob, and a step that
needs a folder pulls it back first.

Blob layout, made for a CDN that may keep a rewritten file for a minute: each file is stored once
under its content hash, so it never changes; each save writes a new `<folder>/manifest-<time>.json`
naming the folder's current files, and the latest manifest is the folder's state. Old folders and
exports are purged to stay within the free plan (1 GB).
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import threading
import time
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[1]
ON_VERCEL = bool(os.environ.get("VERCEL"))
# Vercel can only write to /tmp
DATA_ROOT = Path(os.environ.get("MATTERLIFT_DATA") or ("/tmp/matterlift" if ON_VERCEL else REPO / "data"))
# A 4K material or export needs ~2.5 GB of memory; Vercel's free plan gives functions 2 GB.
MAX_SIZE = int(os.environ.get("MATTERLIFT_MAX_SIZE") or (2048 if ON_VERCEL else 4096))
KEEP = {"materials": 40, "understand": 40, "libraries": 15}  # folders kept in Blob, newest first
EXPORT_TTL = 3600  # seconds an export zip stays downloadable
FRESH = 15  # seconds a folder pulled from Blob is trusted before checking for a newer save

LOCAL_MANIFEST = ".manifest.json"
_lock = threading.Lock()
_checked: dict[str, float] = {}  # folder key -> when its latest manifest was last looked up
_blob = None


def remote() -> bool:
    """Blob is used when the project has a store (Vercel sets these when one is connected)."""
    if os.environ.get("MATTERLIFT_STORAGE") == "local":
        return False
    return bool(os.environ.get("BLOB_STORE_ID") or os.environ.get("BLOB_READ_WRITE_TOKEN"))


def _api():
    global _blob
    if _blob is None:
        from vercel.blob import sync as blob  # only needed with a store
        _blob = blob
    return _blob


def _key(folder: Path) -> str:
    """`materials/<id>`: the folder's place under the data root (or its last two parts elsewhere)."""
    try:
        return folder.resolve().relative_to(DATA_ROOT.resolve()).as_posix()
    except ValueError:
        return "/".join(folder.parts[-2:])


def _files(folder: Path) -> dict[str, Path]:
    """Files to mirror: everything but the local manifest and transient exports."""
    return {p.relative_to(folder).as_posix(): p for p in sorted(folder.rglob("*"))
            if p.is_file() and p.name != LOCAL_MANIFEST and "export" not in p.relative_to(folder).parts}


def _local_manifest(folder: Path) -> dict:
    p = folder / LOCAL_MANIFEST
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"id": None, "files": {}}


def _put(pathname: str, data: bytes, **kw):
    return _api().put_blob(pathname, data, access="public", allow_overwrite=True,
                           content_type=mimetypes.guess_type(pathname)[0] or "application/octet-stream", **kw)


def push(folder: Path) -> None:
    """After a step saved `folder`: upload its new or changed files and a manifest naming them all."""
    if not remote():
        return
    key = _key(folder)
    with _lock:
        known = _local_manifest(folder)["files"]
        files = {}
        for name, path in _files(folder).items():
            data = path.read_bytes()
            digest = hashlib.sha1(data).hexdigest()[:16]
            entry = known.get(name)
            if not entry or entry["hash"] != digest:
                p = PurePosixPath(name)  # albedo.png -> albedo.<hash>.png: new content, new name
                put = _put(f"{key}/{p.with_name(f'{p.stem}.{digest}{p.suffix}')}", data)
                entry = {"hash": digest, "url": put.url}
            files[name] = entry
        mid = f"{key}/manifest-{time.time_ns():020d}.json"
        _put(mid, json.dumps(files).encode(), cache_control_max_age=31536000)
        (folder / LOCAL_MANIFEST).write_text(json.dumps({"id": mid, "files": files}), encoding="utf-8")
        _checked[key] = time.monotonic()
    _purge(key.split("/")[0])


def _latest_manifest(key: str) -> str | None:
    names = [b.pathname for b in _api().query_blobs(prefix=f"{key}/manifest-")]
    return max(names) if names else None


def pull(folder: Path, fresh: bool = True) -> bool:
    """Before a step reads `folder`: make the local copy current. False when it exists nowhere.
    `fresh=False` trusts any local copy (for files that never change once written)."""
    if not remote():
        return folder.exists()
    key = _key(folder)
    with _lock:
        local = _local_manifest(folder)
        if local["id"] and (not fresh or time.monotonic() - _checked.get(key, -FRESH) < FRESH):
            return True
        latest = _latest_manifest(key)
        _checked[key] = time.monotonic()
        if latest is None:
            return folder.exists()
        if latest == local["id"]:
            return True
        api = _api()
        files = json.loads(api.get_blob(latest, access="public").body)
        folder.mkdir(parents=True, exist_ok=True)
        for name, entry in files.items():
            target = folder / name
            if local["files"].get(name, {}).get("hash") == entry["hash"] and target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(api.get_blob(entry["url"], access="public").body)
        (folder / LOCAL_MANIFEST).write_text(json.dumps({"id": latest, "files": files}), encoding="utf-8")
        return True


def url(folder: Path, name: str) -> str | None:
    """Public Blob URL of a saved file (images are served from Blob, not through the function)."""
    if not pull(folder, fresh=False):
        return None
    entry = _local_manifest(folder)["files"].get(name)
    return entry["url"] if entry else None


def publish_export(zip_path: Path) -> str:
    """A finished export zip: upload it and return the URL that downloads it."""
    put = _put(f"exports/{time.time_ns():020d}/{zip_path.name}", zip_path.read_bytes())
    _purge_exports()
    return put.download_url


def _purge(kind: str) -> None:
    """Keep the newest KEEP[kind] folders of that kind in Blob; delete the rest (deletes are free)."""
    keep = KEEP.get(kind)
    if not keep:
        return
    latest: dict[str, str] = {}
    blobs: dict[str, list[str]] = {}
    for b in _api().query_blobs(prefix=f"{kind}/"):
        folder = "/".join(b.pathname.split("/")[:2])
        blobs.setdefault(folder, []).append(b.url)
        if "/manifest-" in b.pathname:
            latest[folder] = max(latest.get(folder, ""), b.pathname.rsplit("/manifest-", 1)[1])
    old = sorted(blobs, key=lambda f: latest.get(f, ""), reverse=True)[keep:]
    doomed = [u for f in old for u in blobs[f]]
    for i in range(0, len(doomed), 1000):
        _api().delete_blob(doomed[i:i + 1000])
    for f in old:  # the local copy too
        shutil.rmtree(DATA_ROOT / f, ignore_errors=True)


def _purge_exports() -> None:
    cutoff = time.time_ns() - EXPORT_TTL * 1_000_000_000
    old = [b.url for b in _api().query_blobs(prefix="exports/")
           if int(b.pathname.split("/")[1]) < cutoff]
    if old:
        _api().delete_blob(old[:1000])
