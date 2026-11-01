import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";

export type Shape = "sphere" | "cube" | "plane";
export type LightPass = "hdri" | "key" | "raking" | "back";
/** Render passes (AOVs): the lit beauty pass, or one buffer shown on its own. */
export type Aov = "beauty" | "depth" | "normal" | "albedo" | "roughness" | "ao";

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
// The height map displaces the mesh for real, so silhouettes and the depth AOV show the relief.
const DISPLACEMENT = 0.035;
const BACKGROUND = new THREE.Color(0x141416);

/** View-space depth, linear between near (white) and far (black) set around the object. */
class LinearDepthMaterial extends THREE.ShaderMaterial {
  constructor() {
    super({
      uniforms: {
        near: { value: 1 },
        far: { value: 5 },
        displacementMap: { value: null as THREE.Texture | null },
        displacementScale: { value: DISPLACEMENT },
        uvTransform: { value: new THREE.Matrix3() },
      },
      vertexShader: /* glsl */ `
        uniform sampler2D displacementMap;
        uniform float displacementScale;
        uniform mat3 uvTransform;
        varying float vDepth;
        void main() {
          vec2 st = (uvTransform * vec3(uv, 1.0)).xy;
          vec3 p = position + normal * (texture2D(displacementMap, st).r - 0.5) * displacementScale;
          vec4 view = modelViewMatrix * vec4(p, 1.0);
          vDepth = -view.z;
          gl_Position = projectionMatrix * view;
        }`,
      fragmentShader: /* glsl */ `
        uniform float near;
        uniform float far;
        varying float vDepth;
        void main() {
          float d = clamp((vDepth - near) / (far - near), 0.0, 1.0);
          gl_FragColor = vec4(vec3(1.0 - d), 1.0);
        }`,
    });
    this.toneMapped = false;
  }
}

export class Preview {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private controls: OrbitControls;
  private mesh: THREE.Mesh;
  private material = new THREE.MeshPhysicalMaterial({ color: 0xbbbbbb, roughness: 0.6 });
  private depthMaterial = new LinearDepthMaterial();
  private normalMaterial = new THREE.MeshNormalMaterial();
  private flatMaterial = new THREE.MeshBasicMaterial({ toneMapped: false });
  private textures: Partial<Record<"albedo" | "normal" | "ao" | "roughness" | "metallic" | "height", THREE.Texture>> = {};
  private aov: Aov = "beauty";
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
    this.scene.background = BACKGROUND;
    this.scene.add(this.sun);

    this.mesh = new THREE.Mesh(this.geometry("sphere"), this.material);
    this.scene.add(this.mesh);
    this.setLight("hdri");

    new ResizeObserver(() => this.resize()).observe(host);
    this.resize();
    this.renderer.setAnimationLoop(() => {
      this.controls.update();
      if (this.aov === "depth") this.fitDepthRange();
      this.renderer.render(this.scene, this.camera);
    });
  }

  private geometry(shape: Shape): THREE.BufferGeometry {
    // Dense enough for the displacement to read.
    if (shape === "cube") return new THREE.BoxGeometry(1.5, 1.5, 1.5, 96, 96, 96);
    if (shape === "plane") return new THREE.PlaneGeometry(2.4, 2.4, 256, 256);
    return new THREE.SphereGeometry(1, 256, 128);
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

  /** Show one render pass. Lighting choices only affect the beauty pass. */
  setAov(aov: Aov) {
    this.aov = aov;
    const t = this.textures;
    this.scene.background = aov === "beauty" ? BACKGROUND : new THREE.Color(0x000000);
    if (aov === "beauty") {
      this.mesh.material = this.material;
    } else if (aov === "depth") {
      this.depthMaterial.uniforms.displacementMap.value = t.height ?? null;
      if (t.height) this.depthMaterial.uniforms.uvTransform.value.copy(t.height.matrix);
      this.depthMaterial.uniforms.displacementScale.value = t.height ? DISPLACEMENT : 0;
      this.mesh.material = this.depthMaterial;
    } else if (aov === "normal") {
      Object.assign(this.normalMaterial, {
        normalMap: t.normal ?? null,
        displacementMap: t.height ?? null,
        displacementScale: DISPLACEMENT,
        displacementBias: -DISPLACEMENT / 2,
      });
      this.normalMaterial.needsUpdate = true;
      this.mesh.material = this.normalMaterial;
    } else {
      this.flatMaterial.map = t[aov] ?? null;
      this.flatMaterial.needsUpdate = true;
      this.mesh.material = this.flatMaterial;
    }
  }

  /** Near/far hugging the object so the depth pass uses its whole range. */
  private fitDepthRange() {
    const sphere = (this.mesh.geometry.boundingSphere ??
      (this.mesh.geometry.computeBoundingSphere(), this.mesh.geometry.boundingSphere))!;
    const dist = this.camera.position.distanceTo(this.mesh.position);
    // Front half only: the range is spent on what the camera sees, so the relief reads too.
    const r = sphere.radius + DISPLACEMENT;
    this.depthMaterial.uniforms.near.value = Math.max(0.01, dist - r);
    this.depthMaterial.uniforms.far.value = dist - r * 0.25;
  }

  /** PNG of the current view and pass. */
  snapshot(): string {
    this.renderer.render(this.scene, this.camera);
    return this.renderer.domElement.toDataURL("image/png");
  }

  private async texture(url: string, color = false): Promise<THREE.Texture> {
    const t = await this.loader.loadAsync(url);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(REPEAT, REPEAT);
    t.updateMatrix();
    t.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
    t.colorSpace = color ? THREE.SRGBColorSpace : THREE.NoColorSpace;
    return t;
  }

  async load(maps: MaterialMaps, shading?: Partial<Shading>) {
    const [albedo, normal, ao, roughness, metallic, height] = await Promise.all([
      this.texture(maps.albedo, true),
      this.texture(maps.normal),
      this.texture(maps.ao),
      this.texture(maps.roughness),
      this.texture(maps.metallic),
      maps.height ? this.texture(maps.height) : Promise.resolve(undefined),
    ]);
    for (const old of Object.values(this.textures)) old?.dispose();
    this.textures = { albedo, normal, ao, roughness, metallic, height };
    const m = this.material;
    Object.assign(m, {
      map: albedo,
      normalMap: normal,
      aoMap: ao,
      roughnessMap: roughness,
      metalnessMap: metallic,
      displacementMap: height ?? null,
      displacementScale: DISPLACEMENT,
      displacementBias: -DISPLACEMENT / 2,
    });
    m.color.set(0xffffff);
    m.roughness = 1;
    m.metalness = 1;
    m.aoMapIntensity = 1;
    m.normalScale.set(1, 1);
    if (shading) this.setShading(shading);
    m.needsUpdate = true;
    this.setAov(this.aov);
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
