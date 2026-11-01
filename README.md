# MatterLift

**Point at anything. Say what you want. Get a game-ready material.**

The open-source alternative to Substance Sampler: show a real object, say what you want, get a
tileable PBR material (albedo, normal, height, AO, roughness, metallic, ORM) ready for Godot,
Blender, Unity or Unreal.

All code in this repository was written from 2026-11-01 onward, for the Meta hackathon
(Build for Your World, Indie Developer track). The Git history is the proof.

## How it works

With a photo, MatterLift works in two steps so you see what it understood before it paints:

1. **Understand** (~13 s for one material, ~30 s for a room): Spark reads the request and the
   photo, SAM 3.1 masks the surface, and the UI shows the photo with the mask, the square that
   will be sampled and Spark's description.
2. **Generate** (~25 s per material, in parallel for a room): Muse Image and pbrforge.

**Nothing fails alone.** Each step falls back to the next instead of stopping the run
(`api/matterlift_api/locate.py`, tested offline with failure injection in `tests/test_resilience.py`):

| If… | then… |
|---|---|
| the photo is a phone shot | EXIF rotation applied, resized to 2048 px; a non-image gets a clear 400 |
| Spark's plan has a wrong type or value | that field takes its default, numbers are clamped; invalid JSON is retried once |
| SAM finds nothing for Spark's name | Spark's alternative names, then Spark's points as a SAM prompt, then a sample around the points |
| the surface still cannot be located | the material is painted from Spark's description (and the UI says so) |
| Muse fails on the samples | Muse paints from the description |
| Muse fails on the height map | height from luminance |
| the Meta API answers 429/5xx or drops | up to two retries with backoff |
| anything else goes wrong | a readable error message, never a bare 500; one failed material never sinks a library |

**Samples** (`api/matterlift_api/sampling.py`): the largest rectangle inside the mask (aspect up to
3:1, so a countertop strip still gives a clean sample), then up to two more away from it (a floor
half hidden by furniture is better described by several samples). Muse gets all of them and is
told to keep the pattern scale of the first: the kitchen's octagonal floor tiles stay octagons.

**Preview passes (AOVs)**: Beauty, Depth, Normal, Albedo, Roughness, AO, with the height map as real
displacement on the mesh (so the depth pass shows the relief), and Save PNG for the current pass.

**Library mode**: one photo of a room gives every material in it. Spark lists up to 8 materials
with two points on each; SAM masks each from its noun phrase (one concept per request, all in
parallel), Spark's points pick the right instance; then every sample is generated in parallel.
On a kitchen photo: 7 of 8 materials in 81 s. (Point prompts can segment 16 objects in one SAM
pass, but a point selects an object, one brick rather than the wall, so concept prompts win.)

```
photo + voice/text
  -> Muse Voice Transcribe   (voice -> text)
  -> Muse Spark              (reads request + photo: material plan as JSON, what SAM should look for)
  -> SAM 3.1                 (masks the surface in the photo)
  -> samples                 (up to 3 rectangles inside the mask: objects lying on it are avoided)
  -> Muse Image              (sample -> flat, delit, top-down albedo; or text -> albedo without a photo)
  -> pbrforge                (period crop, seamless wrap, delight, singleton taming)
  -> Muse Image              (albedo -> height map, aligned with it)
  -> pbrforge                (normal, AO, roughness, metallic, ORM at 512 to 4K)
  -> preview (Three.js) and export
```

| Model | Role |
|---|---|
| Muse Spark | Plans the material (roughness, metal, relief, shading model), names the surface for SAM |
| SAM 3.1 | Masks the surface in the photo, so the samples avoid what lies on it |
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
| normal structure (r of X/Y components) | 0.12 | **0.50** (true displacement: 0.97) |
| normal fine detail vs reference | 0.34 (faces read smooth) | **0.80** |

Normals are built like a studio would: macro relief from Muse's height, micro detail (pores,
chisel marks, grain) from the albedo's fine band, which is exactly aligned with the colour, blended
with Reoriented Normal Mapping. Mean angular error is not the target: a flat normal map scores
8.0 deg on it, so it rewards smooth faces. Muse painting the normal map directly was tried and is
worse (r 0.34, wrong neutral colour).

**Spark critique** (`api/matterlift_api/critique.py`, `POST /materials/{id}/critique`, run
automatically after each generation). Spark reviews the material like a senior material artist: a
sphere under raking light, the 3x3 tiling and the photo sample. It scores it, lists what is wrong
and fixes it with the right tool: parameters (relief, roughness, wear, detail) are re-derived at
once, colour is matched to the photo deterministically, and only faults in the colour texture
itself (baked shadows, a standout feature, seams) go back to Muse for a repaint. Spark then compares
before and after side by side and the better one is kept. Live: walnut 4 -> 6, worn parquet 5 -> 7
(wear and detail raised, no new image), hammered copper 3 -> 6.

Lessons that shaped it: asked to judge a 3x3 tiling, Spark flags the repetition of the tile itself,
so the prompt says it is expected; two separate scores were too noisy (+-1), one A/B comparison is
steadier; and the word "tileable" in a repaint makes Muse lay copies side by side with visible
joins, which pbrforge now detects (evenly spaced joins and near-identical cells) and crops.

**Detail layer** (`pbrforge/detail.py`). What a studio adds on top of a scan: a procedural micro
relief (wood fibres and pores, stone grit and pits, fabric fuzz, brushed metal with scratches, plaster
sand), periodic so it tiles, repeated 8 times per texture and computed at the export resolution, so
a 4K export gets real 4K micro detail although Muse paints 1600 px. Blended into the normal with RNM
and into roughness. Wood fibres and metal brushing follow the local grain (structure tensor on the
albedo), so a parquet's vertical and horizontal boards each get fibres along their length. Plus edge wear: convex rims lighter and smoother, recesses darker and rougher.
Spark picks `detail_kind`, `detail_strength` and `wear` from the request ("vieux parquet très usé"
-> wood, 0.6, wear 0.85); the kind is inferred from the name when it does not say.

**Triplanar preview.** A Triplanar toggle projects every map along the world axes (whiteout blend
for normals): no UVs needed, no stretching at the sphere's poles, the same scale as the UVs.

**Colour fidelity.** Muse repaints the sample, so colours drift (a dusty terracotta comes back bright
orange). The albedo is matched to the delit photo samples in CIELAB, hue fully and lightness at 60%
(a sample in shadow says little about the true value). Delta E between mean colours, kitchen
materials: oak 10.7 -> 1.7, floor 37.1 -> 7.4, brick 13.9 -> 4.5. The UI shows sample and albedo
side by side with that score.

## Run it

```bash
py -3.12 -m venv .venv && .venv/Scripts/python -m pip install -e .[dev]
cp .env.example .env   # add META_API_KEY
.venv/Scripts/python scripts/smoke_meta.py
.venv/Scripts/python -m uvicorn matterlift_api.main:app --app-dir api --port 8001
npm --prefix web install && npm --prefix web run dev   # http://localhost:5173
```

API:
- `POST /understand` (form: `photo`, optional `text`, `audio`): step 1, returns the plan, overlay and sample.
- `POST /materials` (form: `understanding` id, or `text`/`audio` with optional `photo`; `size`): a material.
- `POST /libraries` (form: `photo`, optional `text`, `audio`): library step 1; then
  `POST /libraries/{id}/build` (form: `size`) generates every material.
- `GET /materials/{id}`, `/materials/{id}/maps/{name}.png`, `/materials/{id}/export?size=2048&fmt=png`,
  `GET /libraries/{id}`. The UI reopens them with `?id=` or `?lib=`.

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
contact sheet), `sam_table.py` (photo chain), `library_sheet.py` (a library's masks and spheres),
`bench_baseline.py` (against a reference material).

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
