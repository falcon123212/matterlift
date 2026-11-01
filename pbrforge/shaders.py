"""Engine shaders that keep the studio controls live instead of baking them.

The packaged textures have the detail layer and the wear baked in. These exports ship the layers
apart (clean base maps, one detail tile, a wear/grain mask) plus a shader that recombines them with
the same maths as pbrforge.maps, so the defaults look identical and every control stays a slider:
tiling, relief, detail strength and scale, wear, triplanar projection.

- Godot 4: <stem>.gdshader + <stem>_shader.tres (ShaderMaterial with the textures assigned)
- Blender 4/5: <stem>_blender.py, run it to build the node tree (Value nodes are the sliders)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from . import detail, io, maps
from .maps import MapParams

DETAIL_TILE = 512


def layers(albedo: np.ndarray, p: MapParams, size: int, guide: np.ndarray | None) -> dict[str, np.ndarray]:
    """Clean base maps (no detail, no wear) plus the detail tile and the wear/grain mask."""
    base_params = MapParams(**{**p.__dict__, "detail_kind": "none", "wear": 0.0})
    base = maps.derive(albedo, base_params, size=size, height_guide=guide)
    edges, cavities = maps.edge_wear(base["height"], base["ao"])
    grain = maps.grain_along_x(base["albedo"])
    kind = p.detail_kind if p.detail_kind in detail.KINDS else "none"
    dh = detail.detail_height(kind, DETAIL_TILE) if kind != "none" else np.zeros((DETAIL_TILE,) * 2, np.float32)
    return {
        **base,
        "wear_mask": np.stack([edges, cavities, grain], -1),  # R edges, G cavities, B grain along X
        "detail_height": dh * 0.5 + 0.5,
        "detail_normal": maps.normal(dh * 0.5 + 0.5, maps.DETAIL_GAIN),
    }


def _defaults(p: MapParams, shading: dict) -> dict[str, float]:
    k = detail.KIND_GAIN.get(p.detail_kind, 0.0) * p.detail_strength
    return {
        "uv_scale": 1.0, "normal_strength": 1.0, "detail_strength": round(k, 3),
        "detail_repeats": float(p.detail_repeats), "wear": round(p.wear, 3),
        "clearcoat": shading.get("clearcoat", 0.0), "clearcoat_roughness": shading.get("clearcoat_roughness", 0.1),
        "anisotropy": shading.get("anisotropy", 0.0), "sss": shading.get("subsurface", 0.0),
        "rim": shading.get("sheen", 0.0),
        "specular": min(1.0, ((shading.get("ior", 1.5) - 1) / (shading.get("ior", 1.5) + 1)) ** 2 / 0.08),
    }


GDSHADER = """// MatterLift material shader for Godot 4: {name}
// Base maps + live controls. Defaults reproduce the packaged textures exactly; move the sliders
// to change tiling, relief, detail and wear in the editor, no regeneration needed.
shader_type spatial;
render_mode blend_mix, depth_draw_opaque, cull_back, diffuse_burley, specular_schlick_ggx;

group_uniforms maps;
uniform sampler2D albedo_tex : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D normal_tex : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D orm_tex : hint_default_white, filter_linear_mipmap_anisotropic, repeat_enable; // R ao, G roughness, B metallic
uniform sampler2D wear_tex : hint_default_black, filter_linear_mipmap, repeat_enable; // R edges, G cavities, B grain along X
uniform sampler2D detail_normal_tex : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;

group_uniforms controls;
uniform float uv_scale : hint_range(0.1, 16.0) = {uv_scale};
uniform float normal_strength : hint_range(0.0, 3.0) = {normal_strength};
uniform float detail_strength : hint_range(0.0, 1.0) = {detail_strength};
uniform float detail_repeats : hint_range(1.0, 32.0) = {detail_repeats};
uniform float wear : hint_range(0.0, 1.0) = {wear};
uniform float ao_strength : hint_range(0.0, 1.0) = 1.0;
uniform bool triplanar = false;
uniform float triplanar_scale : hint_range(0.05, 8.0) = 1.0;
uniform float triplanar_sharpness : hint_range(1.0, 16.0) = 4.0;

group_uniforms shading;
uniform float clearcoat_amount : hint_range(0.0, 1.0) = {clearcoat};
uniform float clearcoat_gloss : hint_range(0.0, 1.0) = {clearcoat_gloss};
uniform float anisotropy_amount : hint_range(-1.0, 1.0) = {anisotropy};
uniform float sss : hint_range(0.0, 1.0) = {sss};
uniform float rim_amount : hint_range(0.0, 1.0) = {rim};
uniform float specular_amount : hint_range(0.0, 1.0) = {specular};

varying vec3 world_pos;
varying vec3 world_nrm;

void vertex() {{
	world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	world_nrm = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
}}

vec3 tri_weights(vec3 n) {{
	vec3 w = pow(abs(n), vec3(triplanar_sharpness));
	return w / (w.x + w.y + w.z);
}}

// One function per texture: Godot will not pass samplers with different hints to one parameter.
vec3 tri_albedo(vec3 p, vec3 w) {{
	return (texture(albedo_tex, p.zy) * w.x + texture(albedo_tex, p.xz) * w.y + texture(albedo_tex, p.xy) * w.z).rgb;
}}
vec3 tri_orm(vec3 p, vec3 w) {{
	return (texture(orm_tex, p.zy) * w.x + texture(orm_tex, p.xz) * w.y + texture(orm_tex, p.xy) * w.z).rgb;
}}
vec3 tri_wear(vec3 p, vec3 w) {{
	return (texture(wear_tex, p.zy) * w.x + texture(wear_tex, p.xz) * w.y + texture(wear_tex, p.xy) * w.z).rgb;
}}

// Whiteout blend of three tangent-space normal samples into a world-space normal.
vec3 tri_normal(vec3 p, vec3 n, vec3 w) {{
	vec3 tx = texture(normal_tex, p.zy).xyz * 2.0 - 1.0;
	vec3 ty = texture(normal_tex, p.xz).xyz * 2.0 - 1.0;
	vec3 tz = texture(normal_tex, p.xy).xyz * 2.0 - 1.0;
	tx = vec3(tx.xy * normal_strength + n.zy, abs(tx.z) * n.x);
	ty = vec3(ty.xy * normal_strength + n.xz, abs(ty.z) * n.y);
	tz = vec3(tz.xy * normal_strength + n.xy, abs(tz.z) * n.z);
	return normalize(tx.zyx * w.x + ty.xzy * w.y + tz.xyz * w.z);
}}

void fragment() {{
	vec2 uv = UV * uv_scale;
	vec3 tp = world_pos * triplanar_scale;
	vec3 tw = tri_weights(world_nrm);
	vec3 albedo = triplanar ? tri_albedo(tp, tw) : texture(albedo_tex, uv).rgb;
	vec3 orm = triplanar ? tri_orm(tp, tw) : texture(orm_tex, uv).rgb;
	vec3 wm = triplanar ? tri_wear(tp, tw) : texture(wear_tex, uv).rgb;

	// Wear, as pbrforge.maps.apply_wear: rubbed edges lighter, less saturated, smoother;
	// cavities darker and rougher.
	float e = wm.r * wear * 0.5;
	float c = wm.g * wear * 0.35;
	float grey = (albedo.r + albedo.g + albedo.b) / 3.0;
	albedo = mix(albedo, 0.6 * albedo + 0.4 * vec3(grey) + 0.12, e) * (1.0 - c * 0.6);
	float rough = clamp(orm.g - wm.r * wear * 0.18 + wm.g * wear * 0.1, 0.02, 1.0);

	ALBEDO = clamp(albedo, 0.0, 1.0);
	ROUGHNESS = rough;
	METALLIC = orm.b;
	AO = orm.r;
	AO_LIGHT_AFFECT = ao_strength;
	SPECULAR = specular_amount;
	CLEARCOAT = clearcoat_amount;
	CLEARCOAT_ROUGHNESS = 1.0 - clearcoat_gloss;
	ANISOTROPY = anisotropy_amount;
	SSS_STRENGTH = sss;
	RIM = rim_amount;
	RIM_TINT = 0.5;

	if (triplanar) {{
		NORMAL = normalize((VIEW_MATRIX * vec4(tri_normal(tp, normalize(world_nrm), tw), 0.0)).xyz);
	}} else {{
		// Macro normal, then the detail tile along the grain (blend with its transpose), UDN blend.
		vec3 n = texture(normal_tex, uv).xyz * 2.0 - 1.0;
		n.xy *= normal_strength;
		vec2 duv = uv * detail_repeats;
		vec3 d_x = texture(detail_normal_tex, duv).xyz * 2.0 - 1.0;
		vec3 d_y = texture(detail_normal_tex, duv.yx).xyz * 2.0 - 1.0;
		d_y.xy = d_y.yx;
		vec3 d = mix(d_y, d_x, wm.b);
		n = normalize(vec3(n.xy + d.xy * detail_strength, n.z));
		NORMAL_MAP = n * 0.5 + 0.5;
		NORMAL_MAP_DEPTH = 1.0;
	}}
}}
"""


def write_godot(d: Path, stem: str, files: dict[str, str], p: MapParams, shading: dict) -> list[Path]:
    v = _defaults(p, shading)
    shader = d / f"{stem}.gdshader"
    shader.write_text(GDSHADER.format(name=stem, clearcoat_gloss=round(1 - v["clearcoat_roughness"], 3),
                                      **{k: round(float(x), 3) for k, x in v.items()}), encoding="utf-8")
    tex = [("albedo_tex", files["ShaderColor"]), ("normal_tex", files["ShaderNormal"]),
           ("orm_tex", files["ShaderORM"]), ("wear_tex", files["WearMask"]), ("detail_normal_tex", files["DetailNormal"])]
    lines = [f'[gd_resource type="ShaderMaterial" load_steps={len(tex) + 2} format=3]', "",
             f'[ext_resource type="Shader" path="./{shader.name}" id="shader"]']
    lines += [f'[ext_resource type="Texture2D" path="./{f}" id="{k}"]' for k, f in tex]
    lines += ["", "[resource]", 'shader = ExtResource("shader")']
    lines += [f'shader_parameter/{k} = ExtResource("{k}")' for k, _ in tex]
    mat = d / f"{stem}_shader.tres"
    mat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [shader, mat]


BLENDER_PY = '''"""MatterLift material for Blender 4/5: {stem}

Run once: Blender > Scripting > Open this file > Run Script (or blender --python {stem}_blender.py).
It builds the material "{stem}" from the textures next to this file and puts it on the active object
(a preview sphere if there is none). The "MatterLift ..." Value nodes on the left are the controls:
tiling, relief, detail strength, detail scale, wear. Triplanar: set TRIPLANAR = True below (Box
projection, no UVs needed).
"""
import os

import bpy

TRIPLANAR = False
HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else bpy.path.abspath("//")
NAME = "{stem}"
DEFAULTS = {defaults}
FILES = {files}


def image(nodes, key, colour, x, y, vec):
    n = nodes.new("ShaderNodeTexImage")
    n.image = bpy.data.images.load(os.path.join(HERE, FILES[key]), check_existing=True)
    n.image.colorspace_settings.name = "sRGB" if colour else "Non-Color"
    n.location = (x, y)
    if TRIPLANAR and key != "DetailHeight":
        n.projection = "BOX"
        n.projection_blend = 0.25
    return n


def mix_rgba(nodes, blend, x, y):
    """Mix node in colour mode. Its sockets share names across float/vector/colour ("A" three
    times), so colour ones are addressed by index: Factor 0, A 6, B 7, Result out 2."""
    n = nodes.new("ShaderNodeMix")
    n.data_type = "RGBA"
    n.blend_type = blend
    n.location = (x, y)
    return n


def value(nodes, label, v, y):
    n = nodes.new("ShaderNodeValue")
    n.label = n.name = "MatterLift " + label
    n.outputs[0].default_value = v
    n.location = (-1500, y)
    return n.outputs[0]


def build():
    mat = bpy.data.materials.get(NAME) or bpy.data.materials.new(NAME)
    if bpy.app.version < (5, 0, 0):  # always on (and deprecated) from Blender 5
        mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    nodes.clear()
    L = links.new

    tiling = value(nodes, "Tiling", DEFAULTS["uv_scale"], 300)
    relief = value(nodes, "Relief", DEFAULTS["normal_strength"], 200)
    detail = value(nodes, "Detail strength", DEFAULTS["detail_strength"], 100)
    repeats = value(nodes, "Detail scale", DEFAULTS["detail_repeats"], 0)
    wear = value(nodes, "Wear", DEFAULTS["wear"], -100)

    coord = nodes.new("ShaderNodeTexCoord")
    coord.location = (-1500, -300)
    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-1300, -300)
    L(coord.outputs["Object" if TRIPLANAR else "UV"], mapping.inputs["Vector"])
    combine = nodes.new("ShaderNodeCombineXYZ")
    combine.location = (-1300, 300)
    for c in "XYZ":
        L(tiling, combine.inputs[c])
    L(combine.outputs[0], mapping.inputs["Scale"])
    vec = mapping.outputs["Vector"]

    color = image(nodes, "ShaderColor", True, -1000, 300, vec)
    orm = image(nodes, "ShaderORM", False, -1000, 0, vec)
    nrm = image(nodes, "ShaderNormal", False, -1000, -300, vec)
    wmask = image(nodes, "WearMask", False, -1000, -600, vec)
    for n in (color, orm, nrm, wmask):
        L(vec, n.inputs["Vector"])

    # Detail tile at detail scale, as a bump on top of the normal map.
    dscale = nodes.new("ShaderNodeVectorMath")
    dscale.operation = "SCALE"
    dscale.location = (-1100, -900)
    L(vec, dscale.inputs[0])
    L(repeats, dscale.inputs["Scale"])
    dtex = image(nodes, "DetailHeight", False, -900, -900, None)
    L(dscale.outputs[0], dtex.inputs["Vector"])
    # The same tile turned 90 degrees, and the wear mask's blue channel (grain along X) picks
    # between them, so fibres follow each board as in pbrforge.
    swap_in = nodes.new("ShaderNodeSeparateXYZ")
    swap_in.location = (-1100, -1150)
    L(dscale.outputs[0], swap_in.inputs[0])
    swap_out = nodes.new("ShaderNodeCombineXYZ")
    swap_out.location = (-1000, -1150)
    L(swap_in.outputs["Y"], swap_out.inputs["X"])
    L(swap_in.outputs["X"], swap_out.inputs["Y"])
    dtex_t = image(nodes, "DetailHeight", False, -900, -1150, None)
    L(swap_out.outputs[0], dtex_t.inputs["Vector"])

    sep_orm = nodes.new("ShaderNodeSeparateColor")
    sep_orm.location = (-700, 0)
    L(orm.outputs["Color"], sep_orm.inputs[0])
    sep_w = nodes.new("ShaderNodeSeparateColor")
    sep_w.location = (-700, -600)
    L(wmask.outputs["Color"], sep_w.inputs[0])

    # Wear, as pbrforge: edges lighter (mix toward a lifted tone), cavities darker.
    edge_f = nodes.new("ShaderNodeMath")
    edge_f.operation = "MULTIPLY"
    edge_f.location = (-500, -500)
    L(sep_w.outputs["Red"], edge_f.inputs[0])
    L(wear, edge_f.inputs[1])
    half = nodes.new("ShaderNodeMath")
    half.operation = "MULTIPLY"
    half.inputs[1].default_value = 0.5
    half.location = (-350, -500)
    L(edge_f.outputs[0], half.inputs[0])
    lift = mix_rgba(nodes, "SCREEN", -300, 300)
    lift.inputs[7].default_value = (0.3, 0.3, 0.3, 1)
    L(half.outputs[0], lift.inputs[0])
    L(color.outputs["Color"], lift.inputs[6])
    cav_f = nodes.new("ShaderNodeMath")
    cav_f.operation = "MULTIPLY"
    cav_f.location = (-500, -700)
    L(sep_w.outputs["Green"], cav_f.inputs[0])
    L(wear, cav_f.inputs[1])
    darken = mix_rgba(nodes, "MULTIPLY", -100, 300)
    darken.inputs[7].default_value = (0.55, 0.55, 0.55, 1)
    L(cav_f.outputs[0], darken.inputs[0])
    L(lift.outputs[2], darken.inputs[6])
    ao_mul = mix_rgba(nodes, "MULTIPLY", 100, 300)
    ao_mul.inputs[0].default_value = 1.0
    L(darken.outputs[2], ao_mul.inputs[6])
    L(sep_orm.outputs["Red"], ao_mul.inputs[7])

    rough = nodes.new("ShaderNodeMath")
    rough.operation = "MULTIPLY_ADD"
    rough.use_clamp = True
    rough.location = (-300, 0)
    rough.inputs[1].default_value = -0.18
    L(edge_f.outputs[0], rough.inputs[0])
    L(sep_orm.outputs["Green"], rough.inputs[2])

    nmap = nodes.new("ShaderNodeNormalMap")
    nmap.location = (-500, -300)
    L(nrm.outputs["Color"], nmap.inputs["Color"])
    L(relief, nmap.inputs["Strength"])
    bump = nodes.new("ShaderNodeBump")
    bump.location = (-300, -300)
    bump.inputs["Distance"].default_value = 0.02
    L(detail, bump.inputs["Strength"])
    grain = nodes.new("ShaderNodeMix")  # float mode: Factor 0, A 2, B 3, Result out 0
    grain.data_type = "FLOAT"
    grain.location = (-500, -900)
    L(sep_w.outputs["Blue"], grain.inputs[0])
    L(dtex_t.outputs["Color"], grain.inputs[2])
    L(dtex.outputs["Color"], grain.inputs[3])
    L(grain.outputs[0], bump.inputs["Height"])
    L(nmap.outputs["Normal"], bump.inputs["Normal"])

    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (300, 0)
    L(ao_mul.outputs[2], bsdf.inputs["Base Color"])
    L(rough.outputs[0], bsdf.inputs["Roughness"])
    L(sep_orm.outputs["Blue"], bsdf.inputs["Metallic"])
    L(bump.outputs["Normal"], bsdf.inputs["Normal"])
    for key, sock in (("clearcoat", "Coat Weight"), ("sheen", "Sheen Weight"), ("transmission", "Transmission Weight"),
                      ("anisotropy", "Anisotropic"), ("ior", "IOR")):
        if key in DEFAULTS and sock in bsdf.inputs:
            bsdf.inputs[sock].default_value = DEFAULTS[key]
    if "Coat Roughness" in bsdf.inputs:
        bsdf.inputs["Coat Roughness"].default_value = DEFAULTS.get("clearcoat_roughness", 0.1)
    if DEFAULTS.get("subsurface", 0) > 0.01 and "Subsurface Weight" in bsdf.inputs:
        bsdf.inputs["Subsurface Weight"].default_value = DEFAULTS["subsurface"]

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (600, 0)
    L(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def main():
    mat = build()
    obj = bpy.context.active_object
    if obj is None or obj.type != "MESH":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=1)
        bpy.ops.object.shade_smooth()
        obj = bpy.context.active_object
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)
    print("MatterLift: material", NAME, "on", obj.name)


main()
'''


def write_blender(d: Path, stem: str, files: dict[str, str], p: MapParams, shading: dict) -> Path:
    v = _defaults(p, shading)
    v["detail_strength"] = round(v["detail_strength"] * 0.6, 3)  # Bump strength, tuned to match
    v.update({k: shading[k] for k in ("clearcoat", "clearcoat_roughness", "sheen", "transmission",
                                      "anisotropy", "ior", "subsurface") if k in shading})
    keys = ("ShaderColor", "ShaderNormal", "ShaderORM", "WearMask", "DetailHeight")
    script = d / f"{stem}_blender.py"
    script.write_text(BLENDER_PY.format(stem=stem, defaults=repr({k: float(x) for k, x in v.items()}),
                                        files=repr({k: files[k] for k in keys})), encoding="utf-8")
    return script


def write_all(d: Path, stem: str, lay: dict[str, np.ndarray], p: MapParams, shading: dict) -> list[Path]:
    """Layer textures (PNG) + the Godot shader and material + the Blender script."""
    files = {}
    for key, arr in (("ShaderColor", lay["albedo"]), ("ShaderNormal", lay["normal"]), ("ShaderORM", lay["orm"]),
                     ("WearMask", lay["wear_mask"]), ("DetailNormal", lay["detail_normal"]),
                     ("DetailHeight", lay["detail_height"])):
        name = f"{stem}_{key}.png"
        io.save(d / name, arr)
        files[key] = name
    return [*write_godot(d, stem, files, p, shading), write_blender(d, stem, files, p, shading)]
