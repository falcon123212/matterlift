/** WGSL twin of TRIPLANAR_GLSL in ../preview.ts, for engines that shade meshes without UVs
 * (the Stanford dragon). Same weights (|n|^4) and the same whiteout normal blend, in world space,
 * so the ray-traced and Three.js previews match. `scale` = tiles per world unit. */
export const TRIPLANAR_WGSL = /* wgsl */ `
fn tri_weights(n: vec3<f32>) -> vec3<f32> {
  let w = pow(abs(n), vec3<f32>(4.0));
  return w / (w.x + w.y + w.z);
}

fn tri_sample(t: texture_2d<f32>, s: sampler, p: vec3<f32>, n: vec3<f32>, scale: f32) -> vec4<f32> {
  let q = p * scale;
  let w = tri_weights(n);
  return textureSampleLevel(t, s, q.zy, 0.0) * w.x
       + textureSampleLevel(t, s, q.xz, 0.0) * w.y
       + textureSampleLevel(t, s, q.xy, 0.0) * w.z;
}

// Normal map (OpenGL convention, as exported by MatterLift) projected on three planes, whiteout blend.
fn tri_normal(t: texture_2d<f32>, s: sampler, p: vec3<f32>, n_in: vec3<f32>, scale: f32) -> vec3<f32> {
  let n = normalize(n_in);
  let q = p * scale;
  let w = tri_weights(n);
  var tx = textureSampleLevel(t, s, q.zy, 0.0).xyz * 2.0 - 1.0;
  var ty = textureSampleLevel(t, s, q.xz, 0.0).xyz * 2.0 - 1.0;
  var tz = textureSampleLevel(t, s, q.xy, 0.0).xyz * 2.0 - 1.0;
  tx = vec3<f32>(tx.xy + n.zy, abs(tx.z) * n.x);
  ty = vec3<f32>(ty.xy + n.xz, abs(ty.z) * n.y);
  tz = vec3<f32>(tz.xy + n.xy, abs(tz.z) * n.z);
  return normalize(tx.zyx * w.x + ty.xzy * w.y + tz.xyz * w.z);
}
`;
