import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";

export type Shape = "sphere" | "cube" | "plane";
export type LightPass = "hdri" | "key" | "raking" | "back";

export interface MaterialMaps {
  albedo: string;
  normal: string;
  ao: string;
  roughness: string;
  metallic: string;
  height?: string;
}

export interface Shading {
  transmission: number;
  ior: number;
  clearcoat: number;
  clearcoat_roughness: number;
  sheen: number;
  anisotropy: number;
}

const REPEAT = 2;

export class Preview {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private controls: OrbitControls;
  private mesh: THREE.Mesh;
  private material = new THREE.MeshPhysicalMaterial({ color: 0xbbbbbb, roughness: 0.6 });
  private envMap: THREE.Texture;
  private sun = new THREE.DirectionalLight(0xffffff, 3);
  private loader = new THREE.TextureLoader();

  constructor(private host: HTMLElement) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.appendChild(this.renderer.domElement);

    this.camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
    this.camera.position.set(0, 0.3, 3.4);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;

    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.envMap = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    this.scene.background = new THREE.Color(0x141416);
    this.scene.add(this.sun);

    this.mesh = new THREE.Mesh(this.geometry("sphere"), this.material);
    this.scene.add(this.mesh);
    this.setLight("hdri");

    new ResizeObserver(() => this.resize()).observe(host);
    this.resize();
    this.renderer.setAnimationLoop(() => {
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
    });
  }

  private geometry(shape: Shape): THREE.BufferGeometry {
    if (shape === "cube") return new THREE.BoxGeometry(1.5, 1.5, 1.5);
    if (shape === "plane") return new THREE.PlaneGeometry(2.4, 2.4);
    return new THREE.SphereGeometry(1, 128, 64);
  }

  setShape(shape: Shape) {
    this.mesh.geometry.dispose();
    this.mesh.geometry = this.geometry(shape);
    this.mesh.rotation.set(shape === "plane" ? -0.9 : 0, 0, 0);
  }

  /** Lighting passes: HDRI for the overall read, key/raking/back to check relief and seams. */
  setLight(pass: LightPass) {
    const env = pass === "hdri" ? 1 : 0.15;
    this.scene.environment = this.envMap;
    this.scene.environmentIntensity = env;
    this.sun.visible = pass !== "hdri";
    const pos: Record<LightPass, [number, number, number]> = {
      hdri: [0, 0, 0],
      key: [2, 2, 3],
      raking: [-4, 0.4, 0.6],
      back: [0, 1.5, -4],
    };
    this.sun.position.set(...pos[pass]);
  }

  private async texture(url: string, color = false): Promise<THREE.Texture> {
    const t = await this.loader.loadAsync(url);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(REPEAT, REPEAT);
    t.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
    t.colorSpace = color ? THREE.SRGBColorSpace : THREE.NoColorSpace;
    return t;
  }

  async load(maps: MaterialMaps, shading?: Partial<Shading>) {
    const [map, normalMap, aoMap, roughnessMap, metalnessMap] = await Promise.all([
      this.texture(maps.albedo, true),
      this.texture(maps.normal),
      this.texture(maps.ao),
      this.texture(maps.roughness),
      this.texture(maps.metallic),
    ]);
    const m = this.material;
    for (const old of [m.map, m.normalMap, m.aoMap, m.roughnessMap, m.metalnessMap]) old?.dispose();
    Object.assign(m, { map, normalMap, aoMap, roughnessMap, metalnessMap });
    m.color.set(0xffffff);
    m.roughness = 1;
    m.metalness = 1;
    m.aoMapIntensity = 1;
    m.normalScale.set(1, 1);
    if (shading) this.setShading(shading);
    m.needsUpdate = true;
  }

  setShading(s: Partial<Shading>) {
    const m = this.material;
    m.transmission = s.transmission ?? 0;
    m.ior = s.ior ?? 1.5;
    m.clearcoat = s.clearcoat ?? 0;
    m.clearcoatRoughness = s.clearcoat_roughness ?? 0.1;
    m.sheen = s.sheen ?? 0;
    m.anisotropy = s.anisotropy ?? 0;
  }

  private resize() {
    const { clientWidth: w, clientHeight: h } = this.host;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    // Keep the whole object in frame when the viewport is taller than wide.
    this.camera.position.setLength(3.4 / Math.min(this.camera.aspect, 1));
  }
}
