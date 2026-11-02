<p align="center">
  <img src="docs/img/hero.jpg" alt="MatterLift. Point at anything. Say what you want. Get a game-ready material." width="100%">
</p>

<p align="center">
  <a href="https://matterlift.taurus-silver-dev.workers.dev"><img alt="Open the live demo" src="https://img.shields.io/badge/%E2%96%B6%20%20Live%20demo-open%20MatterLift-d6aa60?style=for-the-badge&labelColor=16171c"></a>
  <a href="#60-second-judge-path"><img alt="60-second judge path" src="https://img.shields.io/badge/60%20s-judge%20path-2b2d35?style=for-the-badge&labelColor=16171c"></a>
  <a href="#gallery"><img alt="Gallery" src="https://img.shields.io/badge/Gallery-12%20materials-2b2d35?style=for-the-badge&labelColor=16171c"></a>
</p>

<p align="center">
  <a href="https://github.com/falcon123212/matterlift/actions/workflows/tests.yml"><img alt="tests" src="https://github.com/falcon123212/matterlift/actions/workflows/tests.yml/badge.svg"></a>
  <img alt="Meta Global AI Hackathon 2026" src="https://img.shields.io/badge/Meta%20Global%20AI%20Hackathon-2026-0866ff">
  <img alt="Muse Spark, SAM 3.1, Muse Image, Muse Voice" src="https://img.shields.io/badge/Meta%20models-Muse%20Spark%20%C2%B7%20SAM%203.1%20%C2%B7%20Muse%20Image%20%C2%B7%20Muse%20Voice-0866ff">
  <img alt="Exports" src="https://img.shields.io/badge/exports-glTF%20%C2%B7%20Godot%204%20%C2%B7%20Blender%20%C2%B7%20MaterialX%20%C2%B7%20USD-555">
  <img alt="MIT license" src="https://img.shields.io/badge/license-MIT-555">
</p>

<p align="center">
  <b><a href="https://matterlift.taurus-silver-dev.workers.dev">Live demo</a></b> ·
  <a href="#gallery">Gallery</a> ·
  <a href="#real-photos-six-objects-from-a-desk">Real photos</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#tests-and-benchmarks">Tests</a> ·
  <a href="#run-it">Run it</a> ·
  Video: coming soon
</p>

<br>

<p align="center">
  <img src="docs/img/orbit_ruby.gif" alt="A ruby material generated from two words, path traced live in the browser on the Stanford dragon" width="560">
  <br>
  <sub><b>"a ruby"</b>: two words, a game-ready material, path traced live in the browser (WebGPU ReSTIR, 256 lights). Not a video render: the page does this.</sub>
</p>

<br>

From a photo or a sentence to a game-ready material: show a real surface, say what you want, get a
tileable PBR material (albedo, normal, height, AO, roughness, metallic, thickness, ORM, glTF) ready
for Godot, Blender, Unity or Unreal. Open source, built on Meta's models (Muse Spark, Muse Image,
SAM 3.1, Muse Voice Transcribe).

<p align="center">
  <img src="docs/img/flow.jpg" alt="You say: very worn, scratched old oak parquet. MatterLift makes colour, normal, roughness, AO and height maps. Path traced in your browser on the Stanford dragon." width="100%">
</p>

<p align="center">
  <img src="docs/img/interface.jpg" alt="MatterLift: very worn, scratched old oak parquet on the sphere, with its maps and the export" width="100%">
  <br>
  <sub>The page: "very worn, scratched old oak parquet" on the sphere, the tiled 3×3 seam check, every map and the export. Spark's review under raking light gave it 8/10 at once, nothing to fix.</sub>
</p>

## Gallery

Six materials made from a sentence alone, on the Stanford dragon: five in **Live RT** (path traced in
the browser, WebGPU), the diamond in the 3D preview. Each one is in [`samples/export/`](samples/export) exactly as **Download .zip**
gives it (512 px PNG): maps, `.glb`, Godot `.tres` and shader, MaterialX, USD, Blender script, all
passing the Khronos glTF validator, MaterialX, USD and Godot 4. Prompts typed in French are shown translated: MatterLift
takes requests in any language Spark reads.

| | | |
|---|---|---|
| ![Ruby](docs/img/live_ruby.jpg) | ![Old oak parquet](docs/img/live_oak_parquet.jpg) | ![Aged limestone blocks](docs/img/live_limestone.jpg) |
| **"a ruby"**: transmission, IOR 1.77, clearcoat, and a thickness map ([export](samples/export/Ruby_512-PNG)) | **"very worn, scratched old oak parquet"** ([export](samples/export/OldWornOakParquet_512-PNG)) | **"Century-old grey-beige weathered limestone, raw matte finish, pores, fine cracks and visible mortar joints…"**: a detailed brief, down to 60×40 cm blocks ([export](samples/export/AgedLimestoneBlocks_512-PNG)) |
| ![Rusty painted steel](docs/img/live_rusty_steel.jpg) | ![Mossy flagstone path](docs/img/live_mossy_flagstone.jpg) | ![Diamond](docs/img/preview_diamond.jpg) |
| **"rusty painted steel plate, orange rust patches with bare grey metal and flaking blue paint"**: metal only where the paint is gone ([export](samples/export/RustyPaintedSteel_512-PNG)) | **"mossy flagstone path, irregular grey stones with green moss in the joints"** ([export](samples/export/MossyFlagstonePath_512-PNG)) | **"a diamond"**: Spark set full transmission and IOR 2.4 by itself. Shown in the 3D preview, since Live RT does not trace transmission yet ([export](samples/export/Diamond_512-PNG)) |

## Why MatterLift

MatterLift is an open-source material and shader extractor: show a photo, say what you want, get a
material ready for Godot, Blender, Unity or Unreal.

- **The problem.** A unique material takes time (roughly 30 min to 2 h per texture, about a day per
  iteration round in pre-production), technical-artist know-how and a paid tool. Free libraries
  give everyone the same materials.
- **For whom.** Indie developers and modders (over 19,000 games released on Steam in 2025
  [[1]](https://www.gamingonlinux.com/2025/12/over-19000-games-have-released-on-steam-in-2025-with-nearly-half-seeing-fewer-than-10-reviews)),
  beginner 3D artists, students; and VFX pre-production teams exploring a look before production.
- **Why now.** Substance 3D Texturing costs US$249.88 a year and the full Collection US$599.88
  [[2]](https://blog.adobe.com/en/publish/2025/02/20/substance-3d-innovations-pricing-updates); in
  France the Collection is €57.47 a month incl. VAT, €95.99 a month per seat for teams
  [[2b]](https://www.adobe.com/fr/products/substance3d/plans.html). Meanwhile an estimated 40% of 2025 Steam
  releases earned less than $100 [[3]](https://mp1st.com/news/40-of-steam-games-in-2025-earned-less-than-100).
  Teams are shrinking: 28% of game workers were laid off in the past two years (GDC 2026 State of
  the Game Industry [[4]](https://gdconf.com/article/gdc-2026-state-of-the-game-industry-reveals-impact-of-layoffs-generative-ai-and-more/)),
  and open-source Godot grew from 0.9% to 7.1% of the releases GameDiscoverCo tracks, 2020 to 2025
  [[5]](https://newsletter.gamediscover.co/p/hows-pc-game-engine-usage-changing).
- **How.** Muse Spark frames the surface and writes the material plan, SAM 3.1 masks it precisely,
  Muse Image paints the tileable texture, Muse Voice Transcribe takes spoken requests. MatterLift
  computes the PBR maps, the shaders, the lit preview and the export, and Spark critiques the
  result itself.
- **Gain.** Time: one iteration takes about 40 s at 512 px (measured on the live demo) instead of
  hours. Money: pay-per-use API calls instead of a subscription. Control: materials taken from your
  own photos, exported in standard formats (glTF, MaterialX, USD, Godot, Blender).

## 60-second judge path

1. **Ask.** Open the [live demo](https://matterlift.taurus-silver-dev.workers.dev), type
   `old oak planks` or press **Speak**, then **✨ Enrich** (Spark fixes and completes the request)
   and **Generate**. About 40 s at 512 px; the first request after a pause also wakes the API.
2. **Look.** Turn the sphere under **Raking** light, check the seams in **Tiling 3×3**, switch the
   passes (Depth, Normal, Albedo, Rough, AO). Try it on the Stanford **Dragon**, **Buddha** or **Lucy**, or
   in **Live RT**: that scan path traced in the browser (WebGPU) with the same material. With a photo, MatterLift
   first shows what it understood: the surface SAM masked and the square it sampled, before
   generating anything.
3. **Use it.** **Download .zip**: ambientCG-style maps, a glTF `.glb`, Godot `.tres` and
   `.gdshader`, MaterialX, USD and a Blender script. Drop the `.glb` into Godot, Blender or any
   glTF viewer.

## Honest scope

MatterLift does not scan the surface the way photogrammetry tools do: Muse Image repaints the photo
sample as a clean, flat, tileable texture, then pbrforge matches its colours back to the photo and
derives the maps. The result is faithful in character and colour (Delta E shown in the UI), not a
pixel-exact capture.

## Real photos: six objects from a desk

Six phone photos (1500×2000, dim desk light) of what was on the desk, sent to the deployed API the
way the page does it: **Understand** with no text at all, **Generate** at
1K, **Spark's critique**, **Download .zip** at 1K (`scripts/photo_test.py`, raw numbers in
[`results/photo_test/`](results/photo_test); the photos themselves are not in the repository, only
the square that was sampled).

Each material in **Live RT** on the dragon, above the square sampled from the photo and the tileable
texture made from it (the version kept after Spark's critique):

| | | |
|---|---|---|
| ![3D-printed cube in Live RT](docs/img/photo_cube_live.jpg) | ![Plush in Live RT](docs/img/photo_plush_live.jpg) | ![Crumpled paper in Live RT](docs/img/photo_paper_live.jpg) |
| ![3D-printed cube: photo sample and texture](docs/img/photo_cube_texture.jpg) | ![Plush: photo sample and texture](docs/img/photo_plush_texture.jpg) | ![Receipt: photo sample and texture](docs/img/photo_paper_texture.jpg) |
| ![Bowl in Live RT](docs/img/photo_bowl_live.jpg) | ![Webcam in Live RT](docs/img/photo_webcam_live.jpg) | ![Massager in Live RT](docs/img/photo_massager_live.jpg) |
| ![Bowl: photo sample and texture](docs/img/photo_bowl_texture.jpg) | ![Webcam: photo sample and texture](docs/img/photo_webcam_texture.jpg) | ![Massager: photo sample and texture](docs/img/photo_massager_texture.jpg) |

| Object | Spark understood / SAM found | Understand | Generate | Critique | Result |
|---|---|---|---|---|---|
| 3D-printed cube | black circuit plastic / "black box" | 14 s | 29 s | 55 s, 6 → 7 | ✅ The best one: circuit traces and print grain kept |
| Plush | beige plush fleece / "plush toy" | 32 s | 33 s | 51 s, 4 → 6 | ✅ Fleece, with sheen 0.9 and subsurface set by Spark. Critique: too pale, relief too flat |
| Webcam | glossy black plastic / "webcam" | 18 s | 33 s | 41 s, 4 → 5 | ✅ Right but plain. Colour ΔE 0.3 |
| Massager | white matte plastic / "white cap" | 20 s | 38 s | 64 s, 4 → 7 | ✅ Critique saw a cross-shaped seam on the sphere and had Muse repaint the tile without it |
| Bowl | pale blue glazed ceramic / "bowl" | 17 s | 34 s | 68 s, 3 → 7 | ✅ after the critique: Muse first drew the outside's oval decoration on a plain glaze; Spark saw it and had it repainted plain |
| Receipt, no text | frosted glass table / "glass table" | 17 s | 36 s | 41 s, 4 → 6 | ❌ Took the table: the largest surface, not the paper. Fixed since, see below |
| Receipt, "the crumpled paper" (said in French) | crumpled paper / "crumpled paper" | 20 s | 31 s | 67 s, 6 → 3, first kept | ⚠️ The paper, without its print. But a lighter band runs along the top and bottom edges |

**Time** (7 runs, median): understand 18 s (Spark's plan 13 s, from 11 to 30 s; SAM 2.6 s), generate
33 s (Muse Image 11 s, Muse height 11 s, pbrforge about 6 s), critique 55 s, 1K export 10 s for a
10 to 21 MB zip. From photo to a downloadable 1K material: about 1 min, 2 min with the critique.

**What went wrong, and what it says:**
- **"The main material" meant the largest surface (fixed).** With no words, Spark picked the glass
  table under the receipt. Saying it ("the crumpled paper") fixed it at once. Then Spark was taught to
  read the photo as its author framed it: with no words, the subject is what is centred, in focus,
  closest and standing out, and the table or wall around it is context. It now names the subject and
  says why, and the page shows it. Rerun with no text, all six photos land on their object: the
  receipt gives "crumpled printed paper" ("centered white crumpled object stands out against the
  glass table"), and SAM masks the paper only.
- **The seam score misses a band that repeats on both edges.** The paper scored 0.77 ("invisible")
  with a light strip along its top and bottom edges, and the massager 1.39 with a cross Spark saw on
  the sphere: the score compares opposite edges, and here both edges carry the same strip. Spark's
  critique caught both; the score did not. A border-band check is the next metric to add.
- **Muse borrows patterns from elsewhere on the object.** The bowl's inside is a plain glaze; the
  first texture took the ovals painted on its outside. Spark's critique caught it ("repeating white
  oval decoration... while main photo area is plain glaze") and had Muse repaint a uniform glaze:
  3/10 → 7/10. Still missing by its own review: the glossy reflections and the fine pinholes.
- **The critique does not always improve things.** On the paper, Spark's own fix scored 3 against 6
  for the first version: MatterLift kept the first.
- **Colour** after matching to the photo: ΔE 0.3 (webcam) and 1.9 (cube) on the dark objects, 12 to 17
  on the pale ones (bowl, plush, massager, paper, table).

## Built during the hackathon

Meta hackathon *Build for Your World*, Indie Developer track.

| | |
|---|---|
| First commit | 2026-11-01 18:57 (Paris) |
| Our code | Everything in this repository was written from 2026-11-01 onward; the Git history is the proof |
| Meta models (API) | Muse Spark 1.3, Muse Image 1.0, SAM 3.1, Muse Voice Transcribe 1.0 |
| Ported from Meta | `api/matterlift_api/sam_mask.py`: SAM mask decoder ported from `@meta-sam/parser` 0.1.0 (SAM License) |
| Quality reference | ambientCG Bricks113A (CC0), used locally as the benchmark and export-format model; not in the repository |
| Preview meshes | Stanford Dragon, Happy Buddha and Lucy, Stanford 3D Scanning Repository (Stanford Computer Graphics Laboratory), decimated to 150k triangles each: `web/public/models/` (details and terms in `web/public/models/CREDITS.md`) |
| Libraries | numpy, SciPy, Pillow, FastAPI, Uvicorn, httpx, Pydantic, python-dotenv; Three.js, three-mesh-bvh (BVH build for Live RT), Vite, TypeScript |
| Live RT renderer | Ours, written during the hackathon: started 2026-11-01 23:51 (Paris) as a standalone WebGPU prototype, shown in MatterLift from commit `3e5736c` (2026-11-02 01:21, Paris), and in this repository (`web/src/live/`, `live.html`) since commit `f345066` (2026-11-02 02:03, Paris) |
| Hosting | Modal (API), Cloudflare Workers (page) |
| Checked with | Godot 4.7, Blender 5.0, Khronos glTF Validator |

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

**Preview passes (AOVs)**: Beauty, Depth, Normal, Albedo, Roughness, AO, Thickness, with the height
map as real displacement on the mesh (so the depth pass shows the relief), and Save PNG for the
current pass.

![The ruby on the Stanford dragon: Beauty, Depth, Normal and Thickness passes](docs/img/passes_ruby.jpg)
*"a ruby" on the dragon: Beauty, Depth (white = near), Normal, Thickness (white = thick: the veins
of the stone, projected triplanar since the scan has no UVs).*

**Preview shapes and look-dev**: Sphere, Cube, Plane and three Stanford scans, **Dragon**, **Buddha**
and **Lucy** (150k triangles each; no UVs, so always triplanar and without displacement). **Normal scale**, **Displacement scale**,
**Tiling scale** and **Clay render** (grey, no colour or metal, the relief stays) apply to every
shape. A see-through material (glass, gem) shows the studio behind it, dimmed, so its refraction has
something to bend, with colour dispersion growing with its IOR.

**Live RT**: the same material on the selected scan (Dragon, Buddha or Lucy; Sphere, Cube and Plane
are greyed out while it is on), path traced in the browser with WebGPU: unbiased
ReSTIR DI (generalised RIS with pairwise MIS, temporal and spatial reuse) over 256 spot lights,
shadow rays through a BVH in compute shaders, an SVGF denoiser, accumulation that stops once the
image has converged. It is written for any WebGPU GPU (plain WGSL, default limits, GPU timers only
when offered): its *Auto* quality steps down the internal resolution until a frame takes under
40 ms. The renderer is the `live.html` page of the same site (`web/src/live/`: `restir.js` for the
passes, `wgsl.js` for the shared WGSL, `main.js` for the scene), shown in an iframe over the preview
and fed the current maps and scan; it uses the preview's decimated scans (150k triangles each). Its
unbiasedness is checked against an exact reference (every light, one shadow ray each) by
`live.html?test`: mean bias under 0.1 % (0.03 % for both unbiased variants, -12.9 % for the plain
biased combination, over 128 frames on the dragon). Normal scale, tiling and clay follow it; displacement does not (it traces the mesh as
it is).

**Live RT limits** (an experimental viewer; the rest of MatterLift does not depend on it):

- **Tested on one machine only:** Windows 11, NVIDIA GeForce RTX 4060 (desktop), AMD CPU, in Chromium
  (Chrome and the Chromium of the Claude desktop app). There it runs at 30-150 FPS depending on the
  variant and the zoom, about 25 ms per frame at 1080p for the visibility-in-target variant.
- **AMD GPU:** one remote test on a Radeon (RDNA 2) showed a corrupted image. The cause (integers stored
  in float lanes, which AMD may canonicalise) is fixed, but the fix has not been checked on an AMD
  GPU since.
- **Linux, Firefox, Safari, mobile: not tested.** WebGPU itself may be missing: on Linux, Chrome's
  WebGPU depends on the version and the GPU driver (it may need `chrome://flags`); Firefox and Safari
  ship WebGPU on some systems only. Without WebGPU the **Live RT** button is disabled and says why.
- **Laptops with two GPUs:** Chrome on Windows ignores the "high performance" request and may pick the
  integrated GPU; set Chrome to *High performance* in Windows graphics settings.
- **Weak or integrated GPUs** should settle at 540p or 360p (estimate from the costs measured on the
  RTX 4060). The renderer needs about 700 MB of GPU memory at 1080p and 170 MB at 540p; if allocation
  fails it steps down, and if the driver drops the GPU it asks for a reload.
- **Not a full material preview:** direct lighting only (no indirect bounce), a mirror floor without
  shadows, and transmission, clearcoat, sheen, AO and displacement are not rendered.

**Library mode**: one photo of a room gives every material in it. Spark lists up to 8 materials
with two points on each; SAM masks each from its noun phrase (one concept per request, all in
parallel), Spark's points pick the right instance; then every sample is generated in parallel.
On a kitchen photo: 7 of 8 materials in 81 s. (Point prompts can segment 16 objects in one SAM
pass, but a point selects an object, one brick rather than the wall, so concept prompts win.)

- **Manual mode.** Click the surfaces you want on the photo before Generate, one material per click
  (Shift+click: more points on the same one). For each one Spark sees the photo with markers and
  plans the material under them; SAM then masks it, framed by Spark's noun phrase (the instance under
  your points) or, with *Spark frames the masks* off, as the object under the points.
- **Edit after Generate.** Click the photo in *What MatterLift understood* to add a material there;
  ↻ on a card then a click redoes that one; × removes it. Only the new or redone material is
  painted (`POST /libraries/{id}/items`, `DELETE /libraries/{id}/items/{index}`).

```
photo + voice/text
  -> Muse Voice Transcribe   (voice -> text, shown in the box right after recording)
  -> Muse Spark (Enrich)     ("old brick" -> a precise brief: colour, finish, wear, scale; editable, undoable)
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
| Muse Spark | Enriches short requests into a precise brief (same language, uses the photo); plans the material (roughness, metal, relief, shading model), names the surface for SAM |
| SAM 3.1 | Masks the surface in the photo (or the object under the user's points), so the samples avoid what lies on it |
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
Spark picks `detail_kind`, `detail_strength` and `wear` from the request ("very worn old parquet"
-> wood, 0.6, wear 0.85); the kind is inferred from the name when it does not say.

**Triplanar preview.** A Triplanar toggle projects every map along the world axes (whiteout blend
for normals): no UVs needed, no stretching at the sphere's poles, the same scale as the UVs.

**Colour fidelity.** Muse repaints the sample, so colours drift (a dusty terracotta comes back bright
orange). The albedo is matched to the delit photo samples in CIELAB, hue fully and lightness at 60%
(a sample in shadow says little about the true value). Delta E between mean colours, kitchen
materials: oak 10.7 -> 1.7, floor 37.1 -> 7.4, brick 13.9 -> 4.5. The UI shows sample and albedo
side by side with that score.

## Run it

Python 3.11+ and Node 20+. A Meta Model API key goes in `.env` (never committed). One command per
line, so it works the same in Windows PowerShell, Git Bash, macOS and Linux.

```bash
git clone https://github.com/falcon123212/matterlift
cd matterlift
python -m venv .venv
.venv/Scripts/python -m pip install -e .[dev]   # macOS/Linux: .venv/bin/python
cp .env.example .env                              # then set META_API_KEY
.venv/Scripts/python scripts/smoke_meta.py        # every Meta model answers
.venv/Scripts/python -m pytest -q                 # offline tests, no API calls
.venv/Scripts/python -m uvicorn matterlift_api.main:app --app-dir api --port 8001
npm --prefix web install
npm --prefix web run dev                          # http://localhost:5173 (second terminal)
```

API:
- `POST /understand` (form: `photo`, optional `text`, `audio`): step 1, returns the plan, overlay and sample.
- `POST /materials` (form: `understanding` id, or `text`/`audio` with optional `photo`; `size`): a material.
- `POST /libraries` (form: `photo`, optional `text`, `audio`; manual mode: `points` as JSON
  `[[[x, y], ...], ...]` in 0..1000, one group per material, and `frame` true/false): library step 1;
  then `POST /libraries/{id}/build` (form: `size`) generates every material that has none yet.
- `POST /libraries/{id}/items` (form: `points` with one group, `frame`, optional `index` to redo
  that item) and `DELETE /libraries/{id}/items/{index}`: edit a library.
- `GET /materials/{id}`, `/materials/{id}/maps/{name}.png`, `/materials/{id}/export?size=2048&fmt=png`,
  `GET /libraries/{id}`. The UI reopens them with `?id=` or `?lib=`.

## Tests and benchmarks

180 offline tests (no Meta key, no network) run on every push in GitHub Actions, with Godot and the
formats' official validators installed:

| What | How it is checked |
|---|---|
| Every export the UI offers | 512, 1K, 2K, 4K × PNG, JPG: every file present and named like ambientCG, sizes, pixel formats (16-bit displacement), albedo in PBR range, unit normals facing out, DirectX normal = OpenGL with green flipped, **every map tiles without a seam**, zip complete, `.glb` textures at full size (`tests/test_export_matrix.py`) |
| glTF | **Khronos glTF-Validator**: 0 errors, 0 warnings on 14 packages (every shading lobe: clearcoat, sheen, transmission + IOR, anisotropy, subsurface, all at once; metal and not), including the thickness texture of KHR_materials_volume |
| MaterialX | **MaterialX library (ASWF)**: documents validate, one OpenPBR surface, every texture file exists |
| USD | **Pixar USD**: stages open, UsdPreviewSurface with its 5 inputs connected, every texture asset resolves |
| Godot 4.7 | **Godot headless** opens the 14 packages: the `.tres` with all its textures, the live shader **compiles** (its controls are exposed), the `.glb` loads through GLTFDocument (`tests/test_export_godot.py`) |
| What users upload | Through the HTTP API: JPEG, PNG with transparency, palette PNG, 16-bit PNG, greyscale, CMYK JPEG, WebP, rotated phone photo, 24 px, 6000 px, 4000×300 panorama → a material; empty, truncated, non-image, 31 MB upload, decompression bomb → a clear 400/413; WAV speech, silence, non-WAV audio; path traversal and bad ids → 404 (`tests/test_api_inputs.py`) |
| Model failures | Spark garbage or empty answers, SAM misses, Muse failures: a material still comes out (`tests/test_resilience.py`) |
| Performance | Time and memory guards per size (`tests/test_perf.py`); the 4K export must fit the API container |

The validators were checked against broken files (a wrong MaterialX type, a missing USD texture, a
corrupted `.glb` count, a shader with an unknown identifier): each one fails as it should.

These tests found a real bug: 2K and 4K exports had a seam at the tile border, because the resize
(Pillow's Lanczos) clamps at the image edge instead of wrapping. Maps are now padded with their own
opposite edges before resizing (`pbrforge/io.py`); the seam score went from 3.98 to 1.07 (1 = invisible).

**Export report on a real material** (`scripts/export_report.py`, full table in
[`results/export_report.md`](results/export_report.md)): "old red brick", generated by MatterLift,
exported the way the download button does it at 512, 1K, 2K, 4K × PNG, JPG, plus every shading lobe:
**14 of 14 packages pass glTF-Validator, MaterialX, USD and Godot**. A 4K PNG package (maps recomputed
at 4K, 20 files) takes 76 s and zips to 203 MB; 1K takes 5 s and 17 MB.
The 512 PNG package, unzipped, is in [`samples/export/OldRedBrick_512-PNG`](samples/export/OldRedBrick_512-PNG):
drop the folder into a Godot project, open the `.glb` in Blender, or load the `.mtlx` / `.usda`.

**pbrforge performance** (`scripts/bench_pbrforge.py`, full table in `results/perf_pbrforge.md`), from a
1600 px albedo (Muse Image's size), on a desktop AMD CPU (12 threads):

| Size | Maps (s) | Peak memory | Export + zip, PNG (s) | Zip, PNG / JPG |
|---|---|---|---|---|
| 512 | 0.35 | 46 MB | 0.8 | 6 / 5 MB |
| 1K | 1.3 | 122 MB | 2.1 | 20 / 15 MB |
| 2K | 5.5 | 487 MB | 7.8 | 66 / 47 MB |
| 4K | 24.7 | 2.5 GB | 31 | 224 / 149 MB |

A 4K export needs about 2.5 GB, within the 4 GB of the API container; two at the same moment would
likely not fit (not measured yet: that is for the load test), so 4K exports are best done one at a time.

## Deploy

- API on Modal: `modal deploy deploy/modal_app.py`. The Meta key is read from the local `.env` at
  deploy time and stored as a Modal secret, never in the image; materials live on a Modal Volume.
- Page on Cloudflare Workers (static assets, `web/wrangler.jsonc`):

```bash
cd web
npm run deploy   # builds with web/.env.production (API URL), refuses an unbuilt page, deploys
```

  Cloudflare also redeploys the page on every push to GitHub (Workers Builds). The root
  `wrangler.jsonc` makes that build the page and run the same check first; without it Cloudflare
  served the unbuilt `web/` folder and the page lost its CSS after each push.

`VITE_LIVE_URL` points **Live RT** at another copy of the WebGPU renderer (default: `live.html` of the same site).

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
  RustyPaintedSteel_2K-PNG_Thickness.png      only when light goes in or through (subsurface, transmission)
  RustyPaintedSteel_2K-PNG.tres               Godot 4 StandardMaterial3D
  RustyPaintedSteel_2K-PNG.mtlx               MaterialX OpenPBR
  RustyPaintedSteel_2K-PNG.usda               USD UsdPreviewSurface
  RustyPaintedSteel_2K-PNG.glb                glTF 2.0, textures embedded, on a preview sphere
  shader/                                      live controls instead of baked ones:
    RustyPaintedSteel_2K-PNG.gdshader          Godot 4 shader: tiling, relief, detail, wear, triplanar sliders
    RustyPaintedSteel_2K-PNG_shader.tres       ShaderMaterial with its textures assigned
    RustyPaintedSteel_2K-PNG_blender.py        Blender 4/5: builds the node tree, Value nodes are the controls
    *_ShaderColor/Normal/ORM, _WearMask, _DetailNormal, _DetailHeight   clean layers they recombine
  RustyPaintedSteel.png                       preview sphere
```

Spark's shading model goes into every format that has it: KHR_materials_clearcoat, _transmission,
_ior, _sheen, _anisotropy and _diffuse_transmission (for subsurface) in the `.glb`; clearcoat,
anisotropy, subsurface scattering, rim (for sheen) and specular (for IOR) in the `.tres`; coat,
transmission, fuzz, subsurface, anisotropy and IOR in the OpenPBR `.mtlx`; clearcoat and IOR in the
`.usda`.

Skin, wax, jade, glass or ruby also get a **thickness map**: how much matter light crosses, white =
thick. A photo cannot measure it, so it follows the broad relief: raised masses are thick, hollows thin,
pores and scratches leave it alone (a flat skin stays evenly thick instead of blotchy). It goes in the
`.glb` as KHR_materials_volume (thickness tinted by the albedo), in the `.tres` as subsurface
transmittance, and in the `.mtlx` as OpenPBR's subsurface radius and transmission depth.
UsdPreviewSurface has no such input. The page shows it as the **Thick** render pass.

The `shader/` folder keeps the studio controls live: the base maps without detail or wear, one
detail tile and a wear/grain mask (edges, cavities, grain direction), recombined by a Godot shader and
a Blender node tree with the same maths as pbrforge, so the defaults match the baked textures and
tiling, relief, detail and wear stay sliders.

Verified:
- the Godot shader compiles in Godot 4.7.2 and renders as the baked `.tres` at its defaults, with
  wear, detail and triplanar on a cube changing as expected;
- the Blender script runs in Blender 5.0 (31 nodes, colour mixes on their colour sockets) and
  renders in Cycles;
- the `.glb` passes the Khronos glTF Validator with 0 errors and 0 warnings, including a material
  with five KHR extensions;
- Three.js loads it as a MeshPhysicalMaterial with every map and every extension value;
- Godot 4.7.2 loads the `.glb` (maps, tiling from KHR_texture_transform) and the `.tres`, next to
  the reference package. Godot's glTF importer ignores clearcoat and anisotropy, so for Godot the
  `.tres` is the file that carries them.

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

## Credits

Concept, product design, UI design and build plan: Silver (falcon123212).
Implementation written with Claude Code (Anthropic) as a coding assistant, under my direction:
I chose the pipeline, reviewed the code, ran the tests and validated the materials in the results
gallery.
Meta models: Muse Spark, SAM 3.1, Muse Image, Muse Voice Transcribe.
3D models: Stanford Dragon, Happy Buddha and Lucy from the Stanford 3D Scanning Repository,
Stanford University Computer Graphics Laboratory (https://graphics.stanford.edu/data/3Dscanrep/),
used under its terms (non-commercial, source acknowledged); see `web/public/models/CREDITS.md`.
Third-party code, data and libraries: see [Built during the hackathon](#built-during-the-hackathon).

## License

MIT (see `LICENSE`), except `api/matterlift_api/sam_mask.py`, a port of Meta's `@meta-sam/parser`,
which is distributed under the SAM License (see `LICENSE-SAM`), and the 3D models in
`web/public/models/` (Stanford 3D Scanning Repository terms, see `web/public/models/CREDITS.md`).
