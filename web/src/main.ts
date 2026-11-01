import "./style.css";
import { Preview, type Aov, type LightPass, type MaterialMaps, type Shading, type Shape } from "./preview";

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
toggle("#shapes", "shape", (v) => preview.setShape(v as Shape));
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
$("#triplanar").addEventListener("click", (e) => {
  const b = e.currentTarget as HTMLButtonElement;
  const on = !b.classList.contains("on");
  b.classList.toggle("on", on);
  b.setAttribute("aria-pressed", String(on));
  preview.setTriplanar(on);
});

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
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (ev) => chunks.push(ev.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      clearInterval(recTick);
      mic.textContent = "🎤 Speak";
      mic.classList.remove("on");
      mic.setAttribute("aria-pressed", "false");
      const seconds = (performance.now() - recStart) / 1000;
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
      voiceState.textContent = `● recording ${((performance.now() - recStart) / 1000).toFixed(0)} s`;
    }, 250);
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

function showLibrary(lib: Library, onPick: (m: Material) => void) {
  $("#understanding").hidden = false;
  $<HTMLImageElement>("#und-overlay").src = API + lib.overlay;
  const sampled = lib.items.filter((i) => i.crops.length).length;
  const fromText = lib.items.length - sampled;
  describe($("#und-text"), [`I see `, [`${lib.items.length} materials`], ` in this photo and sampled `, [`${sampled}`],
    ". Each framed area is a sample Muse turns into a texture",
    fromText ? `; ${fromText} not found in the photo will be painted from their description.` : "."]);
  const cards = lib.items.map((item, i) => {
    const failed = !item.material && lib.status === "built";
    const b = el("button", undefined, item.material ? "" : failed ? "failed" : "pending");
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
        $("#und-items").querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
        onPick(item.material!);
      });
    }
    return b;
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
      phase = "Spark lists the materials, SAM masks each one…";
      let lib = await post<Library>("/libraries", data);
      history.replaceState(null, "", `?lib=${lib.id}`);
      const pick = pickFromLibrary;
      showLibrary(lib, pick);
      phase = `Understood in ${(lib.timings.spark_list + lib.timings.sam_masks).toFixed(0)} s. Muse paints every material…`;
      const build = new FormData();
      build.append("size", size);
      lib = await post<Library>(`/libraries/${lib.id}/build`, build);
      showLibrary(lib, pick);
      const first = lib.items.find((i) => i.material)?.material;
      if (first) await pick(first);
      $("#und-items").querySelector("button:not(.failed):not(.pending)")?.classList.add("on");
      status.textContent = `${lib.items.filter((i) => i.material).length}/${lib.items.length} materials ready — click one to preview it`;
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
      $("#und-items").querySelector("button:not(.failed):not(.pending)")?.classList.add("on");
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
