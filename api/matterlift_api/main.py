"""MatterLift API. Run: uvicorn matterlift_api.main:app --app-dir api --reload"""
from __future__ import annotations

import io
import re

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from PIL import Image

from .library import LIBRARY_DIR, build_library, load_library, understand_library
from .pipeline import (DATA_DIR, UNDERSTAND_DIR, Pipeline, export_material, load_material,
                       load_understanding)
from .schemas import Library, Material, Understanding

app = FastAPI(title="MatterLift")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_pipeline: Pipeline | None = None
_SAFE = re.compile(r"^[A-Za-z0-9_]+$")

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


async def _photo(photo: UploadFile) -> Image.Image:
    try:
        return Image.open(io.BytesIO(await photo.read())).convert("RGB")
    except OSError as e:
        raise HTTPException(400, "photo is not a readable image") from e


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
    if not _SAFE.match(uid) or name not in ("overlay.jpg", "crop.png", "photo.jpg"):
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
    if not (_SAFE.match(lid) and re.fullmatch(r"photo\.jpg|overlay\.jpg|crop_\d+\.png", name)):
        raise HTTPException(404)
    path = LIBRARY_DIR / lid / name
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)
