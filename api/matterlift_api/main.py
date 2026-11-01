"""MatterLift API. Run: uvicorn matterlift_api.main:app --app-dir api --reload"""
from __future__ import annotations

import io
import re

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from PIL import Image

from .pipeline import DATA_DIR, Pipeline, load_material
from .schemas import Material

app = FastAPI(title="MatterLift")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_pipeline: Pipeline | None = None
_SAFE = re.compile(r"^[A-Za-z0-9_]+$")


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
    text: str = Form(...),
    size: int = Form(1024),
    photo: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
) -> Material:
    if size not in (512, 1024, 2048, 4096):
        raise HTTPException(400, "size must be 512, 1024, 2048 or 4096")
    request = text
    if audio is not None:
        spoken = await run_in_threadpool(pipeline().client.transcribe, await audio.read(), audio.filename or "audio.webm")
        request = f"{text} {spoken}".strip()
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


@app.get("/materials/{mid}/maps/{name}.png")
def get_map(mid: str, name: str) -> FileResponse:
    if not (_SAFE.match(mid) and _SAFE.match(name)):
        raise HTTPException(404)
    path = DATA_DIR / mid / f"{name}.png"
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/png")
