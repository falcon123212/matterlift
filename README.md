# MatterLift

**Point at anything. Say what you want. Get a game-ready material.**

The open-source alternative to Substance Sampler: show a real object, say what you want, get a
tileable PBR material (albedo, normal, height, AO, roughness, metallic, ORM) ready for Godot,
Blender, Unity or Unreal.

All code in this repository was written from 2026-11-01 onward, for the Meta hackathon
(Build for Your World, Indie Developer track). The Git history is the proof.

## How it works

```
photo + voice/text
  -> Muse Voice Transcribe   (voice -> text)
  -> Muse Spark              (reads request + photo: material plan as JSON, what SAM should look for)
  -> SAM 3.1                 (finds the surface in the photo: box)
  -> crop                    (square sample inside the box)
  -> Muse Image              (sample -> flat, delit, top-down albedo; or text -> albedo without a photo)
  -> pbrforge                (period crop, seamless wrap, delight, singleton taming)
  -> Muse Image              (albedo -> height map, aligned with it)
  -> pbrforge                (normal, AO, roughness, metallic, ORM at 512 to 4K)
  -> preview (Three.js) and export
```

| Model | Role |
|---|---|
| Muse Spark | Plans the material (roughness, metal, relief, shading model), names the surface for SAM |
| SAM 3.1 | Locates the surface in the photo |
| Muse Image | Paints the albedo from the photo sample or the text; paints the height map from the albedo |
| Muse Voice Transcribe | Spoken requests |

### pbrforge (pure numpy/scipy, no network)

What it fixes in raw Muse Image output, measured by `pbrforge.metrics`:

| Defect | Fix | Example (flagstone) |
|---|---|---|
| Muse returns a 1600 px image that repeats itself 2x2 (square blocks when tiled) | autocorrelation finds the period, keep one | period 800 found, cropped |
| Visible seams when tiled | Moisan periodic component (low-frequency mismatch) + Efros-Freeman minimum-error cut (structure) | seam score 1.49 -> 1.05 |
| Baked lighting, out-of-range albedo | delight (FFT low-pass gain) + PBR range fit | 1.9 % -> 0 % out of range |
| One standout feature that forms a grid when tiled | salient-blob detection, pulled toward the local colour | 6.6 % -> 2.6 % of the tile |
| Crinkled relief from luminance | height painted by Muse Image, low-frequency weighted bands, automatic joint polarity | see benchmark |

Benchmark against a reference material (ambientCG Bricks113A, derived from its Color map only,
`scripts/bench_baseline.py`):

| | luminance only (first version) | MatterLift |
|---|---|---|
| height vs reference displacement (r) | -0.24 | **0.71** |
| AO vs reference AO (r) | -0.07 | **0.65** |
| normal mean angular error | 19.4 deg | **7.5 deg** (flat normal: 8.0) |

## Run it

```bash
py -3.12 -m venv .venv && .venv/Scripts/python -m pip install -e .[dev]
cp .env.example .env   # add META_API_KEY
.venv/Scripts/python scripts/smoke_meta.py
.venv/Scripts/python -m uvicorn matterlift_api.main:app --app-dir api --port 8000
npm --prefix web install && npm --prefix web run dev   # http://localhost:5173
```

API: `POST /materials` (form: `text`, optional `photo`, `audio`, `size`), `GET /materials/{id}`,
`GET /materials/{id}/maps/{name}.png`.

Scripts: `smoke_meta.py` (every model answers), `gate_muse.py` (3 materials, raw vs MatterLift
contact sheet), `sam_table.py` (photo chain), `bench_baseline.py` (against a reference material).

## Meta Model API notes (observed 2026-11-01)

- Base URL `https://api.meta.ai/v1`, OpenAI-compatible. Model ids: `muse-spark-1.3`,
  `muse-image-1.0`, `sam-3.1`, `muse-voice-transcribe-1.0`.
- Spark is a reasoning model: give it `max_completion_tokens` in the thousands or `content` is empty.
- Muse Image returns 1600x1600 WebP whatever `size` says; `/images/edits` has no `mask` field.
- SAM 3.1 answers on `/responses` only, as text: `<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..|>` per
  instance, then an entropy-coded mask we do not decode (boxes are enough for sampling).

## License

MIT
