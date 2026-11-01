import type { RtFactory, RtViewer } from "./types";

export type { RtViewer } from "./types";

// The engine lives in ./engine/index.ts (default export: RtFactory). Until it is committed the glob
// is empty, the "Ray-traced" button stays hidden and the page builds and runs as before.
const engines = import.meta.glob<{ default: RtFactory }>("./engine/index.ts");

/** A ray-traced viewer, or null when this browser or this build cannot run one (the page then keeps
 * the Three.js preview). Never throws: every failure is a fallback, logged once. */
export async function createRtViewer(container: HTMLElement): Promise<RtViewer | null> {
  const load = Object.values(engines)[0];
  if (!load) return null;
  try {
    const gpu = (navigator as Navigator & { gpu?: GPU }).gpu;
    if (!gpu) return null;
    const adapter = await gpu.requestAdapter({ powerPreference: "high-performance" });
    if (!adapter) return null;
    const device = await adapter.requestDevice();
    const { default: factory } = await load();
    return await factory(container, device);
  } catch (err) {
    console.warn("Ray-traced preview unavailable, keeping the WebGL preview:", err);
    return null;
  }
}
