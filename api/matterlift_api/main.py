"""MatterLift API. Run: uvicorn matterlift_api.main:app --app-dir api --reload"""
from __future__ import annotations

import io
import logging
import re

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image

from .critique import critique_by_id
from .library import LIBRARY_DIR, build_library, load_library, understand_library
from .pipeline import (DATA_DIR, UNDERSTAND_DIR, Pipeline, export_material, load_material,
                       load_understanding, normalize_photo)
from .schemas import Critique, Library, Material, Understanding

app = FastAPI(title="MatterLift")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
log = logging.getLogger("matterlift")


@app.exception_handler(Exception)
async def any_error(request: Request, exc: Exception) -> JSONResponse:
    """Last resort: a readable message instead of a bare 500 page."""
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=502, content={"detail": f"{type(exc).__name__}: {str(exc)[:300]}"})

_pipeline: Pipeline | None = None
_SAFE = re.compile(r"^[A-Za-z0-9_]+$")
MAX_UPLOAD = 30_000_000

# Biases Muse Voice Transcribe toward material vocabulary (it may otherwise mishear these).
VOCABULARY = ["albedo", "roughness", "normal map", "PBR", "tileable", "seamless", "moss", "mousse",
              "rust", "rouille", "oak", "chêne", "walnut", "noyer", "flagstone", "dalle", "grout",
              "joints", "brick", "brique", "plank", "planche", "weathered", "usé", "patina", "patine"]


def pipeline() -> Pipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = Pipeline()
    return _pipeline


@app.get("/health")
def health() -> dict:
    return {"ok": True}


async def _request_text(text: str, audio: UploadFile | None) -> str:
    """Typed text, plus the transcript of the voice request when there is one."""
    request = text.strip()
    if audio is not None:
        try:
            spoken = await run_in_threadpool(pipeline().client.transcribe, await audio.read(), VOCABULARY)
        except (RuntimeError, ValueError, EOFError) as e:  # wave raises on non-WAV input
            raise HTTPException(502, f"transcription failed: {e}") from e
        request = f"{request} {spoken}".strip()
    return request


@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)) -> dict:
    """Voice request -> text, right after recording, so the user sees and can edit what was heard."""
    text = await _request_text("", audio)
    if not text:
        raise HTTPException(422, "nothing was heard in the recording")
    return {"text": text}


@app.post("/enhance")
async def enhance(text: str = Form(...), photo: UploadFile | None = File(None)) -> dict:
    """Spark turns a short request into a precise material brief (same language), with the photo
    when there is one. The page shows it in the text box, editable, before generating."""
    if not text.strip():
        raise HTTPException(400, "nothing to enrich")
    img = await _photo(photo) if photo is not None else None
    try:
        return {"text": await run_in_threadpool(pipeline().enhance, text.strip(), img), "original": text.strip()}
    except RuntimeError as e:
        raise HTTPException(502, str(e)) from e


async def _photo(photo: UploadFile) -> Image.Image:
    data = await photo.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"photo is over {MAX_UPLOAD // 1_000_000} MB")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:  # not an image, truncated, HEIC without a decoder, decompression bomb
        raise HTTPException(400, f"photo is not a readable image (JPEG, PNG or WebP): {type(e).__name__}") from e
    return normalize_photo(img)


@app.post("/understand", response_model=Understanding)
async def understand(
    photo: UploadFile = File(...),
    text: str = Form(""),
    audio: UploadFile | None = File(None),
) -> Understanding:
    """Step 1 with a photo: what Spark understood and where SAM found it, shown before generation."""
    request = await _request_text(text, audio) or "take the main material of this photo"
    img = await _photo(photo)
    try:
        return await run_in_threadpool(pipeline().understand, request, img)
    except RuntimeError as e:
        raise HTTPException(502, str(e)) from e


@app.get("/understand/{uid}/{name}")
def get_understanding_image(uid: str, name: str) -> FileResponse:
    if not _SAFE.match(uid) or not re.fullmatch(r"overlay\.jpg|photo\.jpg|crop_\d\.png", name):
        raise HTTPException(404)
    path = UNDERSTAND_DIR / uid / name
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


@app.post("/materials", response_model=Material)
async def create_material(
    text: str = Form(""),
    size: int = Form(1024),
    photo: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
    understanding: str = Form(""),
) -> Material:
    """Text, voice, or both; or resume from an understanding (step 2 after /understand)."""
    if size not in (512, 1024, 2048, 4096):
        raise HTTPException(400, "size must be 512, 1024, 2048 or 4096")
    try:
        if understanding:
            und = load_understanding(understanding) if _SAFE.match(understanding) else None
            if und is None:
                raise HTTPException(404, "unknown understanding")
            return await run_in_threadpool(pipeline().run_understood, und, size)
        request = await _request_text(text, audio)
        if not request:
            raise HTTPException(400, "say or type what you want")
        img = await _photo(photo) if photo is not None else None
        return await run_in_threadpool(pipeline().run, request, img, size)
    except RuntimeError as e:
        raise HTTPException(502, str(e)) from e


@app.get("/materials/{mid}", response_model=Material)
def get_material(mid: str) -> Material:
    mat = load_material(mid) if _SAFE.match(mid) else None
    if mat is None:
        raise HTTPException(404)
    return mat


@app.post("/materials/{mid}/critique", response_model=Critique)
async def critique_material(mid: str) -> Critique:
    """Spark reviews the material under raking light, fixes what it finds, and judges the result."""
    if not _SAFE.match(mid):
        raise HTTPException(404)
    try:
        result = await run_in_threadpool(critique_by_id, pipeline(), mid)
    except RuntimeError as e:
        raise HTTPException(502, str(e)) from e
    if result is None:
        raise HTTPException(404)
    return result


@app.get("/materials/{mid}/export")
async def export(mid: str, size: int = 1024, fmt: str = "png") -> FileResponse:
    """ambientCG-style zip: Color, NormalGL/DX, Roughness, AO, Displacement (+ Metalness),
    Godot .tres, MaterialX .mtlx, USD .usda."""
    mat = load_material(mid) if _SAFE.match(mid) else None
    if mat is None:
        raise HTTPException(404)
    if size not in (512, 1024, 2048, 4096) or fmt not in ("png", "jpg"):
        raise HTTPException(400, "size in 512/1024/2048/4096, fmt in png/jpg")
    path = await run_in_threadpool(export_material, mat, size, fmt)
    return FileResponse(path, media_type="application/zip", filename=path.name)


@app.get("/materials/{mid}/maps/{name}.png")
def get_map(mid: str, name: str) -> FileResponse:
    if not (_SAFE.match(mid) and _SAFE.match(name)):
        raise HTTPException(404)
    path = DATA_DIR / mid / f"{name}.png"
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/png")


@app.post("/libraries", response_model=Library)
async def create_library(
    photo: UploadFile = File(...),
    text: str = Form(""),
    audio: UploadFile | None = File(None),
) -> Library:
    """Library step 1: Spark lists the materials, SAM masks each one; returns the overlay and
    samples to show, before /libraries/{id}/build generates them."""
    request = await _request_text(text, audio)
    img = await _photo(photo)
    try:
        return await run_in_threadpool(understand_library, pipeline(), img, request)
    except RuntimeError as e:
        raise HTTPException(502, str(e)) from e


@app.post("/libraries/{lid}/build", response_model=Library)
async def build(lid: str, size: int = Form(1024)) -> Library:
    """Library step 2: Muse Image + pbrforge for every sample, in parallel."""
    lib = load_library(lid) if _SAFE.match(lid) else None
    if lib is None:
        raise HTTPException(404)
    if size not in (512, 1024, 2048):
        raise HTTPException(400, "size must be 512, 1024 or 2048")
    return await run_in_threadpool(build_library, pipeline(), lib, size)


@app.get("/libraries/{lid}", response_model=Library)
def get_library(lid: str) -> Library:
    lib = load_library(lid) if _SAFE.match(lid) else None
    if lib is None:
        raise HTTPException(404)
    return lib


@app.get("/libraries/{lid}/{name}")
def get_library_image(lid: str, name: str) -> FileResponse:
    if not (_SAFE.match(lid) and re.fullmatch(r"photo\.jpg|overlay\.jpg|crop_\d+_\d\.png", name)):
        raise HTTPException(404)
    path = LIBRARY_DIR / lid / name
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)
