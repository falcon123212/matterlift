"""MatterLift API on Modal. Deploy: modal deploy deploy/modal_app.py

The Meta key comes from the local .env at deploy time (never baked into the image).
Generated materials live on a Modal Volume, so they survive the container going to sleep.
"""
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = "/root/app"  # the API finds data/ two levels above api/matterlift_api

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("numpy", "scipy", "pillow", "fastapi", "uvicorn", "python-multipart",
                 "openai", "httpx", "python-dotenv", "pydantic")
    .env({"PYTHONPATH": f"{APP_DIR}:{APP_DIR}/api"})
    .add_local_dir(ROOT / "pbrforge", f"{APP_DIR}/pbrforge", ignore=["__pycache__"])
    .add_local_dir(ROOT / "api", f"{APP_DIR}/api", ignore=["__pycache__"])
)

data = modal.Volume.from_name("matterlift-data", create_if_missing=True)
app = modal.App("matterlift", image=image)


# One container: every request sees the materials the previous ones wrote.
@app.function(
    secrets=[modal.Secret.from_dotenv(ROOT)],
    volumes={f"{APP_DIR}/data": data},
    cpu=4, memory=4096, timeout=900, max_containers=1, scaledown_window=600,
)
@modal.concurrent(max_inputs=8)
@modal.asgi_app()
def api():
    from matterlift_api.main import app as fastapi_app
    return fastapi_app
