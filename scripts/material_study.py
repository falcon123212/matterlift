"""The material study: MatterLift's own preview scene, modelled from code in Blender (MIT, like the rest
of the repository), so no third-party mesh is needed to show a material.

Each piece shows something about a material:
  two-step plinth   large flat areas (tiling, scale, repetition) and round edges (edge highlights)
  sphere            every angle at once: highlight shape, Fresnel at grazing angles, triplanar blend
  rounded cube      flat faces at three orientations, bevelled edges and corners
  upright torus     concave and convex curvature, inner faces in shadow
  fluted column     narrow grooves (normal map against real geometry), a tall silhouette
  Suzanne           on the cube: organic curvature, deep hollows (eyes, ears), stretched areas
                    (Blender's own primitive, made by Blender here)

    "C:/Program Files/Blender Foundation/Blender 5.0/blender.exe" -b --factory-startup --python scripts/material_study.py

Writes web/public/models/material_study.ply (z up: positions, smooth normals, UVs, triangles) and
docs/blender/material_study.blend.

UVs: each piece keeps its primitive's own unwrap, scaled to the density of the triplanar projection
(REPEAT tiles per UV unit in the WebGL preview, TRI_SCALE["study"] tiles per unit of the mesh normalised
to its bounding sphere), each axis rounded to whole tiles so the wrapping ones (sphere, torus, cylinder
sides) close without a seam. Seams stay on the cube's edges, the caps and Suzanne, as on any UV-mapped
asset: the preview's UV / triplanar switch shows the difference.
"""
from __future__ import annotations

import math
from pathlib import Path

import bmesh
import bpy
from bpy_extras.mesh_utils import mesh_linked_uv_islands

ROOT = Path(__file__).resolve().parents[1]
PLY = ROOT / "web" / "public" / "models" / "material_study.ply"
BLEND = ROOT / "docs" / "blender" / "material_study.blend"

TIER1, TIER2 = 0.10, 0.08  # plinth step heights
TOP = TIER1 + TIER2  # where the pieces stand
# web/src/preview.ts: REPEAT tiles per UV unit; TRI_SCALE.study = REPEAT / 0.8 tiles per normalised unit
REPEAT = 2
TILES_PER_UNIT = REPEAT / 0.8
CUBE = dict(size=0.44, location=(-0.36, -0.20), angle=28)


def bevel(obj, width: float, segments: int) -> None:
    m = obj.modifiers.new("bevel", "BEVEL")
    m.width = width
    m.segments = segments
    m.limit_method = "ANGLE"
    m.angle_limit = math.radians(40)
    m.harden_normals = False


def finish(obj) -> None:
    """Apply the modifiers, smooth shading."""
    bpy.context.view_layer.objects.active = obj
    for m in list(obj.modifiers):
        bpy.ops.object.modifier_apply(modifier=m.name)
    for p in obj.data.polygons:
        p.use_smooth = True


def ring_caps(obj, rings: int) -> None:
    """Concentric rings on a cylinder's top cap: a cap is one n-gon, which triangulates into a fan of long
    slivers, and the preview's displacement moves vertices only, so the relief needs them spread."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    caps = [f for f in bm.faces if len(f.verts) > 8 and f.normal.z > 0.5]  # the tops: the bottoms never show
    for cap in caps:
        r = max((v.co.xy - cap.calc_center_median().xy).length for v in cap.verts)
        for _ in range(rings):
            bmesh.ops.inset_region(bm, faces=[cap], thickness=r / (rings + 1), depth=0, use_even_offset=True)
    # the inset copies the rim's UVs onto every ring: the flat top gets a projection from above instead
    uv = bm.loops.layers.uv.active
    for f in bm.faces:
        if f.normal.z > 0.999:
            for l in f.loops:
                l[uv].uv = (l.vert.co.x, l.vert.co.y)
    bm.to_mesh(obj.data)
    bm.free()


def plinth():
    parts = []
    for i, (r, h, z) in enumerate([(1.0, TIER1, TIER1 / 2), (0.78, TIER2, TIER1 + TIER2 / 2)]):
        bpy.ops.mesh.primitive_cylinder_add(vertices=160, radius=r, depth=h, location=(0, 0, z))
        o = bpy.context.object
        o.name = f"plinth_{i}"
        ring_caps(o, 24)
        bevel(o, 0.018, 4)
        finish(o)
        parts.append(o)
    return parts


def sphere():
    bpy.ops.mesh.primitive_uv_sphere_add(segments=160, ring_count=80, radius=0.40, location=(0.05, 0.28, TOP + 0.40))
    o = bpy.context.object
    o.name = "sphere"
    finish(o)
    return o


def rounded_cube():
    s = CUBE["size"]
    bpy.ops.mesh.primitive_cube_add(size=s, location=(*CUBE["location"], TOP + s / 2), rotation=(0, 0, math.radians(CUBE["angle"])))
    o = bpy.context.object
    o.name = "rounded_cube"
    # a few cuts so the flat faces carry vertices for the shared normals
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.subdivide(number_cuts=6)
    bpy.ops.object.mode_set(mode="OBJECT")
    bevel(o, 0.035, 6)
    finish(o)
    return o


def torus():
    R, r = 0.20, 0.07
    bpy.ops.mesh.primitive_torus_add(major_segments=128, minor_segments=48, major_radius=R, minor_radius=r,
                                     location=(0.40, -0.36, TOP + R + r),
                                     rotation=(math.radians(90), 0, math.radians(-35)))
    o = bpy.context.object
    o.name = "torus"
    finish(o)
    return o


def fluted_column():
    """A column of 16 rounded flutes, a bevelled cap on top."""
    h, r, flutes = 0.74, 0.11, 16
    bpy.ops.mesh.primitive_cylinder_add(vertices=256, radius=r, depth=h, location=(-0.58, 0.30, TOP + h / 2))
    o = bpy.context.object
    o.name = "fluted_column"
    bm = bmesh.new()
    bm.from_mesh(o.data)
    for v in bm.verts:
        a = math.atan2(v.co.y, v.co.x)
        d = math.hypot(v.co.x, v.co.y)
        if d > 1e-6:
            k = 1 - 0.07 * (0.5 + 0.5 * math.cos(flutes * a))
            v.co.x *= k
            v.co.y *= k
    # rings along the shaft, so the long flute faces are not slivers
    edges = [e for e in bm.edges if abs(e.verts[0].co.z - e.verts[1].co.z) > 1e-6]
    bmesh.ops.subdivide_edges(bm, edges=edges, cuts=12, use_grid_fill=True)
    bm.to_mesh(o.data)
    bm.free()
    bevel(o, 0.012, 4)
    finish(o)
    return o


def suzanne():
    """Blender's monkey sitting on the cube, turned a little more towards the camera than the cube."""
    bpy.ops.mesh.primitive_monkey_add(size=0.30, rotation=(0, 0, math.radians(CUBE["angle"] - 12)))
    o = bpy.context.object
    o.name = "suzanne"
    sub = o.modifiers.new("subsurf", "SUBSURF")
    sub.levels = sub.render_levels = 3
    finish(o)
    # chin on the cube's top, sunk 5 mm so it rests on it
    bottom = min((o.matrix_world @ v.co).z for v in o.data.vertices)
    o.location = (*CUBE["location"], o.location.z + TOP + CUBE["size"] - 0.005 - bottom)
    return o


def scale_uvs(objs) -> None:
    """Each piece's UVs scaled to the triplanar density, each axis to whole tiles (see the docstring)."""
    pts = [o.matrix_world @ v.co for o in objs for v in o.data.vertices]
    lo = [min(p[k] for p in pts) for k in range(3)]
    hi = [max(p[k] for p in pts) for k in range(3)]
    centre = [(a + b) / 2 for a, b in zip(lo, hi)]
    radius = max(math.dist(p, centre) for p in pts)  # three.js computeBoundingSphere: box centre, farthest vertex
    tiles = TILES_PER_UNIT / radius  # tiles per Blender unit
    for o in objs:
        me = o.data
        uv = me.uv_layers.active.data
        me.calc_loop_triangles()
        by_poly = {}
        for t in me.loop_triangles:
            by_poly.setdefault(t.polygon_index, []).append(t)
        # per UV island (a cylinder's side and its caps differ a lot), so each keeps its own density
        for island in mesh_linked_uv_islands(me):
            su = sv = area = 0.0
            for t in (t for f in island for t in by_poly.get(f, [])):
                p = [o.matrix_world @ me.vertices[i].co for i in t.vertices]
                q = [uv[i].uv for i in t.loops]
                e1, e2 = p[1] - p[0], p[2] - p[0]
                d1, d2 = q[1] - q[0], q[2] - q[0]
                det = d1.x * d2.y - d2.x * d1.y
                if abs(det) < 1e-12:
                    continue
                a = e1.cross(e2).length / 2
                su += a * ((e1 * d2.y - e2 * d1.y) / det).length
                sv += a * ((e2 * d1.x - e1 * d2.x) / det).length
                area += a
            if area == 0:
                continue
            # world units per UV unit along each axis -> whole tiles per UV unit
            nu = max(1, round(su / area * tiles))
            nv = max(1, round(sv / area * tiles))
            for f in island:
                for li in me.polygons[f].loop_indices:
                    uv[li].uv = (uv[li].uv.x * nu / REPEAT, uv[li].uv.y * nv / REPEAT)
        print(f"  {o.name}: {len(mesh_linked_uv_islands(me))} UV islands")


def main() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    objs = [*plinth(), sphere(), rounded_cube(), suzanne(), torus(), fluted_column()]
    scale_uvs(objs)
    # one mesh, triangulated
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    study = bpy.context.object
    study.name = "material_study"
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    tri = study.modifiers.new("triangulate", "TRIANGULATE")
    tri.keep_custom_normals = False
    finish(study)
    tris = sum(len(p.vertices) - 2 for p in study.data.polygons)
    print(f"material_study: {len(study.data.vertices)} vertices, {tris} triangles, size {tuple(round(x, 3) for x in study.dimensions)}")

    # a neutral clay material, a camera and a light, so the .blend opens on something readable
    mat = bpy.data.materials.new("clay")
    mat.diffuse_color = (0.45, 0.45, 0.45, 1)
    study.data.materials.append(mat)
    bpy.ops.object.camera_add(location=(0, -3.6, 1.15), rotation=(math.radians(78), 0, 0))
    bpy.context.scene.camera = bpy.context.object
    bpy.ops.object.light_add(type="AREA", location=(1.5, -1.5, 2.5))
    bpy.context.object.data.energy = 400
    bpy.context.object.data.size = 1.5

    PLY.parent.mkdir(parents=True, exist_ok=True)
    BLEND.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    study.select_set(True)
    # normals exported: the UV seams split vertices, and normals recomputed from one side would show the seam
    bpy.ops.wm.ply_export(filepath=str(PLY), export_selected_objects=True, export_uv=True, export_normals=True,
                          export_colors="NONE", export_attributes=False, export_triangulated_mesh=True,
                          ascii_format=False, forward_axis="Y", up_axis="Z")
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND), compress=True)
    print("wrote", PLY, PLY.stat().st_size, "bytes;", BLEND)


main()
