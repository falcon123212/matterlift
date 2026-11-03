// WGSL shared by the Live RT passes: camera and helpers, BVH traversal, the compute entry point and
// the display pass. W / H are the largest internal resolution; unbiased.js rewrites them per quality.

export const W = 1920;
export const H = 1080;

export const COMMON = /* wgsl */`
const W = ${ W }u;
const H = ${ H }u;
const NONE = 0xffffffffu;
const PI = 3.14159265;

// current and previous camera (for temporal reprojection); accum = frames since the camera last moved
struct Cam { o: vec4f, u: vec4f, v: vec4f, w: vec4f, po: vec4f, pu: vec4f, pv: vec4f, pw: vec4f, frame: u32, accum: u32, live: u32, p2: u32 };
// three-mesh-bvh node: min xyz, max xyz, offset (leaf: first triangle, inner: relative right child), flags.
// The second half is read as u32: integers kept in f32 lanes are NaN / denormal bit patterns, which some
// GPUs (AMD) canonicalise or flush to zero.
struct Node { a: vec4f, b: vec4u };

// PCG hash (Jarzynski & Olano 2020): seeds from pixel and frame without the patterns of an LCG
fn pcg( v: u32 ) -> u32 {
	let s = v * 747796405u + 2891336453u;
	let w = ( ( s >> ( ( s >> 28u ) + 4u ) ) ^ s ) * 277803737u;
	return ( w >> 22u ) ^ w;
}
fn seedOf( pix: u32, salt: u32 ) -> u32 { return pcg( pix ^ pcg( cam.frame * 4u + salt ) ); }
fn rand( seed: ptr<function, u32> ) -> f32 {
	*seed = pcg( *seed );
	return f32( *seed >> 8u ) / 16777216.0;
}

// ray through point (px + off) of the pixel grid
fn camDirAt( px: vec2u, off: vec2f ) -> vec3f {
	let s = ( ( f32( px.x ) + off.x ) / f32( W ) - 0.5 ) * 2.0;
	let t = ( 0.5 - ( f32( px.y ) + off.y ) / f32( H ) ) * 2.0;
	return normalize( cam.w.xyz + s * cam.u.xyz + t * cam.v.xyz );
}
fn camDir( px: vec2u ) -> vec3f { return camDirAt( px, vec2f( 0.5 ) ); }
// sub-pixel offset of the primary rays: the centre while moving, an R2 sequence while accumulating
// (cam.p2 bit 3), so the accumulated image is anti-aliased
fn jitter() -> vec2f {
	if ( ( cam.p2 & 8u ) == 0u || cam.accum == 0u ) { return vec2f( 0.5 ); }
	return fract( vec2f( 0.5 ) + f32( cam.accum ) * vec2f( 0.7548776662, 0.5698402910 ) );
}

// unit normal <-> one f32: octahedral map, 11 bits per axis, as an exact integer (no NaN bit patterns)
fn octPack( n: vec3f ) -> f32 {
	var p = n.xy / ( abs( n.x ) + abs( n.y ) + abs( n.z ) );
	if ( n.z < 0.0 ) { p = ( 1.0 - abs( p.yx ) ) * select( vec2f( -1.0 ), vec2f( 1.0 ), p >= vec2f( 0.0 ) ); }
	let q = round( clamp( p * 0.5 + 0.5, vec2f( 0.0 ), vec2f( 1.0 ) ) * 2047.0 );
	return q.x * 2048.0 + q.y;
}
fn octUnpack( f: f32 ) -> vec3f {
	let qx = floor( f / 2048.0 );
	let e = vec2f( qx, f - qx * 2048.0 ) / 2047.0 * 2.0 - 1.0;
	var n = vec3f( e, 1.0 - abs( e.x ) - abs( e.y ) );
	if ( n.z < 0.0 ) { n = vec3f( ( 1.0 - abs( n.yx ) ) * select( vec2f( -1.0 ), vec2f( 1.0 ), n.xy >= vec2f( 0.0 ) ), n.z ); }
	return normalize( n );
}

// pixel of world point P in the previous frame, or -1 when it was off screen
fn prevPixel( P: vec3f ) -> vec2i {
	let d = P - cam.po.xyz;
	let z = dot( d, cam.pw.xyz );
	if ( z <= 0.0 ) { return vec2i( -1 ); }
	let s = dot( d / z, cam.pu.xyz ) / dot( cam.pu.xyz, cam.pu.xyz );
	let t = dot( d / z, cam.pv.xyz ) / dot( cam.pv.xyz, cam.pv.xyz );
	let q = vec2i( floor( vec2f( ( s * 0.5 + 0.5 ) * f32( W ), ( 0.5 - t * 0.5 ) * f32( H ) ) ) );
	if ( any( q < vec2i( 0 ) ) || q.x >= i32( W ) || q.y >= i32( H ) ) { return vec2i( -1 ); }
	return q;
}

fn studioBg( d: vec3f ) -> vec3f {
	return mix( vec3f( 0.003, 0.003, 0.004 ), vec3f( 0.022, 0.024, 0.03 ), clamp( d.z * 0.5 + 0.5, 0.0, 1.0 ) );
}
`;

export const TRAVERSE = /* wgsl */`
struct Hit { t: f32, tri: u32, u: f32, v: f32 };

// Stack-based BVH2 traversal. anyHit stops at the first occluder, like
// a hardware ray tracer's terminate-on-first-hit shadow rays.
fn traverse( o: vec3f, d: vec3f, tmax: f32, anyHit: bool ) -> Hit {
	var hit = Hit( tmax, NONE, 0.0, 0.0 );
	let safeD = select( d, vec3f( 1e-20 ), abs( d ) < vec3f( 1e-20 ) );
	let inv = 1.0 / safeD;
	var stack: array<u32, 48>;
	var sp = 0u;
	var ni = 0u;
	loop {
		let n = nodes[ ni ];
		let t0 = ( n.a.xyz - o ) * inv;
		let t1 = ( vec3f( n.a.w, bitcast<f32>( n.b.x ), bitcast<f32>( n.b.y ) ) - o ) * inv;
		let tn = max( max( min( t0.x, t1.x ), min( t0.y, t1.y ) ), min( t0.z, t1.z ) );
		let tf = min( min( max( t0.x, t1.x ), max( t0.y, t1.y ) ), max( t0.z, t1.z ) );
		if ( tf >= max( tn, 0.0 ) && tn < hit.t ) {
			let flags = n.b.w;
			let off = n.b.z;
			if ( ( flags >> 16u ) == 0xFFFFu ) {
				let end = off + ( flags & 0xFFFFu );
				for ( var i = off; i < end; i++ ) {
					let v0 = tris[ 3u * i ].xyz;
					let e1 = tris[ 3u * i + 1u ].xyz;
					let e2 = tris[ 3u * i + 2u ].xyz;
					let p = cross( d, e2 );
					let det = dot( e1, p );
					if ( abs( det ) > 1e-14 ) {
						let id = 1.0 / det;
						let s = o - v0;
						let u = dot( s, p ) * id;
						let q = cross( s, e1 );
						let v = dot( d, q ) * id;
						let t = dot( e2, q ) * id;
						if ( u >= 0.0 && v >= 0.0 && u + v <= 1.0 && t > 1e-4 && t < hit.t ) {
							hit.t = t;
							hit.tri = i;
							hit.u = u;
							hit.v = v;
							if ( anyHit ) { return hit; }
						}
					}
				}
			} else {
				let left = ni + 1u;
				let right = ni + off;
				if ( d[ flags ] >= 0.0 ) {
					stack[ sp ] = right; ni = left;
				} else {
					stack[ sp ] = left; ni = right;
				}
				sp++;
				continue;
			}
		}
		if ( sp == 0u ) { break; }
		sp--;
		ni = stack[ sp ];
	}
	return hit;
}
`;


export const MAIN = '@compute @workgroup_size( 8, 8 ) fn main( @builtin( global_invocation_id ) gid: vec3u ) {\n' +
	'if ( gid.x >= W || gid.y >= H ) { return; }\nlet pix = gid.y * W + gid.x;\n';

// scale = output pixels per canvas pixel
export const BLIT = scale => /* wgsl */`
const W = ${ W }u;
@group( 0 ) @binding( 0 ) var<storage, read> outBuf: array<vec4f>;
@vertex fn vs( @builtin( vertex_index ) i: u32 ) -> @builtin( position ) vec4f {
	let p = vec2f( f32( ( i << 1u ) & 2u ), f32( i & 2u ) );
	return vec4f( p * 2.0 - 1.0, 0.0, 1.0 );
}
@fragment fn fs( @builtin( position ) pos: vec4f ) -> @location( 0 ) vec4f {
	let q = vec2u( pos.xy * ${ scale }.0 );
	let c = outBuf[ q.y * W + q.x ].rgb * 1.4;
	// ACES fit
	let t = clamp( ( c * ( 2.51 * c + 0.03 ) ) / ( c * ( 2.43 * c + 0.59 ) + 0.14 ), vec3f( 0.0 ), vec3f( 1.0 ) );
	return vec4f( pow( t, vec3f( 1.0 / 2.2 ) ), 1.0 );
}
`;
