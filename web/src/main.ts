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

$<HTMLFormElement>("#request").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target as HTMLFormElement;
  const data = new FormData(form);
  if (!(data.get("photo") as File)?.size) data.delete("photo");
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
    status.textContent = `${mat.plan.name} — ${mat.source}, ${mat.size}px`;
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
