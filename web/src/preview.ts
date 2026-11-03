import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { PLYLoader } from "three/examples/jsm/loaders/PLYLoader.js";

export type Shape = "sphere" | "cube" | "plane" | Scan;
/** The loaded meshes (PLY files): the material study. */
export type Scan = "study";
export type LightPass = "hdri" | "key" | "raking" | "back";
/** Render passes (AOVs): the lit beauty pass, or one buffer shown on its own. */
export type Aov = "beauty" | "depth" | "normal" | "albedo" | "roughness" | "ao" | "thickness";

export interface MaterialMaps {
  albedo: string;
  normal: string;
  ao: string;
  roughness: string;
  metallic: string;
  height?: string;
  thickness?: string; // how much matter light crosses (materials made before it have none)
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
const TRI_SCALE: Record<Shape, number> = {
  sphere: REPEAT / Math.PI, cube: REPEAT / 1.5, plane: REPEAT / 2.4, study: REPEAT / 0.8,
};
// MatterLift's own material study, modelled in Blender from scripts/material_study.py (MIT; credits:
// public/models/CREDITS.md). `zUp`: the mesh stands on its z axis (three.js is y-up). `uv`: it has UVs (REPEAT tiles per UV unit, the
// density of its triplanar projection), so it takes UV mapping and displacement like the primitives.
export const SCANS: Record<Scan, { url: string; zUp: boolean; uv?: boolean }> = {
  study: { url: "models/material_study.ply", zUp: true, uv: true },
};
export const isScan = (shape: string): shape is Scan => shape in SCANS;
/** Shapes with UVs: the primitives and the study. A loaded mesh without them would always be triplanar,
 * without displacement. */
export const hasUV = (shape: string): boolean => !isScan(shape) || !!SCANS[shape].uv;
// The height map displaces the mesh for real, so silhouettes and the depth AOV show the relief.
const DISPLACEMENT = 0.035;
// The study's tiles are ~4x smaller than the sphere's: its relief shrinks with them, so a height map keeps
// the same depth for the size of its pattern (else its small pieces swell).
const DISPLACEMENT_SHAPE: Partial<Record<Shape, number>> = { study: TRI_SCALE.sphere / TRI_SCALE.study };
// Real-world scale: every shape (unit bounding sphere) is shown 1 m across, so 50 cm per unit.
const REAL_RADIUS_CM = 50;
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

/** Height for the displacement in triplanar mode (vertex shader: object position and normal to world). */
const TRI_HEIGHT_GLSL = /* glsl */ `
#ifdef USE_DISPLACEMENTMAP
uniform float triplanar;
uniform float triScale;
float triHeight(vec3 pos, vec3 nrm) {
  vec3 p = (modelMatrix * vec4(pos, 1.0)).xyz * triScale;
  vec3 w = pow(abs(normalize(mat3(modelMatrix) * nrm)), vec3(4.0));
  w /= w.x + w.y + w.z;
  return texture2D(displacementMap, p.zy).x * w.x + texture2D(displacementMap, p.xz).x * w.y + texture2D(displacementMap, p.xy).x * w.z;
}
#endif
`;
const TRI_HEIGHT_CALL = "( triplanar > 0.5 ? triHeight( transformed, objectNormal ) : texture2D( displacementMap, vDisplacementMapUv ).x )";

function addTriplanar(
  material: THREE.MeshPhysicalMaterial | THREE.MeshBasicMaterial,
  uniforms: { triplanar: { value: number }; triScale: { value: number }; triNormalScale: { value: number } },
  normal = "objectNormal", // MeshBasicMaterial has no objectNormal without an env map: "normal"
) {
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vTriPos;\nvarying vec3 vTriNormal;")
      .replace(
        "#include <worldpos_vertex>",
        "#include <worldpos_vertex>\nvTriPos = (modelMatrix * vec4(transformed, 1.0)).xyz;\n" +
          `vTriNormal = normalize(mat3(modelMatrix) * ${normal});`,
      );
    // The shader still holds #include directives here: swap each one for its chunk, patched.
    const chunk = (name: keyof typeof THREE.ShaderChunk, from: string, to: string) => {
      const patched = THREE.ShaderChunk[name].replace(from, to);
      if (patched === THREE.ShaderChunk[name]) console.warn(`triplanar: ${name} did not match`);
      shader.fragmentShader = shader.fragmentShader.replace(`#include <${name}>`, patched);
    };
    // the relief follows the projection: in triplanar mode the height map is read along the world axes
    // too, so the bumps sit under the pattern they belong to (with UVs they would not match it)
    shader.vertexShader = shader.vertexShader
      .replace("#include <displacementmap_pars_vertex>", "#include <displacementmap_pars_vertex>\n" + TRI_HEIGHT_GLSL)
      .replace(
        "#include <displacementmap_vertex>",
        THREE.ShaderChunk.displacementmap_vertex.replace("texture2D( displacementMap, vDisplacementMapUv ).x", TRI_HEIGHT_CALL),
      );
    shader.fragmentShader = shader.fragmentShader.replace("#include <common>", "#include <common>\n" + TRIPLANAR_GLSL);
    chunk("map_fragment", "texture2D( map, vMapUv )", "triTex( map, vMapUv )");
    chunk("roughnessmap_fragment", "texture2D( roughnessMap, vRoughnessMapUv )", "triTex( roughnessMap, vRoughnessMapUv )");
    chunk("metalnessmap_fragment", "texture2D( metalnessMap, vMetalnessMapUv )", "triTex( metalnessMap, vMetalnessMapUv )");
    chunk("aomap_fragment", "texture2D( aoMap, vAoMapUv )", "triTex( aoMap, vAoMapUv )");
    if (material instanceof THREE.MeshPhysicalMaterial)
      chunk("lights_physical_fragment", "texture2D( sheenColorMap, vSheenColorMapUv )", "triTex( sheenColorMap, vSheenColorMapUv )");
    chunk(
      "normal_fragment_maps",
      "normal = normalize( tbn * mapN );",
      "normal = normalize( tbn * mapN );\n" +
        "\tif ( triplanar > 0.5 ) normal = normalize( ( viewMatrix * vec4( triNormalWorld( normalMap ), 0.0 ) ).xyz );",
    );
  };
}

/** View-space depth, linear between near (white) and far (dark grey) set around the object. */
class LinearDepthMaterial extends THREE.ShaderMaterial {
  constructor() {
    super({
      uniforms: {
        near: { value: 1 },
        far: { value: 5 },
        displacementMap: { value: null as THREE.Texture | null },
        displacementScale: { value: DISPLACEMENT },
        uvTransform: { value: new THREE.Matrix3() },
        // shared with the beauty material (Preview's constructor): the depth follows the same relief
        triplanar: { value: 0 },
        triScale: { value: 1 },
      },
      vertexShader: /* glsl */ `
        #define USE_DISPLACEMENTMAP
        uniform sampler2D displacementMap;
        uniform float displacementScale;
        uniform mat3 uvTransform;
        varying float vDepth;
        ${TRI_HEIGHT_GLSL}
        void main() {
          vec2 st = (uvTransform * vec3(uv, 1.0)).xy;
          float h = triplanar > 0.5 ? triHeight(position, normal) : texture2D(displacementMap, st).r;
          vec3 p = position + normal * (h - 0.5) * displacementScale;
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
          gl_FragColor = vec4(vec3(1.0 - 0.85 * d), 1.0); // the farthest surface stays grey, apart from the black background
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
  private corner = new THREE.Vector3();
  private normalMaterial = new THREE.MeshNormalMaterial();
  private flatMaterial = new THREE.MeshBasicMaterial({ toneMapped: false });
  private textures: Partial<Record<"albedo" | "normal" | "ao" | "roughness" | "metallic" | "height" | "thickness", THREE.Texture>> = {};
  private aov: Aov = "beauty";
  private tri = { triplanar: { value: 0 }, triScale: { value: TRI_SCALE.sphere }, triNormalScale: { value: 1 } };
  private tweaks: Tweaks = { normalScale: 1, displacement: 1, tiling: 1, clay: false };
  private tileCm = 0; // real-world scale (setRealScale), 0 = off
  private shape: Shape = "sphere";
  private triplanarChosen = false;
  private scans = new Map<Scan, Promise<THREE.BufferGeometry>>();
  private scanGeometries = new Set<THREE.BufferGeometry>();
  private envMap: THREE.Texture;
  private seeThrough = false; // a transmissive material: the studio shows behind it
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
    Object.assign(this.depthMaterial.uniforms, { triplanar: this.tri.triplanar, triScale: this.tri.triScale });
    addTriplanar(this.flatMaterial, this.tri, "normal"); // the Albedo/Rough/AO/Thick passes, on loaded meshes too
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

  /** A loaded mesh, once, upright, centred and scaled to the unit sphere like the other shapes. */
  private loadScan(scan: Scan): Promise<THREE.BufferGeometry> {
    const cached = this.scans.get(scan);
    if (cached) return cached;
    const loading = new PLYLoader().loadAsync(SCANS[scan].url).then((g) => {
      if (SCANS[scan].zUp) g.rotateX(-Math.PI / 2);
      // the study ships smooth normals (recomputed, its UV seams would show); a mesh without them gets them
      if (!g.attributes.normal) g.computeVertexNormals();
      g.computeBoundingSphere();
      const { center, radius } = g.boundingSphere!;
      g.translate(-center.x, -center.y, -center.z);
      g.scale(1 / radius, 1 / radius, 1 / radius);
      g.computeBoundingSphere();
      this.scanGeometries.add(g);
      return g;
    }).catch((err) => {
      this.scans.delete(scan); // a failed download is not cached: the next click tries again
      throw err;
    });
    this.scans.set(scan, loading);
    return loading;
  }

  async setShape(shape: Shape) {
    this.shape = shape;
    const geometry = isScan(shape) ? await this.loadScan(shape) : this.geometry(shape);
    // a later click won while the scan was loading
    if (this.shape !== shape) return;
    // the cached scans are kept for the next visit
    if (!this.scanGeometries.has(this.mesh.geometry)) this.mesh.geometry.dispose();
    this.mesh.geometry = geometry;
    this.mesh.rotation.set(shape === "plane" ? -0.9 : 0, 0, 0);
    this.applyTiling();
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

  /** Triplanar projection on or off (beauty pass). A loaded mesh without UVs would always be triplanar;
   * the choice applies to every shape with UVs. */
  setTriplanar(on: boolean) {
    this.triplanarChosen = on;
    this.applyTriplanar();
  }

  private applyTriplanar() {
    this.tri.triplanar.value = this.triplanarChosen || !hasUV(this.shape) ? 1 : 0;
  }

  /** The height map displaces along UVs: none on a loaded mesh without them. */
  private displacement(): number {
    return hasUV(this.shape) ? DISPLACEMENT * (DISPLACEMENT_SHAPE[this.shape] ?? 1) * this.tweaks.displacement : 0;
  }

  private applyDisplacement() {
    this.material.displacementScale = this.displacement();
    this.material.displacementBias = -this.material.displacementScale / 2;
  }

  /** Real-world scale: one tile covers `tileCm` (the plan's tile_size_cm) on a shape shown 1 m across;
   * 0 goes back to the tiling slider. */
  setRealScale(tileCm: number) {
    this.tileCm = tileCm;
    this.applyTiling();
  }

  /** Tiles per unit of the triplanar density: the slider, or the real-world scale for this shape. */
  private tiling(): number {
    return this.tileCm > 0 ? REAL_RADIUS_CM / this.tileCm / TRI_SCALE[this.shape] : this.tweaks.tiling;
  }

  private applyTiling() {
    const k = this.tiling();
    this.tri.triScale.value = TRI_SCALE[this.shape] * k;
    for (const t of Object.values(this.textures)) {
      t?.repeat.set(REPEAT * k, REPEAT * k);
      t?.updateMatrix();
    }
  }

  setTweaks(tweaks: Tweaks) {
    this.tweaks = { ...tweaks };
    const m = this.material;
    m.normalScale.set(tweaks.normalScale, tweaks.normalScale);
    this.tri.triNormalScale.value = tweaks.normalScale;
    this.applyTiling();
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
    m.sheenColorMap = clay ? null : (t.albedo ?? null); // the fibres' sheen takes their colour
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
    this.scene.background = aov !== "beauty" ? new THREE.Color(0x000000) : this.seeThrough ? this.envMap : BACKGROUND;
    // dimmed and sharp: the studio's light panels stay bright against it, so the refraction has contrast
    this.scene.backgroundIntensity = 0.3;
    this.scene.backgroundBlurriness = 0;
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
    const u = this.depthMaterial.uniforms;
    if (isScan(this.shape)) {
      // A loaded mesh (the study) shows surfaces down to its back: its whole depth, from its
      // bounding box seen along the view (tighter than its sphere, so the depth keeps contrast).
      const g = this.mesh.geometry;
      if (!g.boundingBox) g.computeBoundingBox();
      const { min, max } = g.boundingBox!;
      const view = this.camera.matrixWorldInverse.clone().multiply(this.mesh.matrixWorld);
      let near = Infinity, far = 0;
      for (let i = 0; i < 8; i++) {
        const z = -this.corner.set(i & 1 ? max.x : min.x, i & 2 ? max.y : min.y, i & 4 ? max.z : min.z).applyMatrix4(view).z;
        near = Math.min(near, z);
        far = Math.max(far, z);
      }
      u.near.value = Math.max(0.01, near);
      u.far.value = far;
      return;
    }
    // Sphere, cube, plane: the camera only sees their front, so the range is spent there and the
    // relief reads too.
    const dist = this.camera.position.distanceTo(this.mesh.position);
    const r = sphere.radius + DISPLACEMENT;
    u.near.value = Math.max(0.01, dist - r);
    u.far.value = dist - r * 0.25;
  }

  /** PNG of the current view and pass. */
  snapshot(): string {
    this.renderer.render(this.scene, this.camera);
    return this.renderer.domElement.toDataURL("image/png");
  }

  private async texture(url: string, color = false): Promise<THREE.Texture> {
    const t = await this.loader.loadAsync(url);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(REPEAT * this.tiling(), REPEAT * this.tiling());
    t.updateMatrix();
    t.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
    t.colorSpace = color ? THREE.SRGBColorSpace : THREE.NoColorSpace;
    return t;
  }

  async load(maps: MaterialMaps, shading?: Partial<Shading>) {
    const [albedo, normal, ao, roughness, metallic, height, thickness] = await Promise.all([
      this.texture(maps.albedo, true),
      this.texture(maps.normal),
      this.texture(maps.ao),
      this.texture(maps.roughness),
      this.texture(maps.metallic),
      maps.height ? this.texture(maps.height) : Promise.resolve(undefined),
      maps.thickness ? this.texture(maps.thickness) : Promise.resolve(undefined),
    ]);
    for (const old of Object.values(this.textures)) old?.dispose();
    this.textures = { albedo, normal, ao, roughness, metallic, height, thickness };
    const m = this.material;
    Object.assign(m, {
      map: albedo,
      normalMap: normal,
      aoMap: ao,
      roughnessMap: roughness,
      metalnessMap: metallic,
      displacementMap: height ?? null,
      thicknessMap: thickness ?? null, // used by transmission: thin parts refract and tint less
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
    m.thickness = m.transmission > 0 ? 0.5 : 0;
    m.ior = s.ior ?? 1.5;
    // Colours fanning out through clear matter: barely in glass, the "fire" of a diamond (IOR 2.42).
    m.dispersion = m.transmission > 0 ? Math.max(0, m.ior - 1.4) * 0.6 : 0;
    // See-through materials refract what is behind them: the studio, not the dark backdrop.
    this.seeThrough = m.transmission > 0.01;
    this.setAov(this.aov);
    m.clearcoat = s.clearcoat ?? 0;
    m.clearcoatRoughness = s.clearcoat_roughness ?? 0.1;
    m.sheen = s.sheen ?? 0;
    // three's sheen colour is black by default, which turns the lobe off whatever `sheen` says: white,
    // tinted by the albedo (sheenColorMap, applyClay); a soft, wide lobe as on fur, velvet and felt
    m.sheenColor.setScalar(1);
    m.sheenRoughness = 0.5;
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
