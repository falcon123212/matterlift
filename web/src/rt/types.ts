import type { MaterialMaps, Shading } from "../preview";

/** What the page needs from a ray-traced preview engine (HyperWave WebGPU port, kept in ./engine).
 * The engine owns its canvas and its camera; the page only feeds it materials and reads images. */
export interface RtViewer {
  /** Load MatterLift maps onto the preview objects. Meshes without UVs use triplanar projection. */
  setMaterial(maps: MaterialMaps, shading: Shading | null): Promise<void>;
  /** Show or hide the engine's canvas (the Three.js preview is hidden while it is shown). */
  setVisible(on: boolean): void;
  /** Samples accumulated since the camera last moved: the image refines while the camera is still. */
  readonly samples: number;
  /** PNG data URL of the current, accumulated image. */
  capture(): string;
  dispose(): void;
}

export type RtFactory = (container: HTMLElement, device: GPUDevice) => Promise<RtViewer>;
