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
  -> SAM 3.1                 (masks the surface in the photo)
  -> crop                    (largest square inside the mask: objects lying on it are avoided)
  -> Muse Image              (sample -> flat, delit, top-down albedo; or text -> albedo without a photo)
  -> pbrforge                (period crop, seamless wrap, delight, singleton taming)
  -> Muse Image              (albedo -> height map, aligned with it)
  -> pbrforge                (normal, AO, roughness, metallic, ORM at 512 to 4K)
  -> preview (Three.js) and export
```

| Model | Role |
|---|---|
| Muse Spark | Plans the material (roughness, metal, relief, shading model), names the surface for SAM |
| SAM 3.1 | Masks the surface in the photo, so the sample avoids what lies on it |
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
.venv/Scripts/python -m uvicorn matterlift_api.main:app --app-dir api --port 8001
npm --prefix web install && npm --prefix web run dev   # http://localhost:5173
```

API: `POST /materials` (form: `text`, optional `photo`, `audio`, `size`), `GET /materials/{id}`,
`GET /materials/{id}/maps/{name}.png`, `GET /materials/{id}/export?size=2048&fmt=png`.

## Export

Same layout as an ambientCG package (checked against Bricks113A_4K-JPG), recomputed at the
requested resolution (512 to 4K) from the clean albedo and the Muse height:

```
RustyPaintedSteel_2K-PNG/
  RustyPaintedSteel_2K-PNG_Color.png          sRGB albedo
  RustyPaintedSteel_2K-PNG_NormalGL.png       OpenGL normal (Godot, Blender, Unity)
  RustyPaintedSteel_2K-PNG_NormalDX.png       DirectX normal (Unreal)
  RustyPaintedSteel_2K-PNG_Roughness.png
  RustyPaintedSteel_2K-PNG_AmbientOcclusion.png
  RustyPaintedSteel_2K-PNG_Displacement.png   16-bit PNG
  RustyPaintedSteel_2K-PNG_Metalness.png      only when the material has metal
  RustyPaintedSteel_2K-PNG.tres               Godot 4 StandardMaterial3D
  RustyPaintedSteel_2K-PNG.mtlx               MaterialX OpenPBR
  RustyPaintedSteel_2K-PNG.usda               USD UsdPreviewSurface
  RustyPaintedSteel.png                       preview sphere
```

Verified: Godot 4.7.2 loads the `.tres` with every map resolved, next to the reference package.

Scripts: `smoke_meta.py` (every model answers), `gate_muse.py` (3 materials, raw vs MatterLift
contact sheet), `sam_table.py` (photo chain), `bench_baseline.py` (against a reference material).

## Meta Model API notes (docs: https://dev.meta.ai/docs)

- Base URL `https://api.meta.ai/v1`, OpenAI-compatible. Model ids: `muse-spark-1.3`,
  `muse-image-1.0`, `sam-3.1`, `muse-voice-transcribe-1.0`.
- Spark is a reasoning model: give it `max_completion_tokens` in the thousands or `content` is empty.
- Muse Image returns 1600x1600 whatever `size` says (it sets the aspect ratio); `/images/edits` has no
  `mask` field. We ask for PNG and `reasoning_strength: "low"`: twice as fast (~9 s), and it paints a
  unique 1600 px image, where `"high"` repeats one 800 px tile 2x2 (half the usable resolution).
  Height maps are as good in low (r 0.60 vs 0.60 against the reference displacement).
- Muse Voice Transcribe: `POST /v1/asr/transcribe` (not the OpenAI route), multipart `request` (JSON)
  + `audio`, WAV mono 16-bit at 16/24 kHz only. The browser converts its WebM recording to 24 kHz WAV;
  the API normalises any WAV and biases recognition with material vocabulary (`keywords`).
- SAM 3.1 answers on `/responses` only, as text: a box token and a mask token per instance. We
  request `metadata.mask_encoding: "one_bit"` and decode it in `api/matterlift_api/sam_mask.py`, a
  Python port of Meta's `@meta-sam/parser` decoder (adaptive binary range coder, 12-bit context).

## License

MIT
