"""Godot 4 opens every export headless: the StandardMaterial3D .tres with all its textures, the
live ShaderMaterial (its shader must compile: the dummy renderer still parses it) and the .glb
through GLTFDocument. Runs when GODOT_BIN points at a Godot 4 binary (the CI downloads one)."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from pbrforge import export, maps, shaders

from .test_export_validators import SHADINGS
from .test_pbrforge import _noise

CHECK = '''extends SceneTree
# One JSON line per package: what Godot resolved from each exported file.
func _init() -> void:
	for dir in DirAccess.get_directories_at("res://m"):
		var base := "res://m/%s/" % dir
		var r := {"name": dir}
		var std := load(base + dir + ".tres") as StandardMaterial3D
		r["std"] = std != null
		if std:
			r["albedo"] = std.albedo_texture.get_width() if std.albedo_texture else 0
			r["normal"] = std.normal_texture != null
			r["roughness"] = std.roughness_texture != null
			r["ao"] = std.ao_texture != null
			r["height"] = std.heightmap_texture != null
			r["metal"] = std.metallic_texture != null
		var sm := load(base + "shader/" + dir + "_shader.tres") as ShaderMaterial
		r["uniforms"] = sm.shader.get_shader_uniform_list().size() if sm and sm.shader else -1
		var doc := GLTFDocument.new()
		var state := GLTFState.new()
		r["glb"] = doc.append_from_file(ProjectSettings.globalize_path(base + dir + ".glb"), state) == OK
		r["glb_materials"] = state.get_materials().size()
		print("MATTERLIFT " + JSON.stringify(r))
	quit()
'''


def _godot() -> str:
    path = os.environ.get("GODOT_BIN") or shutil.which("godot")
    if not path or not Path(path).exists():
        pytest.skip("set GODOT_BIN to a Godot 4 binary")
    return path


def test_godot_opens_every_export(tmp_path):
    godot = _godot()
    proj = tmp_path / "proj"
    albedo = _noise(128)
    expected = {}
    for metallic in (0.0, 1.0):
        p = maps.MapParams(metallic=metallic, detail_kind="wood", detail_strength=0.6, wear=0.5)
        m = maps.derive(albedo, p)
        lay = shaders.layers(albedo, p, 128, None)
        for key, shading in SHADINGS.items():
            d = export.export_package(m, f"{key} {'metal' if metallic else 'plain'}", proj / "m", "png",
                                      shading=shading, shader_layers=(lay, p))
            expected[d.name] = metallic > 0
    (proj / "project.godot").write_text('[application]\nconfig/name="matterlift_check"\n')
    (proj / "check.gd").write_text(CHECK)

    subprocess.run([godot, "--headless", "--path", str(proj), "--import"], capture_output=True, timeout=600)
    run = subprocess.run([godot, "--headless", "--path", str(proj), "-s", "check.gd"],
                         capture_output=True, text=True, timeout=600)
    log = run.stdout + run.stderr
    assert "SHADER ERROR" not in log and "Shader compilation failed" not in log, log[-3000:]
    rows = {r["name"]: r for r in (json.loads(line.split(" ", 1)[1]) for line in log.splitlines()
                                   if line.startswith("MATTERLIFT "))}
    assert set(rows) == set(expected), log[-3000:]
    for name, metal in expected.items():
        r = rows[name]
        assert r["std"] and r["albedo"] == 128 and r["normal"] and r["roughness"] and r["ao"] and r["height"], r
        assert r["metal"] == metal, r
        assert r["uniforms"] >= 15, r  # the live shader compiled and exposes its controls
        assert r["glb"] and r["glb_materials"] == 1, r
