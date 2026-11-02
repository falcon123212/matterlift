import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { PLYLoader } from "three/examples/jsm/loaders/PLYLoader.js";

export type Shape = "sphere" | "cube" | "plane" | "dragon";
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

/** Look-dev controls shared by every shape (and sent to the live renderer): normal and
 * displacement strength, tiling, and a clay pass that drops colour and metal. */
export interface Tweaks {
  normalScale: number;
  displacement: number;
  tiling: number;
  clay: boolean;
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
// Triplanar tiles per world unit, matching each shape's UV density (REPEAT tiles across its UVs).
const TRI_SCALE: Record<Shape, number> = { sphere: REPEAT / Math.PI, cube: REPEAT / 1.5, plane: REPEAT / 2.4, dragon: REPEAT / 0.8 };
// Stanford dragon (Stanford 3D Scanning Repository), decimated to 150k triangles. No UVs: shown triplanar only.
const DRAGON_URL = "/models/stanford_dragon.ply";
// The height map displaces the mesh for real, so silhouettes and the depth AOV show the relief.
const DISPLACEMENT = 0.035;
const BACKGROUND = new THREE.Color(0x141416);

/** Triplanar projection, injected into MeshPhysicalMaterial: every map is sampled along the three
 * world axes and blended by the surface normal, so no UV layout is needed and nothing stretches
 * (sphere poles, arbitrary game meshes). Normals use the whiteout blend, in world space. */
const TRIPLANAR_GLSL = /* glsl */ `
uniform float triplanar;
uniform float triScale;
uniform float triNormalScale;
varying vec3 vTriPos;
varying vec3 vTriNormal;
vec3 triWeights() {
  vec3 w = pow(abs(normalize(vTriNormal)), vec3(4.0));
  return w / (w.x + w.y + w.z);
}
vec4 triTex(sampler2D t, vec2 uv) {
  vec4 c = texture2D(t, uv);
  if (triplanar > 0.5) {
    vec3 p = vTriPos * triScale;
    vec3 w = triWeights();
    c = texture2D(t, p.zy) * w.x + texture2D(t, p.xz) * w.y + texture2D(t, p.xy) * w.z;
  }
  return c;
}
vec3 triNormalWorld(sampler2D t) {
  vec3 n = normalize(vTriNormal);
  vec3 p = vTriPos * triScale;
  vec3 w = triWeights();
  vec3 tx = texture2D(t, p.zy).xyz * 2.0 - 1.0;
  vec3 ty = texture2D(t, p.xz).xyz * 2.0 - 1.0;
  vec3 tz = texture2D(t, p.xy).xyz * 2.0 - 1.0;
  tx.xy *= triNormalScale;
  ty.xy *= triNormalScale;
  tz.xy *= triNormalScale;
  tx = vec3(tx.xy + n.zy, abs(tx.z) * n.x);
  ty = vec3(ty.xy + n.xz, abs(ty.z) * n.y);
  tz = vec3(tz.xy + n.xy, abs(tz.z) * n.z);
  return normalize(tx.zyx * w.x + ty.xzy * w.y + tz.xyz * w.z);
}
`;

function addTriplanar(
  material: THREE.MeshPhysicalMaterial,
  uniforms: { triplanar: { value: number }; triScale: { value: number }; triNormalScale: { value: number } },
) {
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vTriPos;\nvarying vec3 vTriNormal;")
      .replace(
        "#include <worldpos_vertex>",
        "#include <worldpos_vertex>\nvTriPos = (modelMatrix * vec4(transformed, 1.0)).xyz;\n" +
          "vTriNormal = normalize(mat3(modelMatrix) * objectNormal);",
      );
    // The shader still holds #include directives here: swap each one for its chunk, patched.
    const chunk = (name: keyof typeof THREE.ShaderChunk, from: string, to: string) => {
      const patched = THREE.ShaderChunk[name].replace(from, to);
      if (patched === THREE.ShaderChunk[name]) console.warn(`triplanar: ${name} did not match`);
      shader.fragmentShader = shader.fragmentShader.replace(`#include <${name}>`, patched);
    };
    shader.fragmentShader = shader.fragmentShader.replace("#include <common>", "#include <common>\n" + TRIPLANAR_GLSL);
    chunk("map_fragment", "texture2D( map, vMapUv )", "triTex( map, vMapUv )");
    chunk("roughnessmap_fragment", "texture2D( roughnessMap, vRoughnessMapUv )", "triTex( roughnessMap, vRoughnessMapUv )");
    chunk("metalnessmap_fragment", "texture2D( metalnessMap, vMetalnessMapUv )", "triTex( metalnessMap, vMetalnessMapUv )");
    chunk("aomap_fragment", "texture2D( aoMap, vAoMapUv )", "triTex( aoMap, vAoMapUv )");
    chunk(
      "normal_fragment_maps",
      "normal = normalize( tbn * mapN );",
      "normal = normalize( tbn * mapN );\n" +
        "\tif ( triplanar > 0.5 ) normal = normalize( ( viewMatrix * vec4( triNormalWorld( normalMap ), 0.0 ) ).xyz );",
    );
  };
}

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
  private tri = { triplanar: { value: 0 }, triScale: { value: TRI_SCALE.sphere }, triNormalScale: { value: 1 } };
  private tweaks: Tweaks = { normalScale: 1, displacement: 1, tiling: 1, clay: false };
  private shape: Shape = "sphere";
  private triplanarChosen = false;
  private dragon?: Promise<THREE.BufferGeometry>;
  private dragonGeometry?: THREE.BufferGeometry;
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

    addTriplanar(this.material, this.tri);
    this.mesh = new THREE.Mesh(this.geometry("sphere"), this.material);
    this.scene.add(this.mesh);
    this.setLight("hdri");

    new ResizeObserver(() => this.resize()).observe(host);
    this.resize();
    this.renderer.setAnimationLoop(this.frame);
  }

  private frame = () => {
    this.controls.update();
    if (this.aov === "depth") this.fitDepthRange();
    this.renderer.render(this.scene, this.camera);
  };

  /** Stop drawing (and hide the canvas) while another view covers the preview. */
  setActive(on: boolean) {
    this.renderer.setAnimationLoop(on ? this.frame : null);
    this.renderer.domElement.style.visibility = on ? "" : "hidden";
  }

  private geometry(shape: Shape): THREE.BufferGeometry {
    // Dense enough for the displacement to read.
    if (shape === "cube") return new THREE.BoxGeometry(1.5, 1.5, 1.5, 96, 96, 96);
    if (shape === "plane") return new THREE.PlaneGeometry(2.4, 2.4, 256, 256);
    return new THREE.SphereGeometry(1, 256, 128);
  }

  /** The dragon scan, loaded once, centred and scaled to the unit sphere like the other shapes. */
  private loadDragon(): Promise<THREE.BufferGeometry> {
    this.dragon ??= new PLYLoader().loadAsync(DRAGON_URL).then((g) => {
      g.computeVertexNormals();
      g.computeBoundingSphere();
      const { center, radius } = g.boundingSphere!;
      g.translate(-center.x, -center.y, -center.z);
      g.scale(1 / radius, 1 / radius, 1 / radius);
      g.computeBoundingSphere();
      this.dragonGeometry = g;
      return g;
    });
    return this.dragon;
  }

  async setShape(shape: Shape) {
    this.shape = shape;
    const geometry = shape === "dragon" ? await this.loadDragon() : this.geometry(shape);
    // a later click won while the dragon was loading
    if (this.shape !== shape) return;
    // the cached dragon is kept for the next visit
    if (this.mesh.geometry !== this.dragonGeometry) this.mesh.geometry.dispose();
    this.mesh.geometry = geometry;
    this.mesh.rotation.set(shape === "plane" ? -0.9 : 0, 0, 0);
    this.tri.triScale.value = TRI_SCALE[shape] * this.tweaks.tiling;
    this.applyTriplanar();
    this.applyDisplacement();
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

  /** Triplanar projection on or off (beauty pass). The dragon has no UVs, so it is always triplanar;
   * the choice comes back on the other shapes. */
  setTriplanar(on: boolean) {
    this.triplanarChosen = on;
    this.applyTriplanar();
  }

  private applyTriplanar() {
    this.tri.triplanar.value = this.triplanarChosen || this.shape === "dragon" ? 1 : 0;
  }

  /** The height map displaces along UVs, which the dragon lacks: no displacement there. */
  private displacement(): number {
    return this.shape === "dragon" ? 0 : DISPLACEMENT * this.tweaks.displacement;
  }

  private applyDisplacement() {
    this.material.displacementScale = this.displacement();
    this.material.displacementBias = -this.material.displacementScale / 2;
  }

  setTweaks(tweaks: Tweaks) {
    this.tweaks = { ...tweaks };
    const m = this.material;
    m.normalScale.set(tweaks.normalScale, tweaks.normalScale);
    this.tri.triNormalScale.value = tweaks.normalScale;
    this.tri.triScale.value = TRI_SCALE[this.shape] * tweaks.tiling;
    for (const t of Object.values(this.textures)) {
      t?.repeat.set(REPEAT * tweaks.tiling, REPEAT * tweaks.tiling);
      t?.updateMatrix();
    }
    this.applyDisplacement();
    this.applyClay();
    this.setAov(this.aov);
  }

  /** Clay: neutral grey, no metal, uniform roughness; the normal and height maps still shape it. */
  private applyClay() {
    const m = this.material;
    const t = this.textures;
    const clay = this.tweaks.clay || !t.albedo;
    m.map = clay ? null : t.albedo!;
    m.metalnessMap = clay ? null : (t.metallic ?? null);
    m.roughnessMap = clay ? null : (t.roughness ?? null);
    m.color.set(clay && t.albedo ? 0xb4b4b4 : t.albedo ? 0xffffff : 0xbbbbbb);
    m.metalness = clay ? 0 : 1;
    m.roughness = clay ? 0.6 : 1;
    m.needsUpdate = true;
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
      this.depthMaterial.uniforms.displacementScale.value = t.height ? this.displacement() : 0;
      this.mesh.material = this.depthMaterial;
    } else if (aov === "normal") {
      Object.assign(this.normalMaterial, {
        normalMap: t.normal ?? null,
        displacementMap: t.height ?? null,
        displacementScale: this.displacement(),
        displacementBias: -this.displacement() / 2,
        normalScale: new THREE.Vector2(this.tweaks.normalScale, this.tweaks.normalScale),
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
    t.repeat.set(REPEAT * this.tweaks.tiling, REPEAT * this.tweaks.tiling);
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
    });
    this.applyDisplacement();
    this.applyClay();
    m.aoMapIntensity = 1;
    m.normalScale.set(this.tweaks.normalScale, this.tweaks.normalScale);
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
