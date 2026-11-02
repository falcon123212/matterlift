"""MatterLift material for Blender 4/5: OldWornOakParquet_512-PNG

Run once: Blender > Scripting > Open this file > Run Script (or blender --python OldWornOakParquet_512-PNG_blender.py).
It builds the material "OldWornOakParquet_512-PNG" from the textures next to this file and puts it on the active object
(a preview sphere if there is none). The "MatterLift ..." Value nodes on the left are the controls:
tiling, relief, detail strength, detail scale, wear. Triplanar: set TRIPLANAR = True below (Box
projection, no UVs needed).
"""
import os

import bpy

TRIPLANAR = False
HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else bpy.path.abspath("//")
NAME = "OldWornOakParquet_512-PNG"
DEFAULTS = {'uv_scale': 1.0, 'normal_strength': 1.0, 'detail_strength': 0.54, 'detail_repeats': 8.0, 'wear': 1.0, 'clearcoat': 0.05, 'clearcoat_roughness': 0.7, 'anisotropy': 0.2, 'sss': 0.0, 'rim': 0.0, 'specular': 0.5000000000000001, 'sheen': 0.0, 'transmission': 0.0, 'ior': 1.5, 'subsurface': 0.0}
FILES = {'ShaderColor': 'OldWornOakParquet_512-PNG_ShaderColor.png', 'ShaderNormal': 'OldWornOakParquet_512-PNG_ShaderNormal.png', 'ShaderORM': 'OldWornOakParquet_512-PNG_ShaderORM.png', 'WearMask': 'OldWornOakParquet_512-PNG_WearMask.png', 'DetailHeight': 'OldWornOakParquet_512-PNG_DetailHeight.png'}


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
