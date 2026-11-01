"""MatterLift API. Run: uvicorn matterlift_api.main:app --app-dir api --reload"""
from __future__ import annotations

import io
import re

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from PIL import Image

from .pipeline import DATA_DIR, Pipeline, export_material, load_material
from .schemas import Material

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


@app.post("/materials", response_model=Material)
async def create_material(
    text: str = Form(""),
    size: int = Form(1024),
    photo: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
) -> Material:
    """Text, voice, or both (the transcript is appended to the text)."""
    if size not in (512, 1024, 2048, 4096):
        raise HTTPException(400, "size must be 512, 1024, 2048 or 4096")
    request = text.strip()
    if audio is not None:
        try:
            spoken = await run_in_threadpool(pipeline().client.transcribe, await audio.read(), VOCABULARY)
        except (RuntimeError, ValueError, EOFError) as e:  # wave raises on non-WAV input
            raise HTTPException(502, f"transcription failed: {e}") from e
        request = f"{request} {spoken}".strip()
    if not request:
        raise HTTPException(400, "say or type what you want")
    img = None
    if photo is not None:
        img = Image.open(io.BytesIO(await photo.read())).convert("RGB")
    try:
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
