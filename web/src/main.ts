import "./style.css";
import { Preview, type LightPass, type MaterialMaps, type Shading, type Shape } from "./preview";

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
  const rows = ["seam", "blocks", "repetition", "albedo_out_of_range", "period"];
  const timing = Object.entries(mat.timings).map(([k, v]) => `${k} ${v}s`).join(" · ");
  $("#scores").innerHTML =
    `<tr><th></th><th>Muse raw</th><th>MatterLift</th></tr>` +
    rows.map((r) => `<tr><td>${r}</td><td>${fmt(before[r])}</td><td>${fmt(after[r])}</td></tr>`).join("") +
    `<tr><td colspan="3" class="muted">${timing}</td></tr>`;
}

let currentId: string | null = null;

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

async function show(mat: Material) {
  currentId = mat.id;
  updateExportLink();
  const maps = absolute(mat.maps) as unknown as MaterialMaps & Record<string, string>;
  await preview.load(maps, mat.plan.shading);
  $("#tiling").style.backgroundImage = `url(${maps.albedo})`;
  $("#maps").innerHTML = Object.entries(maps)
    .map(([k, v]) => `<figure><img src="${v}" alt="${k}" loading="lazy" /><figcaption>${k}</figcaption></figure>`)
    .join("");
  showScores(mat);
  history.replaceState(null, "", `?id=${mat.id}`);
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
      try {
        setVoice(await toWav(new Blob(chunks, { type: recorder!.mimeType })), seconds);
      } catch (err) {
        voiceState.textContent = `Could not read the recording: ${(err as Error).message}`;
      }
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

$<HTMLFormElement>("#request").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target as HTMLFormElement;
  const data = new FormData(form);
  if (!(data.get("photo") as File)?.size) data.delete("photo");
  if (recorder?.state === "recording") {
    status.textContent = "Stop the recording first.";
    return;
  }
  if (voice) data.append("audio", voice, "voice.wav");
  if (!String(data.get("text") ?? "").trim() && !voice) {
    status.textContent = "Type or say what you want.";
    return;
  }
  const btn = form.querySelector("button")!;
  btn.disabled = true;
  const t0 = performance.now();
  const tick = setInterval(() => {
    status.textContent = `Spark plans, Muse paints, pbrforge cleans… ${((performance.now() - t0) / 1000).toFixed(0)} s`;
  }, 500);
  try {
    const r = await fetch(`${API}/materials`, { method: "POST", body: data });
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    const mat = (await r.json()) as Material;
    await show(mat);
    status.textContent = `${mat.plan.name} — “${mat.request}” (${mat.source}, ${mat.size}px)`;
  } catch (err) {
    status.textContent = `Failed: ${(err as Error).message}`;
  } finally {
    clearInterval(tick);
    btn.disabled = false;
  }
});

const id = new URLSearchParams(location.search).get("id");
if (id) {
  fetch(`${API}/materials/${id}`)
    .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
    .then((m: Material) => show(m).then(() => (status.textContent = `${m.plan.name} — ${m.request}`)))
    .catch(() => (status.textContent = `Material ${id} not found`));
}
