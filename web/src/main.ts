import "./style.css";
import { Preview, isScan, type Aov, type LightPass, type MaterialMaps, type Scan, type Shading, type Shape, type Tweaks } from "./preview";

const API = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";

interface Material {
  id: string;
  request: string;
  source: string;
  size: number;
  plan: { name: string; shading: Shading } & Record<string, unknown>;
  maps: MaterialMaps & Record<string, string>;
  scores: { before?: Record<string, unknown>; after?: Record<string, unknown> } & Record<string, unknown>;
  timings: Record<string, number>;
}

interface Plan {
  name: string;
  texture_prompt: string;
  sam_prompt: string;
  roughness: number;
  metallic: number;
}

/** Step 1 with a photo: what Spark understood and where SAM found it. */
interface Understanding {
  id: string;
  request: string;
  plan: Plan;
  matched: boolean;
  crop_from: "mask" | "box" | "points" | null;
  found_by: string | null;
  overlay: string;
  crops: string[];
  timings: Record<string, number>;
}

/** Spark's review: what it saw, what it changed, and its verdict on the result. */
interface Critique {
  before: string;
  after: string;
  chosen: string;
  score_before: number;
  score_after: number;
  issues: string[];
  remaining: string[];
  params_changed: Record<string, [number, number]>;
  albedo_fix: string;
  colour_matched: boolean;
  review_before: string;
  review_after: string | null;
  seconds: number;
}

interface Library {
  id: string;
  overlay: string;
  status: "understood" | "built";
  items: {
    plan: Plan;
    crops: string[];
    crop_from: string | null;
    found_by: string | null;
    material: Material | null;
    error: string | null;
    manual?: boolean;
  }[];
  timings: Record<string, number>;
}

const $ = <T extends HTMLElement>(sel: string) => document.querySelector(sel) as T;
const preview = new Preview($("#canvas-wrap"));
const status = $<HTMLParagraphElement>("#status");

function toggle(groupSel: string, attr: string, apply: (v: string) => void) {
  $(groupSel).addEventListener("click", (e) => {
    const btn = (e.target as HTMLElement).closest("button");
    if (!btn) return;
    $(groupSel).querySelectorAll("button").forEach((b) => b.classList.toggle("on", b === btn));
    apply(btn.dataset[attr]!);
  });
}
let currentShape: Shape = "sphere";
toggle("#shapes", "shape", (v) => {
  currentShape = v as Shape;
  void preview.setShape(currentShape);
  showTriplanar(isScan(v));
  // Live RT follows the scan picked here
  if (isScan(v)) sendLiveModel(v);
});
toggle("#lights", "light", (v) => preview.setLight(v as LightPass));
let currentAov: Aov = "beauty";
toggle("#aovs", "aov", (v) => preview.setAov((currentAov = v as Aov)));
$("#snapshot").addEventListener("click", () => {
  const a = document.createElement("a");
  a.href = preview.snapshot();
  a.download = `${currentName}_${currentAov}.png`;
  a.click();
});
let currentName = "matterlift";
$("#critique-btn").addEventListener("click", () => {
  if (currentMaterial) void runCritique(currentMaterial);
});
let triplanarOn = false;
$("#triplanar").addEventListener("click", () => {
  triplanarOn = !triplanarOn;
  showTriplanar(false);
  preview.setTriplanar(triplanarOn);
});
/** The scans are always triplanar (no UVs): the button shows it and is locked there. */
function showTriplanar(forced: boolean) {
  const b = $<HTMLButtonElement>("#triplanar");
  const on = forced || triplanarOn;
  b.disabled = forced;
  b.classList.toggle("on", on);
  b.setAttribute("aria-pressed", String(on));
}

// Live path tracing: the WebGPU ReSTIR renderer (live.html, src/live) in an iframe over the preview,
// fed the current material's maps as ImageBitmaps. The WebGL preview sleeps while it is shown.
const LIVE_URL = (import.meta.env.VITE_LIVE_URL as string | undefined) ?? new URL("live.html", location.href).href;
let live: HTMLIFrameElement | null = null;
let liveReady = false;
let liveMaps: Record<string, string> | null = null;

const liveBtn = $<HTMLButtonElement>("#live");
if (!("gpu" in navigator)) {
  liveBtn.disabled = true;
  liveBtn.title = "Live path tracing needs WebGPU (recent Chrome or Edge on desktop, Safari 26)";
}
liveBtn.addEventListener("click", () => {
  const on = !liveBtn.classList.contains("on");
  liveBtn.classList.toggle("on", on);
  liveBtn.setAttribute("aria-pressed", String(on));
  // Live RT traces the scans only: Sphere / Cube / Plane are greyed out, and a primitive switches to the dragon
  if (on && !isScan(currentShape)) $<HTMLButtonElement>('#shapes [data-shape="dragon"]').click();
  $("#shapes")
    .querySelectorAll<HTMLButtonElement>("button")
    .forEach((b) => {
      if (!isScan(b.dataset.shape!)) b.disabled = on;
    });
  if (on && !live) {
    const url = new URL(LIVE_URL);
    url.searchParams.set("embed", "");
    url.searchParams.set("model", currentShape);
    live = document.createElement("iframe");
    live.className = "live-frame";
    live.src = url.href;
    live.title = "Live path-traced preview";
    $("#canvas-wrap").append(live);
  }
  if (live) live.hidden = !on;
  preview.setActive(!on);
});
window.addEventListener("message", (e) => {
  if (!live || e.source !== live.contentWindow || e.data?.type !== "live-rt:ready") return;
  liveReady = true;
  void sendLiveMaterial();
  sendLiveTweaks();
});

// Look-dev controls: one set for every shape, mirrored in Live RT (which has no displacement:
// it traces the mesh as it is).
const tweaks = (): Tweaks => ({
  normalScale: +$<HTMLInputElement>("#tw-normal").value,
  displacement: +$<HTMLInputElement>("#tw-disp").value,
  tiling: 2 ** +$<HTMLInputElement>("#tw-tiling").value,
  clay: $<HTMLInputElement>("#tw-clay").checked,
});
$("#tweaks").addEventListener("input", () => {
  const t = tweaks();
  const outs = $("#tweaks").querySelectorAll("output");
  [t.normalScale, t.displacement, t.tiling].forEach((v, i) => (outs[i].textContent = v.toFixed(2)));
  preview.setTweaks(t);
  sendLiveTweaks();
});

function sendLiveModel(model: Scan) {
  if (!live?.contentWindow || !liveReady) return;
  live.contentWindow.postMessage({ type: "live-rt:model", model }, "*");
}

function sendLiveTweaks() {
  if (!live?.contentWindow || !liveReady) return;
  const { normalScale, tiling, clay } = tweaks();
  live.contentWindow.postMessage({ type: "live-rt:settings", normalScale, tiling, clay }, "*");
}

async function sendLiveMaterial() {
  if (!live?.contentWindow || !liveReady || !liveMaps) return;
  const keys = ["albedo", "normal", "roughness", "metallic"] as const;
  const bitmaps = await Promise.all(
    keys.map(async (k) => (liveMaps?.[k] ? createImageBitmap(await (await fetch(liveMaps[k])).blob()) : undefined)),
  );
  const maps = Object.fromEntries(keys.map((k, i) => [k, bitmaps[i]]));
  live.contentWindow.postMessage({ type: "live-rt:material", maps }, "*", bitmaps.filter((b) => b !== undefined));
}

function absolute(maps: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(maps).map(([k, v]) => [k, API + v]));
}

function fmt(v: unknown): string {
  if (Array.isArray(v)) return v.map((x) => x ?? "–").join(" × ");
  return v === null || v === undefined ? "–" : String(v);
}

function showScores(mat: Material) {
  const before = mat.scores.before ?? {};
  const after = mat.scores.after ?? {};
  const rows = ["seam", "repetition", "albedo_out_of_range", "period"];
  const timing = Object.entries(mat.timings).map(([k, v]) => `${k} ${v}s`).join(" · ");
  $("#scores").innerHTML =
    `<tr><th></th><th>Muse raw</th><th>MatterLift</th></tr>` +
    rows.map((r) => `<tr><td>${r}</td><td>${fmt(before[r])}</td><td>${fmt(after[r])}</td></tr>`).join("") +
    `<tr><td colspan="3" class="muted">${timing}</td></tr>`;
}

/** Photo sample next to the albedo, with the colour gap (CIE76 Delta E) before and after matching. */
function showFidelity(mat: Material, maps: Record<string, string>) {
  const box = $("#fidelity");
  box.hidden = !maps.photo_sample;
  if (box.hidden) return;
  $<HTMLImageElement>("#fid-photo").src = maps.photo_sample;
  $<HTMLImageElement>("#fid-albedo").src = maps.albedo;
  const f = mat.scores.fidelity as { delta_e_before?: number; delta_e_after?: number } | undefined;
  const verdict = (d: number) => (d < 3 ? "same colour" : d < 10 ? "close" : "different colour");
  $("#fid-text").textContent = f?.delta_e_after !== undefined
    ? `Colour gap ΔE ${f.delta_e_before} → ${f.delta_e_after} after matching to the photo (${verdict(f.delta_e_after)}).`
    : "";
}

let currentId: string | null = null;

function showCritique(c: Critique) {
  $("#critique").hidden = false;
  const kept = c.chosen === c.after && c.after !== c.before;
  describe($("#crit-score"), c.after === c.before
    ? ["Spark scores it ", [`${c.score_before}/10`], c.issues.length ? " and changes nothing." : ": nothing to fix."]
    : ["Spark scored ", [`${c.score_before}/10`], ", fixed it, then scored ", [`${c.score_after}/10`],
       kept ? ". Keeping the fixed version." : ". The fix was not better: keeping the original."]);
  $<HTMLImageElement>("#crit-before").src = API + c.review_before;
  $("#crit-issues").replaceChildren(...c.issues.map((i) => el("li", i)));
  const changes = Object.entries(c.params_changed).map(([k, [a, b]]) => `${k.replace(/_/g, " ")} ${a} → ${b}`);
  if (c.colour_matched) changes.push("colour matched to the photo");
  if (c.albedo_fix) changes.push(`albedo repainted by Muse: “${c.albedo_fix}”`);
  $("#crit-changes").textContent = changes.length ? `Changes: ${changes.join(" · ")} (${c.seconds} s)` : "";
  $("#crit-after-fig").hidden = !c.review_after;
  if (c.review_after) $<HTMLImageElement>("#crit-after").src = API + c.review_after;
}

async function runCritique(mat: Material) {
  const btn = $<HTMLButtonElement>("#critique-btn");
  btn.disabled = true;
  const stop = ticking(() => "Spark reviews it under raking light and tiled…");
  try {
    const c = await post<Critique>(`/materials/${mat.id}/critique`, new FormData());
    showCritique(c);
    if (c.chosen !== mat.id) {
      const r = await fetch(`${API}/materials/${c.chosen}`);
      if (r.ok) await show((await r.json()) as Material);
    }
    status.textContent = `${mat.plan.name} — Spark: ${c.score_before}/10 → ${c.score_after}/10`;
  } catch (err) {
    status.textContent = `Critique failed: ${(err as Error).message}`;
  } finally {
    stop();
    btn.disabled = false;
  }
}

function updateExportLink() {
  const link = $<HTMLAnchorElement>("#export-link");
  link.classList.toggle("disabled", !currentId);
  if (!currentId) return link.removeAttribute("href");
  const size = $<HTMLSelectElement>("#export-size").value;
  const fmt = $<HTMLSelectElement>("#export-fmt").value;
  link.href = `${API}/materials/${currentId}/export?size=${size}&fmt=${fmt}`;
}
$("#export-size").addEventListener("change", updateExportLink);
$("#export-fmt").addEventListener("change", updateExportLink);

let currentMaterial: Material | null = null;

async function show(mat: Material, updateUrl = true) {
  currentId = mat.id;
  currentMaterial = mat;
  $<HTMLButtonElement>("#critique-btn").disabled = false;
  const prior = mat.scores.critique as Critique | undefined;
  if (prior) showCritique(prior);
  else $("#critique").hidden = true;
  currentName = mat.plan.name;
  updateExportLink();
  const maps = absolute(mat.maps) as unknown as MaterialMaps & Record<string, string>;
  liveMaps = maps;
  void sendLiveMaterial();
  await preview.load(maps, mat.plan.shading);
  $("#tiling").style.backgroundImage = `url(${maps.albedo})`;
  $("#maps").innerHTML = Object.entries(maps)
    .map(([k, v]) => `<figure><img src="${v}" alt="${k}" loading="lazy" /><figcaption>${k}</figcaption></figure>`)
    .join("");
  showScores(mat);
  showFidelity(mat, maps);
  if (updateUrl) history.replaceState(null, "", `?id=${mat.id}`);
}

// --- Voice: recorded in the browser, transcribed server-side by Muse Voice Transcribe ---

/** MediaRecorder gives WebM/Opus; /v1/asr/transcribe accepts only mono 16-bit PCM WAV at 16/24 kHz. */
async function toWav(blob: Blob, rate = 24_000): Promise<Blob> {
  const decoded = await new AudioContext().decodeAudioData(await blob.arrayBuffer());
  const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * rate), rate);
  const src = offline.createBufferSource();
  src.buffer = decoded;
  src.connect(offline.destination);
  src.start();
  const pcm = (await offline.startRendering()).getChannelData(0);
  const buf = new ArrayBuffer(44 + pcm.length * 2);
  const v = new DataView(buf);
  const str = (o: number, s: string) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  str(0, "RIFF");
  v.setUint32(4, 36 + pcm.length * 2, true);
  str(8, "WAVE");
  str(12, "fmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); // PCM
  v.setUint16(22, 1, true); // mono
  v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  str(36, "data");
  v.setUint32(40, pcm.length * 2, true);
  pcm.forEach((s, i) => v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 0x7fff, true));
  return new Blob([buf], { type: "audio/wav" });
}
let recorder: MediaRecorder | null = null;
let voice: Blob | null = null;
let recStart = 0;
let recTick: number | undefined;
const mic = $<HTMLButtonElement>("#mic");
const voiceState = $<HTMLSpanElement>("#voice-state");
const voiceClear = $<HTMLButtonElement>("#voice-clear");

function setVoice(blob: Blob | null, seconds = 0) {
  voice = blob;
  voiceState.textContent = blob ? `voice request ready (${seconds.toFixed(0)} s)` : "";
  voiceClear.hidden = !blob;
}

mic.addEventListener("click", async () => {
  if (recorder?.state === "recording") {
    recorder.stop();
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const chunks: Blob[] = [];
    // Live level: shows which microphone the browser picked and that it hears something.
    const device = stream.getAudioTracks()[0]?.label || "default microphone";
    const meterCtx = new AudioContext();
    const analyser = meterCtx.createAnalyser();
    analyser.fftSize = 1024;
    meterCtx.createMediaStreamSource(stream).connect(analyser);
    const samples = new Float32Array(analyser.fftSize);
    let loudest = 0;
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (ev) => chunks.push(ev.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      void meterCtx.close();
      clearInterval(recTick);
      mic.textContent = "🎤 Speak";
      mic.classList.remove("on");
      mic.setAttribute("aria-pressed", "false");
      const seconds = (performance.now() - recStart) / 1000;
      if (loudest < 0.01) {
        voiceState.textContent = `“${device}” heard nothing: pick another microphone (icon in the address bar) or check it is not muted`;
        return;
      }
      let wav: Blob;
      try {
        wav = await toWav(new Blob(chunks, { type: recorder!.mimeType }));
      } catch (err) {
        voiceState.textContent = `Could not read the recording: ${(err as Error).message}`;
        return;
      }
      // Transcribe now and put the words in the text box: the user sees what was heard and can fix it.
      voiceState.textContent = "Muse Voice Transcribe is listening…";
      try {
        const body = new FormData();
        body.append("audio", wav, "voice.wav");
        const { text } = await post<{ text: string }>("/transcribe", body);
        const box = $<HTMLTextAreaElement>('textarea[name="text"]');
        box.value = box.value.trim() ? `${box.value.trim()} ${text}` : text;
        setVoice(null);
        voiceState.textContent = `heard (${seconds.toFixed(0)} s)`;
      } catch (err) {
        setVoice(wav, seconds); // keep it: Generate sends it and the server transcribes then
        voiceState.textContent = `Transcription failed: ${(err as Error).message}`;
        return;
      }
      await enrich(); // a spoken request is short: Spark fleshes it out right away
    };
    recorder.start();
    recStart = performance.now();
    mic.textContent = "■ Stop";
    mic.classList.add("on");
    mic.setAttribute("aria-pressed", "true");
    recTick = window.setInterval(() => {
      analyser.getFloatTimeDomainData(samples);
      const peak = samples.reduce((m, s) => Math.max(m, Math.abs(s)), 0);
      loudest = Math.max(loudest, peak);
      const bars = "▮".repeat(Math.min(10, Math.round(peak * 30))).padEnd(10, "▯");
      voiceState.textContent = `● ${((performance.now() - recStart) / 1000).toFixed(0)} s ${bars} ${device}`;
    }, 100);
  } catch (err) {
    voiceState.textContent = `Microphone unavailable: ${(err as Error).message}`;
  }
});
voiceClear.addEventListener("click", () => setVoice(null));

// --- Spark fleshes out a short request into a precise material brief, shown and editable ---
const enrichBtn = $<HTMLButtonElement>("#enrich");
const enrichUndo = $<HTMLButtonElement>("#enrich-undo");
let beforeEnrich: string | null = null;

async function enrich() {
  const box = $<HTMLTextAreaElement>('textarea[name="text"]');
  const text = box.value.trim();
  if (!text) {
    voiceState.textContent = "Type or say something first.";
    return;
  }
  const body = new FormData();
  body.append("text", text);
  const photo = $<HTMLInputElement>('input[name="photo"]').files?.[0];
  if (photo) body.append("photo", photo); // Spark describes what it sees in it
  enrichBtn.disabled = true;
  voiceState.textContent = "Spark is fleshing out your request…";
  try {
    const r = await post<{ text: string; original: string }>("/enhance", body);
    beforeEnrich = r.original;
    box.value = r.text;
    enrichUndo.hidden = false;
    voiceState.textContent = "Spark enriched it — edit it or undo";
  } catch (err) {
    voiceState.textContent = `Spark could not enrich it: ${(err as Error).message}`;
  } finally {
    enrichBtn.disabled = false;
  }
}

enrichBtn.addEventListener("click", () => void enrich());
enrichUndo.addEventListener("click", () => {
  if (beforeEnrich !== null) $<HTMLTextAreaElement>('textarea[name="text"]').value = beforeEnrich;
  enrichUndo.hidden = true;
  voiceState.textContent = "";
});

// --- Understanding panel: shown as soon as Spark and SAM answer, before Muse paints ---
const photoInput = $<HTMLInputElement>('input[name="photo"]');
const libraryMode = $<HTMLInputElement>("#library-mode");
photoInput.addEventListener("change", () => {
  libraryMode.disabled = !photoInput.files?.length;
  if (libraryMode.disabled) libraryMode.checked = false;
  pickGroups = [];
  const file = photoInput.files?.[0];
  if (file) $<HTMLImageElement>("#pick-img").src = URL.createObjectURL(file);
  showPicker();
});
libraryMode.addEventListener("change", showPicker);

// Manual library mode: the user's points on the photo, one group (1-3 points) per material, in
// 0..1000 image coordinates. The browser shows phone photos upright, as the API does.
type Point = [number, number];
let pickGroups: Point[][] = [];
const frameMasks = $<HTMLInputElement>("#frame");

function showPicker() {
  $("#lib-points").hidden = !(libraryMode.checked && photoInput.files?.length);
  drawDots($("#lib-points .dots"), pickGroups);
}

function pointAt(e: MouseEvent): Point {
  const img = e.currentTarget as HTMLImageElement;
  const r = img.getBoundingClientRect();
  const clamp = (v: number) => Math.round(Math.min(1000, Math.max(0, v)));
  return [clamp(((e.clientX - r.left) / r.width) * 1000), clamp(((e.clientY - r.top) / r.height) * 1000)];
}

function drawDots(layer: HTMLElement, groups: Point[][], busy = false) {
  layer.replaceChildren(
    ...groups.flatMap((g, i) =>
      g.map(([x, y]) => {
        const d = el("span", String(i + 1), busy ? "dot busy" : "dot");
        d.style.left = `${x / 10}%`;
        d.style.top = `${y / 10}%`;
        return d;
      }),
    ),
  );
}

$<HTMLImageElement>("#pick-img").addEventListener("click", (e) => {
  const p = pointAt(e);
  const last = pickGroups[pickGroups.length - 1];
  if (e.shiftKey && last && last.length < 3) last.push(p);
  else if (pickGroups.length < 12) pickGroups.push([p]);
  drawDots($("#lib-points .dots"), pickGroups);
});
$("#pick-clear").addEventListener("click", () => {
  pickGroups = [];
  drawDots($("#lib-points .dots"), pickGroups);
});

function el<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string, cls?: string) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}

function describe(target: HTMLElement, parts: (string | [string])[]) {
  target.replaceChildren(...parts.map((p) => (Array.isArray(p) ? el("b", p[0]) : document.createTextNode(p))));
}

function showUnderstanding(und: Understanding) {
  currentLib = null;
  $("#und-edit").hidden = true;
  drawDots($("#und-pick .dots"), []);
  $("#understanding").hidden = false;
  $<HTMLImageElement>("#und-overlay").src = API + und.overlay;
  const pretty = und.plan.name.replace(/_/g, " ");
  const heard: (string | [string])[] = ["I heard “", [und.request], "”. I see ", [pretty]];
  const paint: (string | [string])[] = [". Muse will paint: ", und.plan.texture_prompt, "."];
  if (und.crop_from === "mask" || und.crop_from === "box") {
    describe($("#und-text"), [...heard, ", found by ", [und.found_by ?? "SAM"], ", and I sample the framed area", ...paint]);
  } else if (und.crop_from === "points") {
    describe($("#und-text"), [...heard, ". SAM could not outline it, so I sample around the spot Spark pointed at",
      ...paint]);
  } else {
    describe($("#und-text"), [...heard, ", but could not find it in the photo: I paint it from the description",
      ...paint]);
  }
  $("#und-items").replaceChildren();
}

let currentLib: Library | null = null;
let redoIndex: number | null = null;
let editing = false;

function showLibrary(lib: Library, onPick: (m: Material) => void) {
  currentLib = lib;
  redoIndex = null;
  $("#und-edit").hidden = false;
  drawDots($("#und-pick .dots"), []);
  $("#understanding").hidden = false;
  $<HTMLImageElement>("#und-overlay").src = API + lib.overlay;
  const sampled = lib.items.filter((i) => i.crops.length).length;
  const fromText = lib.items.length - sampled;
  describe($("#und-text"), [`I see `, [`${lib.items.length} materials`], ` in this photo and sampled `, [`${sampled}`],
    ". Each framed area is a sample Muse turns into a texture",
    fromText ? `; ${fromText} not found in the photo will be painted from their description.` : "."]);
  const cards = lib.items.map((item, i) => {
    const failed = !item.material && lib.status === "built";
    const card = el("div", undefined, "card");
    const b = el("button", undefined, `main ${item.material ? "" : failed ? "failed" : "pending"}`);
    b.type = "button";
    const src = item.material ? item.material.maps.albedo : item.crops[0];
    let thumb: HTMLElement;
    if (src) {
      const img = el("img");
      img.src = API + src;
      img.alt = item.plan.name;
      thumb = img;
    } else {
      thumb = el("div", failed ? "failed" : "from text", "missing");
    }
    b.append(thumb, el("span", `${i + 1} ${item.plan.name.replace(/_/g, " ")}`));
    if (item.error) b.title = item.error;
    if (item.material) {
      b.addEventListener("click", () => {
        $("#und-items").querySelectorAll("button.main").forEach((x) => x.classList.toggle("on", x === b));
        onPick(item.material!);
      });
    }
    const redo = el("button", "↻");
    redo.type = "button";
    redo.title = "Redo this material: then click on the photo where it is";
    redo.addEventListener("click", () => {
      redoIndex = redoIndex === i ? null : i;
      $("#und-items").querySelectorAll(".card").forEach((c, k) => c.classList.toggle("redo", k === redoIndex));
      status.textContent = redoIndex === null ? "" : `Click the photo on the ${item.plan.name.replace(/_/g, " ")}`;
    });
    const remove = el("button", "×");
    remove.type = "button";
    remove.title = "Remove this material from the library";
    remove.addEventListener("click", () => void removeFromLibrary(i));
    card.append(b, el("div", undefined, "acts"));
    card.lastElementChild!.append(redo, remove);
    return card;
  });
  $("#und-items").replaceChildren(...cards);
}

async function post<T>(path: string, body: FormData): Promise<T> {
  let r: Response;
  try {
    r = await fetch(`${API}${path}`, { method: "POST", body });
  } catch {
    throw new Error("the MatterLift server is not reachable");
  }
  if (!r.ok) {
    const text = await r.text();
    let detail = text;
    try {
      detail = JSON.parse(text).detail ?? text;
    } catch {
      /* not JSON: keep the text */
    }
    throw new Error(`${detail} (${r.status})`);
  }
  return (await r.json()) as T;
}

function ticking(label: () => string) {
  const t0 = performance.now();
  const update = () => (status.textContent = `${label()} ${((performance.now() - t0) / 1000).toFixed(0)} s`);
  update();
  const h = setInterval(update, 500);
  return () => clearInterval(h);
}

$<HTMLFormElement>("#request").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target as HTMLFormElement;
  const data = new FormData(form);
  const hasPhoto = !!(data.get("photo") as File)?.size;
  if (!hasPhoto) data.delete("photo");
  data.delete("library");
  if (recorder?.state === "recording") {
    status.textContent = "Stop the recording first.";
    return;
  }
  if (voice) data.append("audio", voice, "voice.wav");
  if (!hasPhoto && !String(data.get("text") ?? "").trim() && !voice) {
    status.textContent = "Type or say what you want, or add a photo.";
    return;
  }
  const size = String(data.get("size") ?? "1024");
  let critiqueAfter: Material | null = null;
  const btn = form.querySelector<HTMLButtonElement>('button[type="submit"]')!;
  btn.disabled = true;
  let phase = "";
  const stop = ticking(() => phase);
  try {
    if (hasPhoto && libraryMode.checked) {
      if (pickGroups.length) {
        data.append("points", JSON.stringify(pickGroups));
        data.append("frame", String(frameMasks.checked));
      }
      phase = pickGroups.length
        ? `Spark names the ${pickGroups.length} surface${pickGroups.length > 1 ? "s" : ""} you pointed at, SAM masks them…`
        : "Spark lists the materials, SAM masks each one…";
      let lib = await post<Library>("/libraries", data);
      history.replaceState(null, "", `?lib=${lib.id}`);
      const pick = pickFromLibrary;
      showLibrary(lib, pick);
      const spark = lib.timings.spark_list ?? lib.timings.spark_points ?? 0;
      phase = `Understood in ${(spark + lib.timings.sam_masks).toFixed(0)} s. Muse paints every material…`;
      const build = new FormData();
      build.append("size", size);
      lib = await post<Library>(`/libraries/${lib.id}/build`, build);
      showLibrary(lib, pick);
      const first = lib.items.find((i) => i.material)?.material;
      if (first) await pick(first);
      $("#und-items").querySelector("button.main:not(.failed):not(.pending)")?.classList.add("on");
      status.textContent = `${lib.items.filter((i) => i.material).length}/${lib.items.length} materials ready — click one to preview it, or the photo to add one`;
    } else if (hasPhoto) {
      phase = "Spark reads your request, SAM finds the surface…";
      const und = await post<Understanding>("/understand", data);
      showUnderstanding(und);
      phase = `Understood: ${und.plan.name.replace(/_/g, " ")}. Muse paints, pbrforge cleans…`;
      const gen = new FormData();
      gen.append("understanding", und.id);
      gen.append("size", size);
      const mat = await post<Material>("/materials", gen);
      await show(mat);
      status.textContent = `${mat.plan.name} — “${mat.request}” (${mat.source}, ${mat.size}px)`;
      critiqueAfter = mat;
    } else {
      $("#understanding").hidden = true;
      phase = "Spark plans, Muse paints, pbrforge cleans…";
      const mat = await post<Material>("/materials", data);
      await show(mat);
      status.textContent = `${mat.plan.name} — “${mat.request}” (${mat.source}, ${mat.size}px)`;
      critiqueAfter = mat;
    }
  } catch (err) {
    status.textContent = `Failed: ${(err as Error).message}`;
  } finally {
    stop();
    btn.disabled = false;
  }
  if (critiqueAfter && $<HTMLInputElement>("#self-critique").checked) await runCritique(critiqueAfter);
});

// Edit mode on a library: a click on the overlay adds a material there (or redoes the armed card),
// then only that material is built.
$<HTMLImageElement>("#und-overlay").addEventListener("click", (e) => {
  if (!currentLib || editing) return;
  const p = pointAt(e);
  void editLibrary([p], redoIndex);
});

async function editLibrary(points: Point[], index: number | null) {
  if (!currentLib) return;
  editing = true;
  drawDots($("#und-pick .dots"), [points], true);
  let phase = index === null ? "Spark names what you pointed at, SAM masks it…" : "Spark and SAM redo this material…";
  const stop = ticking(() => phase);
  try {
    const f = new FormData();
    f.append("points", JSON.stringify([points]));
    f.append("frame", String(frameMasks.checked));
    if (index !== null) f.append("index", String(index));
    let lib = await post<Library>(`/libraries/${currentLib.id}/items`, f);
    showLibrary(lib, pickFromLibrary);
    const target = index ?? lib.items.length - 1;
    phase = `${lib.items[target].plan.name.replace(/_/g, " ")}: Muse paints it…`;
    const b = new FormData();
    b.append("size", String($<HTMLSelectElement>('select[name="size"]').value));
    lib = await post<Library>(`/libraries/${lib.id}/build`, b);
    showLibrary(lib, pickFromLibrary);
    const mat = lib.items[target].material;
    if (mat) {
      await pickFromLibrary(mat);
      $("#und-items").querySelectorAll("button.main")[target]?.classList.add("on");
    } else status.textContent = `Failed: ${lib.items[target].error ?? "no material"}`;
  } catch (err) {
    status.textContent = `Failed: ${(err as Error).message}`;
    drawDots($("#und-pick .dots"), []);
  } finally {
    stop();
    editing = false;
  }
}

async function removeFromLibrary(index: number) {
  if (!currentLib || editing) return;
  const name = currentLib.items[index].plan.name.replace(/_/g, " ");
  if (!confirm(`Remove ${name} from this library?`)) return;
  const r = await fetch(`${API}/libraries/${currentLib.id}/items/${index}`, { method: "DELETE" });
  if (!r.ok) {
    status.textContent = `Failed: could not remove ${name} (${r.status})`;
    return;
  }
  showLibrary((await r.json()) as Library, pickFromLibrary);
  status.textContent = `${name} removed`;
}

const pickFromLibrary = (m: Material) =>
  show(m, false).then(() => (status.textContent = `${m.plan.name} — from the library`));

const libId = new URLSearchParams(location.search).get("lib");
if (libId) {
  fetch(`${API}/libraries/${libId}`)
    .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
    .then(async (lib: Library) => {
      showLibrary(lib, pickFromLibrary);
      const first = lib.items.find((i) => i.material)?.material;
      if (first) await pickFromLibrary(first);
      $("#und-items").querySelector("button.main:not(.failed):not(.pending)")?.classList.add("on");
      if (lib.status !== "built") status.textContent = "This library is still being built.";
    })
    .catch(() => (status.textContent = `Library ${libId} not found`));
}

const id = new URLSearchParams(location.search).get("id");
if (id && !libId) {
  fetch(`${API}/materials/${id}`)
    .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
    .then((m: Material) => show(m).then(() => (status.textContent = `${m.plan.name} — ${m.request}`)))
    .catch(() => (status.textContent = `Material ${id} not found`));
}

// --- Tutorial: a popup on arrival, reopened with "?"; examples fill the request box ---
const EXAMPLES = ["old oak planks", "rusty painted steel", "mossy flagstone", "vieille brique rouge"];
const tutorial = $<HTMLDialogElement>("#tutorial");
const tutHide = $<HTMLInputElement>("#tut-hide");
const TUT_KEY = "matterlift.tutorial.hidden";

function storage(write?: boolean): boolean {
  try {
    if (write !== undefined) localStorage.setItem(TUT_KEY, write ? "1" : "");
    return localStorage.getItem(TUT_KEY) === "1";
  } catch {
    return false; // private window or blocked storage: the popup simply shows again
  }
}

document.querySelectorAll<HTMLDivElement>(".examples").forEach((box) => {
  for (const text of EXAMPLES) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = text;
    b.addEventListener("click", () => {
      const area = $<HTMLTextAreaElement>('textarea[name="text"]');
      area.value = text;
      if (box.hasAttribute("data-close")) tutorial.close();
      area.focus();
    });
    box.append(b);
  }
});
tutorial.addEventListener("close", () => storage(tutHide.checked));
tutorial.addEventListener("click", (ev) => {
  if (ev.target === tutorial) tutorial.close(); // click on the backdrop
});
$<HTMLButtonElement>("#help").addEventListener("click", () => {
  tutHide.checked = storage();
  tutorial.showModal();
});
if (!storage()) tutorial.showModal();
