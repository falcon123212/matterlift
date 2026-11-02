// MatterLift material shader for Godot 4: OldWornOakParquet_512-PNG
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
uniform float uv_scale : hint_range(0.1, 16.0) = 1.0;
uniform float normal_strength : hint_range(0.0, 3.0) = 1.0;
uniform float detail_strength : hint_range(0.0, 1.0) = 0.9;
uniform float detail_repeats : hint_range(1.0, 32.0) = 8.0;
uniform float wear : hint_range(0.0, 1.0) = 1.0;
uniform float ao_strength : hint_range(0.0, 1.0) = 1.0;
uniform bool triplanar = false;
uniform float triplanar_scale : hint_range(0.05, 8.0) = 1.0;
uniform float triplanar_sharpness : hint_range(1.0, 16.0) = 4.0;

group_uniforms shading;
uniform float clearcoat_amount : hint_range(0.0, 1.0) = 0.05;
uniform float clearcoat_gloss : hint_range(0.0, 1.0) = 0.3;
uniform float anisotropy_amount : hint_range(-1.0, 1.0) = 0.2;
uniform float sss : hint_range(0.0, 1.0) = 0.0;
uniform float rim_amount : hint_range(0.0, 1.0) = 0.0;
uniform float specular_amount : hint_range(0.0, 1.0) = 0.5;

varying vec3 world_pos;
varying vec3 world_nrm;

void vertex() {
	world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	world_nrm = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
}

vec3 tri_weights(vec3 n) {
	vec3 w = pow(abs(n), vec3(triplanar_sharpness));
	return w / (w.x + w.y + w.z);
}

// One function per texture: Godot will not pass samplers with different hints to one parameter.
vec3 tri_albedo(vec3 p, vec3 w) {
	return (texture(albedo_tex, p.zy) * w.x + texture(albedo_tex, p.xz) * w.y + texture(albedo_tex, p.xy) * w.z).rgb;
}
vec3 tri_orm(vec3 p, vec3 w) {
	return (texture(orm_tex, p.zy) * w.x + texture(orm_tex, p.xz) * w.y + texture(orm_tex, p.xy) * w.z).rgb;
}
vec3 tri_wear(vec3 p, vec3 w) {
	return (texture(wear_tex, p.zy) * w.x + texture(wear_tex, p.xz) * w.y + texture(wear_tex, p.xy) * w.z).rgb;
}

// Whiteout blend of three tangent-space normal samples into a world-space normal.
vec3 tri_normal(vec3 p, vec3 n, vec3 w) {
	vec3 tx = texture(normal_tex, p.zy).xyz * 2.0 - 1.0;
	vec3 ty = texture(normal_tex, p.xz).xyz * 2.0 - 1.0;
	vec3 tz = texture(normal_tex, p.xy).xyz * 2.0 - 1.0;
	tx = vec3(tx.xy * normal_strength + n.zy, abs(tx.z) * n.x);
	ty = vec3(ty.xy * normal_strength + n.xz, abs(ty.z) * n.y);
	tz = vec3(tz.xy * normal_strength + n.xy, abs(tz.z) * n.z);
	return normalize(tx.zyx * w.x + ty.xzy * w.y + tz.xyz * w.z);
}

void fragment() {
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

	if (triplanar) {
		NORMAL = normalize((VIEW_MATRIX * vec4(tri_normal(tp, normalize(world_nrm), tw), 0.0)).xyz);
	} else {
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
	}
}
