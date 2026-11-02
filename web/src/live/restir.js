// Unbiased ReSTIR DI with many spot lights (GRIS, pairwise MIS, ray-traced visibility in the target),
// following RTXDI's unbiased mode. Three variants are compiled so they can be compared live:
//   0 = unbiased, target includes visibility (shadow rays in every MIS evaluation)
//   1 = unbiased, unshadowed target (1 shadow ray at shading)
//   2 = biased, the plain 1/M combination of the original ReSTIR (1 shadow ray at shading)
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { W as W_MAX, H as H_MAX, COMMON as COMMON_MAX, TRAVERSE, MAIN, BLIT } from './wgsl.js';

// Internal resolution, chosen per GPU (see QUALITY); the WGSL W / H constants follow it.
let W = W_MAX, H = H_MAX, N = W * H;
let COMMON = COMMON_MAX;
const atResolution = wgsl => wgsl.replace( /const W = \d+u;/, `const W = ${ W }u;` ).replace( /const H = \d+u;/, `const H = ${ H }u;` );
// quality ladder, best first: resolution and its share of the 1080p cost
export const QUALITY = [ { w: 1920, h: 1080 }, { w: 1440, h: 810 }, { w: 960, h: 540 }, { w: 640, h: 360 } ];
export const NUM_LIGHTS = 256;
// slots after the decor spots, for the spots the user places (Shift + click)
export const MAX_CUSTOM = 32;
const TOTAL = NUM_LIGHTS + MAX_CUSTOM;
export const MODES = [ 'unbiased, visibility in target (RTXDI)', 'unbiased, unshadowed target', 'biased (plain 1/M combination)' ];
const CANDIDATES = 16;
const SPATIAL = 2;
const RADIUS = 30;
const M_CAP = 20;

// ---------------------------------------------------------------- spot rig

function makeSpots() {

	let s = 12345;
	const rnd = () => ( s = ( s * 1664525 + 1013904223 ) >>> 0 ) / 4294967296;
	const palette = [ [ 0.1, 0.9, 0.8 ], [ 1.0, 0.25, 0.6 ], [ 1.0, 0.55, 0.15 ], [ 0.25, 0.45, 1.0 ] ];
	const spots = [];
	for ( let i = 0; i < NUM_LIGHTS; i ++ ) {
		const a = rnd() * Math.PI * 2, r = 0.18 + rnd() * 0.27, z = 0.12 + rnd() * 0.33;
		const pos = [ Math.cos( a ) * r, Math.sin( a ) * r, z ];
		const aim = [ ( rnd() - 0.5 ) * 0.16, ( rnd() - 0.5 ) * 0.06, rnd() * 0.12 ];
		const d = aim.map( ( v, k ) => v - pos[ k ] );
		const dl = Math.hypot( ...d );
		const outer = ( 8 + rnd() * 12 ) * Math.PI / 180;
		const warm = rnd();
		const col = rnd() < 0.3 ? palette[ Math.floor( rnd() * palette.length ) ] : [ 1.0, 0.85 + 0.15 * warm, 0.7 + 0.3 * warm ];
		spots.push( { pos, dir: d.map( v => v / dl ), cosO: Math.cos( outer ), cosI: Math.cos( outer * 0.7 ), col, I: 0.01 + rnd() * 0.03 } );
	}
	return spots;

}

// GPU light data + alias table for the current settings: the first `count` spots are lit when `on`,
// with their own colours or a single linear-RGB `color`. Unlit spots have zero power and are never picked.
function spotBuffers( spots, { on = true, count = NUM_LIGHTS, color = null, custom = [], gain = 1 } = {} ) {

	const data = new Float32Array( TOTAL * 12 );
	const power = new Float64Array( TOTAL );
	[ ...spots, ...custom ].forEach( ( s, i ) => {
		const lit = i >= NUM_LIGHTS || ( on && i < count );
		const col = lit ? ( color || s.col ) : [ 0, 0, 0 ];
		data.set( [ ...s.pos, s.cosO, ...s.dir, s.cosI, ...col.map( c => c * s.I * gain ), 0 ], i * 12 );
		power[ i ] = s.I * gain * ( 0.2126 * col[ 0 ] + 0.7152 * col[ 1 ] + 0.0722 * col[ 2 ] ) * 2 * Math.PI * ( 1 - s.cosO );
	} );
	// Vose alias table, light picked proportionally to its power; pdf stored in col.w.
	// With every spot off the table is uniform (all contributions are zero anyway).
	let total = power.reduce( ( a, b ) => a + b, 0 );
	if ( total === 0 ) { power.fill( 1 ); total = TOTAL; }
	const prob = Array.from( power, p => p / total * TOTAL );
	const alias = new Uint32Array( TOTAL );
	const small = [], large = [];
	prob.forEach( ( p, i ) => ( p < 1 ? small : large ).push( i ) );
	while ( small.length && large.length ) {
		const l = small.pop(), g = large.pop();
		alias[ l ] = g;
		prob[ g ] += prob[ l ] - 1;
		( prob[ g ] < 1 ? small : large ).push( g );
	}
	for ( const i of [ ...small, ...large ] ) { prob[ i ] = 1; alias[ i ] = i; }
	const table = new ArrayBuffer( TOTAL * 8 );
	const tf = new Float32Array( table ), tu = new Uint32Array( table );
	for ( let i = 0; i < TOTAL; i ++ ) {
		data[ i * 12 + 11 ] = power[ i ] / total;
		tf[ i * 2 ] = prob[ i ];
		tu[ i * 2 + 1 ] = alias[ i ];
	}
	return { data, table };

}

// ---------------------------------------------------------------- WGSL

const DECLS = {
	cam: 'var<uniform> cam: Cam;',
	nodes: 'var<storage, read> nodes: array<Node>;',
	tris: 'var<storage, read> tris: array<vec4f>;',
	tnorm: 'var<storage, read> tnorm: array<vec4f>;',
	gout: 'var<storage, read_write> gout: array<vec4f>;',
	gcur: 'var<storage, read> gcur: array<vec4f>;',
	gprev: 'var<storage, read> gprev: array<vec4f>;',
	lights: 'var<storage, read> lights: array<Light>;',
	alias: 'var<storage, read> aliasT: array<vec2u>;',
	resIn: 'var<storage, read> resIn: array<vec4u>;',
	hist: 'var<storage, read> hist: array<vec4u>;',
	resOut: 'var<storage, read_write> resOut: array<vec4u>;',
	out: 'var<storage, read_write> outBuf: array<vec4f>;',
	ref: 'var<storage, read_write> refBuf: array<vec4f>;',
	// denoiser
	outR: 'var<storage, read> outBuf: array<vec4f>;',
	hAin: 'var<storage, read> hAin: array<vec4f>;',
	hMin: 'var<storage, read> hMin: array<vec4f>;',
	hAout: 'var<storage, read_write> hAout: array<vec4f>;',
	hMout: 'var<storage, read_write> hMout: array<vec4f>;',
	dnIn: 'var<storage, read> dnIn: array<vec4f>;',
	dnOut: 'var<storage, read_write> dnOut: array<vec4f>;',
	stepU: 'var<uniform> stepU: vec4u;',
	guideW: 'var<storage, read_write> guide: array<vec4f>;',
	matU: 'var<uniform> matU: Mat;',
	tAlb: 'var tAlb: texture_2d<f32>;',
	tNrm: 'var tNrm: texture_2d<f32>;',
	tRgh: 'var tRgh: texture_2d<f32>;',
	tMet: 'var tMet: texture_2d<f32>;',
	smp: 'var smp: sampler;',
	guide: 'var<storage, read> guide: array<vec4f>;',
	disp: 'var<storage, read_write> disp: array<vec4f>;',
};

const LIGHTS = /* wgsl */`
const NL = ${ TOTAL }u;
// pos.w = cos outer cone, dir.w = cos inner cone, col.rgb = intensity, col.w = pick pdf
struct Light { pos: vec4f, dir: vec4f, col: vec4f };
// spec = roughness, plus 2 for a metal (G-Buffer channel c.w)
struct Surf { p: vec3f, n: vec3f, alb: vec3f, spec: f32, v: vec3f, ok: bool };

fn lum( c: vec3f ) -> f32 { return dot( c, vec3f( 0.2126, 0.7152, 0.0722 ) ); }

fn surfFrom( a: vec4f, b: vec4f, c: vec4f, eye: vec3f ) -> Surf {
	return Surf( a.xyz, b.xyz, c.xyz, c.w, normalize( eye - a.xyz ), b.w > 0.0 );
}

// BRDF * Le * cos / d^2 for spot li, without visibility
fn unshadowed( s: Surf, li: u32 ) -> vec3f {
	let L = lights[ li ];
	let d = L.pos.xyz - s.p;
	let d2 = dot( d, d );
	let l = d * inverseSqrt( d2 );
	let ndl = dot( s.n, l );
	if ( ndl <= 0.0 ) { return vec3f( 0.0 ); }
	let fall = smoothstep( L.pos.w, L.dir.w, dot( -l, L.dir.xyz ) );
	if ( fall <= 0.0 ) { return vec3f( 0.0 ); }
	// GGX + Smith (Schlick-GGX) + Schlick Fresnel, metal / roughness workflow
	let metal = select( 0.0, 1.0, s.spec >= 2.0 );
	let a = max( s.spec - 2.0 * metal, 0.05 );
	let a2 = a * a * a * a;
	let h = normalize( l + s.v );
	let ndh = max( dot( s.n, h ), 0.0 );
	let ndv = max( dot( s.n, s.v ), 1e-4 );
	let dd = ndh * ndh * ( a2 - 1.0 ) + 1.0;
	let D = a2 / ( PI * dd * dd );
	let k = a * a * 0.5;
	let G = ndl / ( ndl * ( 1.0 - k ) + k ) * ndv / ( ndv * ( 1.0 - k ) + k );
	let F = mix( vec3f( 0.04 ), s.alb, metal ) + ( 1.0 - mix( vec3f( 0.04 ), s.alb, metal ) ) * pow( 1.0 - max( dot( s.v, h ), 0.0 ), 5.0 );
	let diffuse = s.alb * ( 1.0 - metal ) * ( vec3f( 1.0 ) - F ) / PI;
	return ( diffuse + D * G * F / ( 4.0 * ndl * ndv ) ) * ndl * L.col.rgb * fall / d2;
}

fn visible( s: Surf, li: u32 ) -> bool {
	let o = s.p + s.n * 1e-4;
	let d = lights[ li ].pos.xyz - o;
	let dist = length( d );
	return traverse( o, d / dist, dist * 0.999, true ).tri == NONE;
}

// target function: luminance of the unshadowed contribution, times visibility in variant 0
fn phat( s: Surf, li: u32 ) -> f32 {
	if ( li == NONE ) { return 0.0; }
	let u = lum( unshadowed( s, li ) );
	if ( u <= 0.0 ) { return 0.0; }
	if ( VARIANT == 0u && ! visible( s, li ) ) { return 0.0; }
	return u;
}


// reservoir = ( light index, W, M, target at its own pixel )
struct Res { y: u32, W: f32, M: f32, p: f32 };
// stored as u32: the light index must survive bit for bit (NONE is a NaN pattern, small indices are denormals)
fn unpack( v: vec4u ) -> Res { return Res( v.x, bitcast<f32>( v.y ), bitcast<f32>( v.z ), bitcast<f32>( v.w ) ); }
fn pack( r: Res ) -> vec4u { return vec4u( r.y, bitcast<u32>( r.W ), bitcast<u32>( r.M ), bitcast<u32>( r.p ) ); }

// streaming resampling state
struct Stream { y: u32, p: f32, wsum: f32 };
fn add( st: ptr<function, Stream>, y: u32, p: f32, w: f32, seed: ptr<function, u32> ) {
	( *st ).wsum += w;
	if ( w > 0.0 && lcg( seed ) * ( *st ).wsum < w ) { ( *st ).y = y; ( *st ).p = p; }
}

// pairwise MIS split for one canonical / neighbour pair
fn pairT( mi: f32, pi: f32, mcOverK: f32, pc: f32 ) -> f32 {
	let d = mi * pi + mcOverK * pc;
	return select( 0.0, mi * pi / d, d > 0.0 );
}
`;

// alias-table light pick, only in the passes that bind the table
const PICK = /* wgsl */`
fn pickLight( seed: ptr<function, u32> ) -> u32 {
	let i = min( u32( lcg( seed ) * f32( NL ) ), NL - 1u );
	let e = aliasT[ i ];
	// x = probability (f32 bits), y = alias index
	return select( e.y, i, lcg( seed ) < bitcast<f32>( e.x ) );
}
`;

// combines the canonical reservoir c (pixel surface sc) with k neighbour reservoirs ns (surfaces nsurf)
const COMBINE = /* wgsl */`
fn combine( sc: Surf, c: Res, ns: array<Res, 2>, nsurf: array<Surf, 2>, k: u32, seed: ptr<function, u32> ) -> Res {
	if ( k == 0u ) { return c; }
	var st = Stream( NONE, 0.0, 0.0 );
	var mTot = c.M;
	if ( VARIANT == 2u ) {
		// biased: weights M * p_c * W, normalised by the total M
		add( &st, c.y, c.p, c.p * c.W * c.M, seed );
		for ( var i = 0u; i < k; i++ ) {
			let pci = phat( sc, ns[ i ].y );
			add( &st, ns[ i ].y, pci, pci * ns[ i ].W * ns[ i ].M, seed );
			mTot += ns[ i ].M;
		}
		let wOut = select( 0.0, st.wsum / ( mTot * st.p ), st.p > 0.0 );
		return Res( st.y, wOut, mTot, st.p );
	}
	let kf = f32( k );
	var mc = 0.0;
	for ( var i = 0u; i < k; i++ ) {
		let n = ns[ i ];
		// neighbour sample: MIS weight in the current pixel's domain
		let pci = select( 0.0, phat( sc, n.y ), n.W > 0.0 );
		let mi = pairT( n.M, n.p, c.M / kf, pci ) / kf;
		add( &st, n.y, pci, mi * pci * n.W, seed );
		// canonical sample: complement, needs the target in the neighbour's domain
		let pic = phat( nsurf[ i ], c.y );
		mc += ( 1.0 - pairT( n.M, pic, c.M / kf, c.p ) ) / kf;
		mTot += n.M;
	}
	add( &st, c.y, c.p, mc * c.p * c.W, seed );
	let wOut = select( 0.0, st.wsum / st.p, st.p > 0.0 );
	return Res( st.y, wOut, mTot, st.p );
}
`;

// triplanar projection of the generated material, with an explicit mip level (no derivatives in compute)
const MATERIAL = /* wgsl */`
// triplanar tiles per world unit (tiling included), texture size, pixel angle (for the mip level),
// normal map strength, clay switch
struct Mat { scale: f32, texSize: f32, pixAngle: f32, normalScale: f32, clay: f32, p0: f32, p1: f32, p2: f32 };
fn triW( n: vec3f ) -> vec3f {
	let w = pow( abs( n ), vec3f( 4.0 ) );
	return w / ( w.x + w.y + w.z );
}
fn triTex( t: texture_2d<f32>, p: vec3f, n: vec3f, lod: f32 ) -> vec4f {
	let q = p * matU.scale;
	let w = triW( n );
	return textureSampleLevel( t, smp, q.zy, lod ) * w.x + textureSampleLevel( t, smp, q.xz, lod ) * w.y + textureSampleLevel( t, smp, q.xy, lod ) * w.z;
}
// whiteout blend of the three tangent-space normal maps (OpenGL convention)
fn triNormal( t: texture_2d<f32>, p: vec3f, n: vec3f, lod: f32 ) -> vec3f {
	let q = p * matU.scale;
	let w = triW( n );
	var tx = textureSampleLevel( t, smp, q.zy, lod ).xyz * 2.0 - 1.0;
	var ty = textureSampleLevel( t, smp, q.xz, lod ).xyz * 2.0 - 1.0;
	var tz = textureSampleLevel( t, smp, q.xy, lod ).xyz * 2.0 - 1.0;
	tx = vec3f( tx.xy * matU.normalScale, tx.z );
	ty = vec3f( ty.xy * matU.normalScale, ty.z );
	tz = vec3f( tz.xy * matU.normalScale, tz.z );
	tx = vec3f( tx.xy + n.zy, abs( tx.z ) * n.x );
	ty = vec3f( ty.xy + n.xz, abs( ty.z ) * n.y );
	tz = vec3f( tz.xy + n.xy, abs( tz.z ) * n.z );
	return normalize( tx.zyx * w.x + ty.xzy * w.y + tz.xyz * w.z );
}
// one texel per pixel at hit distance t
fn texLod( t: f32 ) -> f32 { return log2( max( matU.texSize * matU.scale * t * matU.pixAngle, 1.0 ) ); }
`;

// albedo only, for the shading pass (it has no room for the other textures' bindings in its code)
const MATERIAL_ALB = /* wgsl */`
// triplanar tiles per world unit (tiling included), texture size, pixel angle (for the mip level),
// normal map strength, clay switch
struct Mat { scale: f32, texSize: f32, pixAngle: f32, normalScale: f32, clay: f32, p0: f32, p1: f32, p2: f32 };
fn triAlb( p: vec3f, n: vec3f, lod: f32 ) -> vec3f {
	let q = p * matU.scale;
	let w = pow( abs( n ), vec3f( 4.0 ) );
	let wn = w / ( w.x + w.y + w.z );
	if ( matU.clay > 0.5 ) { return vec3f( 0.45 ); }
	return ( textureSampleLevel( tAlb, smp, q.zy, lod ) * wn.x + textureSampleLevel( tAlb, smp, q.xz, lod ) * wn.y + textureSampleLevel( tAlb, smp, q.xy, lod ) * wn.z ).rgb;
}
fn texLod( t: f32 ) -> f32 { return log2( max( matU.texSize * matU.scale * t * matU.pixAngle, 1.0 ) ); }
`;

const KERNELS = {

	primary: { uses: [ 'cam', 'nodes', 'tris', 'tnorm', 'gout', 'guideW', 'matU', 'tAlb', 'tNrm', 'tRgh', 'tMet', 'smp' ], code: TRAVERSE + MATERIAL + MAIN + /* wgsl */`
		let d = camDir( gid.xy );
		let h = traverse( cam.o.xyz, d, 1e5, false );
		if ( h.tri == NONE ) { gout[ 3u * pix + 1u ] = vec4f( 0.0 ); guide[ pix ] = vec4f( 0.0 ); return; }
		let p = cam.o.xyz + d * h.t;
		var n = normalize( tnorm[ 3u * h.tri ].xyz * ( 1.0 - h.u - h.v ) + tnorm[ 3u * h.tri + 1u ].xyz * h.u + tnorm[ 3u * h.tri + 2u ].xyz * h.v );
		if ( dot( n, d ) > 0.0 ) { n = -n; }
		let isFloor = p.z < 1e-4 && n.z > 0.99;
		// the model wears the material (triplanar, normal-mapped); the floor stays dark and glossy
		var alb = vec3f( 0.05, 0.05, 0.055 );
		var rs = 0.25;
		var ns = n;
		if ( ! isFloor ) {
			let lod = texLod( h.t );
			if ( matU.clay > 0.5 ) {
				alb = vec3f( 0.45 );
				rs = 0.6;
			} else {
				alb = triTex( tAlb, p, n, lod ).rgb;
				rs = clamp( triTex( tRgh, p, n, lod ).r, 0.05, 1.0 ) + select( 0.0, 2.0, triTex( tMet, p, n, lod ).r > 0.5 );
			}
			ns = triNormal( tNrm, p, n, lod );
		}
		gout[ 3u * pix ] = vec4f( p, h.t );
		gout[ 3u * pix + 1u ] = vec4f( ns, select( 1.0, 4.0, isFloor ) );
		gout[ 3u * pix + 2u ] = vec4f( alb, rs );
		// the denoiser keeps the smooth normal, so the normal map does not stop its filter
		guide[ pix ] = vec4f( n, select( h.t, -h.t, isFloor ) );
	}` },

	// RIS over 16 power-sampled spots, then one visibility ray for the winner
	initial: { uses: [ 'cam', 'nodes', 'tris', 'gcur', 'lights', 'alias', 'resOut' ], code: TRAVERSE + LIGHTS + PICK + MAIN + /* wgsl */`
		let s = surfFrom( gcur[ 3u * pix ], gcur[ 3u * pix + 1u ], gcur[ 3u * pix + 2u ], cam.o.xyz );
		if ( ! s.ok ) { resOut[ pix ] = pack( Res( NONE, 0.0, 0.0, 0.0 ) ); return; }
		var seed = ( pix * 9781u ) ^ ( cam.frame * 0x9e3779b9u + 1u );
		var st = Stream( NONE, 0.0, 0.0 );
		for ( var c = 0u; c < ${ CANDIDATES }u; c++ ) {
			let li = pickLight( &seed );
			let p = lum( unshadowed( s, li ) );
			add( &st, li, p, p / ( lights[ li ].col.w * ${ CANDIDATES }.0 ), &seed );
		}
		var r = Res( st.y, select( 0.0, st.wsum / st.p, st.p > 0.0 ), 1.0, st.p );
		if ( VARIANT == 0u && r.y != NONE && ! visible( s, r.y ) ) { r.W = 0.0; r.p = 0.0; }
		resOut[ pix ] = pack( r );
	}` },

	// temporal reuse: pairwise MIS with the reprojected history (k = 1), M capped at 20
	temporal: { uses: [ 'cam', 'nodes', 'tris', 'gcur', 'gprev', 'lights', 'resIn', 'hist', 'resOut' ], code: TRAVERSE + LIGHTS + COMBINE + MAIN + /* wgsl */`
		let g0 = gcur[ 3u * pix ];
		let s = surfFrom( g0, gcur[ 3u * pix + 1u ], gcur[ 3u * pix + 2u ], cam.o.xyz );
		let c = unpack( resIn[ pix ] );
		if ( ! s.ok ) { resOut[ pix ] = pack( c ); return; }
		var seed = ( pix * 7919u ) ^ ( cam.frame * 0x85ebca6bu + 3u );
		var ns: array<Res, 2>;
		var nsurf: array<Surf, 2>;
		var k = 0u;
		let pp = prevPixel( g0.xyz );
		if ( cam.frame > 0u && pp.x >= 0 ) {
			let q = u32( pp.y ) * W + u32( pp.x );
			let ps = surfFrom( gprev[ 3u * q ], gprev[ 3u * q + 1u ], gprev[ 3u * q + 2u ], cam.po.xyz );
			// same surface? (geometry only, so the MIS weights stay valid)
			if ( ps.ok && dot( ps.n, s.n ) > 0.8 && length( ps.p - s.p ) < 0.02 * g0.w ) {
				var h = unpack( hist[ q ] );
				h.M = min( h.M, ${ M_CAP }.0 * c.M );
				ns[ 0 ] = h;
				nsurf[ 0 ] = ps;
				k = 1u;
			}
		}
		resOut[ pix ] = pack( combine( s, c, ns, nsurf, k, &seed ) );
	}` },

	// spatial reuse: 2 neighbours in a 30 px disk, pairwise MIS; the result is next frame's history
	spatial: { uses: [ 'cam', 'nodes', 'tris', 'gcur', 'lights', 'resIn', 'resOut' ], code: TRAVERSE + LIGHTS + COMBINE + MAIN + /* wgsl */`
		let g0 = gcur[ 3u * pix ];
		let s = surfFrom( g0, gcur[ 3u * pix + 1u ], gcur[ 3u * pix + 2u ], cam.o.xyz );
		let c = unpack( resIn[ pix ] );
		if ( ! s.ok ) { resOut[ pix ] = pack( c ); return; }
		var seed = ( pix * 6271u ) ^ ( cam.frame * 0x27d4eb2du + 7u );
		var ns: array<Res, 2>;
		var nsurf: array<Surf, 2>;
		var k = 0u;
		for ( var i = 0u; i < ${ SPATIAL }u; i++ ) {
			let a = lcg( &seed ) * 2.0 * PI;
			let rr = sqrt( lcg( &seed ) ) * ${ RADIUS }.0;
			let q2 = clamp( vec2i( gid.xy ) + vec2i( vec2f( cos( a ), sin( a ) ) * rr ), vec2i( 0 ), vec2i( i32( W ) - 1, i32( H ) - 1 ) );
			let q = u32( q2.y ) * W + u32( q2.x );
			if ( q == pix ) { continue; }
			let n0 = gcur[ 3u * q ];
			let nsf = surfFrom( n0, gcur[ 3u * q + 1u ], gcur[ 3u * q + 2u ], cam.o.xyz );
			if ( ! nsf.ok || dot( nsf.n, s.n ) < 0.8 || abs( n0.w - g0.w ) > 0.1 * g0.w ) { continue; }
			ns[ k ] = unpack( resIn[ q ] );
			nsurf[ k ] = nsf;
			k++;
		}
		var r = combine( s, c, ns, nsurf, k, &seed );
		r.M = min( r.M, ${ M_CAP }.0 );
		resOut[ pix ] = pack( r );
	}` },

	// shading f(y) * W; in variant 0 the target already holds visibility, otherwise one shadow ray
	shade: { uses: [ 'cam', 'nodes', 'tris', 'tnorm', 'gcur', 'lights', 'alias', 'resIn', 'out', 'matU', 'tAlb', 'smp' ], code: TRAVERSE + LIGHTS + PICK + MATERIAL_ALB + MAIN + /* wgsl */`
		let rd = camDir( gid.xy );
		let g1 = gcur[ 3u * pix + 1u ];
		var col = vec3f( 0.0 );
		if ( g1.w <= 0.0 ) {
			col = select( vec3f( 0.0 ), studioBg( rd ), cam.live == 1u );
		} else {
			let s = surfFrom( gcur[ 3u * pix ], g1, gcur[ 3u * pix + 2u ], cam.o.xyz );
			let r = unpack( resIn[ pix ] );
			if ( r.y != NONE && r.W > 0.0 ) {
				var vis = r.p > 0.0;
				if ( VARIANT != 0u ) { vis = visible( s, r.y ); }
				if ( vis ) { col = unshadowed( s, r.y ) * r.W; }
			}
			if ( cam.live == 1u && g1.w == 4.0 ) {
				// floor mirror reflection; the hit is lit by 2 power-sampled spots, unshadowed
				let rdir = reflect( rd, s.n );
				let h = traverse( s.p + s.n * 1e-4, rdir, 1e5, false );
				var rc = studioBg( rdir );
				if ( h.tri != NONE ) {
					var hn = normalize( tnorm[ 3u * h.tri ].xyz * ( 1.0 - h.u - h.v ) + tnorm[ 3u * h.tri + 1u ].xyz * h.u + tnorm[ 3u * h.tri + 2u ].xyz * h.v );
					if ( dot( hn, rdir ) > 0.0 ) { hn = -hn; }
					let hp = s.p + rdir * h.t;
					let hs = Surf( hp, hn, triAlb( hp, hn, texLod( h.t + length( s.p - cam.o.xyz ) ) ), 0.5, -rdir, true );
					var seed = ( pix * 3301u ) ^ ( cam.frame * 0x165667b1u );
					rc = vec3f( 0.0 );
					for ( var i = 0u; i < 2u; i++ ) {
						let li = pickLight( &seed );
						rc += unshadowed( hs, li ) / ( lights[ li ].col.w * 2.0 );
					}
				}
				let f = 0.04 + 0.96 * pow( max( 0.0, 1.0 - dot( s.n, -rd ) ), 5.0 );
				col += rc * mix( 0.3, 1.0, f ) * exp( -length( s.p.xy ) * 4.0 );
			}
		}
		let hist = outBuf[ W * H + pix ];
		let acc = mix( hist.rgb, col, 1.0 / ( hist.w + 1.0 ) );
		outBuf[ pix ] = vec4f( acc, min( hist.w + 1.0, f32( cam.p2 >> 8u ) ) );
		outBuf[ W * H + pix ] = vec4f( col, 1.0 );
	}` },

	// exact direct lighting: every spot, one shadow ray each
	reference: { uses: [ 'cam', 'nodes', 'tris', 'gcur', 'lights', 'ref' ], code: TRAVERSE + LIGHTS + MAIN + /* wgsl */`
		let g1 = gcur[ 3u * pix + 1u ];
		var sum = vec3f( 0.0 );
		if ( g1.w > 0.0 ) {
			let s = surfFrom( gcur[ 3u * pix ], g1, gcur[ 3u * pix + 2u ], cam.o.xyz );
			for ( var li = 0u; li < NL; li++ ) {
				let c = unshadowed( s, li );
				if ( lum( c ) > 0.0 && visible( s, li ) ) { sum += c; }
			}
		} else if ( cam.live == 1u ) {
			sum = studioBg( camDir( gid.xy ) );
		}
		refBuf[ pix ] = vec4f( sum, 1.0 );
	}` },
};

// ---------------------------------------------------------------- denoiser (SVGF: Schied et al. 2017)
// cam.p2 bit 0 = denoiser on, bit 1 = drop the history (lights changed)

const DN_COMMON = /* wgsl */`
fn lum3( c: vec3f ) -> f32 { return dot( c, vec3f( 0.2126, 0.7152, 0.0722 ) ); }
`;

const DN_KERNELS = {

	// temporal accumulation of the raw frame with reprojection, plus luminance moments for the variance
	dnTemporal: { uses: [ 'cam', 'gcur', 'gprev', 'outR', 'hAin', 'hMin', 'hAout', 'hMout', 'dnOut' ], code: DN_COMMON + MAIN + /* wgsl */`
		let c = outBuf[ W * H + pix ].rgb;
		let l = lum3( c );
		let g0 = gcur[ 3u * pix ];
		let g1 = gcur[ 3u * pix + 1u ];
		if ( g1.w <= 0.0 ) {
			hAout[ pix ] = vec4f( c, 0.0 );
			hMout[ pix ] = vec4f( l, l * l, 0.0, 0.0 );
			dnOut[ pix ] = vec4f( c, 0.0 );
			return;
		}
		var prevC = vec4f( 0.0 );
		var prevM = vec4f( 0.0 );
		var ok = false;
		let pp = prevPixel( g0.xyz );
		if ( cam.frame > 0u && ( cam.p2 & 2u ) == 0u && pp.x >= 0 ) {
			let q = u32( pp.y ) * W + u32( pp.x );
			let p0 = gprev[ 3u * q ];
			let p1 = gprev[ 3u * q + 1u ];
			// same surface: same material, close normal and position (disocclusions start over)
			if ( p1.w == g1.w && dot( p1.xyz, g1.xyz ) > 0.9 && length( p0.xyz - g0.xyz ) < 0.01 * g0.w + 1e-4 ) {
				prevC = hAin[ q ];
				prevM = hMin[ q ];
				ok = prevC.w > 0.0;
			}
		}
		let len = select( 1.0, min( prevC.w + 1.0, 64.0 ), ok );
		let col = mix( prevC.rgb, c, max( 1.0 / len, 0.05 ) );
		let m = mix( prevM.xy, vec2f( l, l * l ), max( 1.0 / len, 0.1 ) );
		var v = max( 0.0, m.y - m.x * m.x );
		// short history: the moments are unreliable, let the spatial filter work harder
		if ( len < 4.0 ) { v = v * 4.0 / len + l * l; }
		hAout[ pix ] = vec4f( col, len );
		hMout[ pix ] = vec4f( m, 0.0, 0.0 );
		dnOut[ pix ] = vec4f( col, v );
	}` },

	// one a-trous iteration (5x5 B3 spline, stride stepU.x) with normal, plane-distance and luminance edge stops
	dnAtrous: { uses: [ 'cam', 'guide', 'dnIn', 'dnOut', 'stepU' ], code: DN_COMMON + MAIN + /* wgsl */`
		let ctr = dnIn[ pix ];
		let gc = guide[ pix ];
		if ( gc.w == 0.0 ) { dnOut[ pix ] = ctr; return; }
		let pc = cam.o.xyz + camDir( gid.xy ) * abs( gc.w );
		let lc = lum3( ctr.rgb );
		let st = i32( stepU.x );
		let hi = vec2i( i32( W ) - 1, i32( H ) - 1 );
		// 3x3 blurred variance for a steadier luminance edge stop (first iteration only, to save bandwidth)
		var vb = ctr.w;
		if ( st == 1 ) {
			vb = 0.0;
			for ( var dy = -1; dy <= 1; dy++ ) {
				for ( var dx = -1; dx <= 1; dx++ ) {
					let q2 = clamp( vec2i( gid.xy ) + vec2i( dx, dy ), vec2i( 0 ), hi );
					vb += dnIn[ u32( q2.y ) * W + u32( q2.x ) ].w * select( 0.25, 0.5, dx == 0 ) * select( 0.25, 0.5, dy == 0 );
				}
			}
		}
		let sl = 4.0 * sqrt( max( vb, 0.0 ) ) + 1e-4;
		var k5 = array<f32, 3>( 0.375, 0.25, 0.0625 );
		var sum = vec3f( 0.0 );
		var wsum = 0.0;
		var vsum = 0.0;
		for ( var dy = -2; dy <= 2; dy++ ) {
			for ( var dx = -2; dx <= 2; dx++ ) {
				let q2 = vec2i( gid.xy ) + vec2i( dx, dy ) * st;
				if ( any( q2 < vec2i( 0 ) ) || any( q2 > hi ) ) { continue; }
				let q = u32( q2.y ) * W + u32( q2.x );
				let gq = guide[ q ];
				// same material (sign of the distance), not background
				if ( gq.w * gc.w <= 0.0 ) { continue; }
				let pq = cam.o.xyz + camDir( vec2u( q2 ) ) * abs( gq.w );
				let sq = dnIn[ q ];
				let wn = pow( max( 0.0, dot( gq.xyz, gc.xyz ) ), 64.0 );
				let wz = exp( -abs( dot( pq - pc, gc.xyz ) ) / ( 0.004 * abs( gc.w ) + 1e-5 ) );
				let wl = exp( -abs( lum3( sq.rgb ) - lc ) / sl );
				let w = k5[ abs( dx ) ] * k5[ abs( dy ) ] * wn * wz * wl;
				sum += w * sq.rgb;
				wsum += w;
				vsum += w * w * sq.w;
			}
		}
		dnOut[ pix ] = vec4f( sum / wsum, vsum / ( wsum * wsum ) );
	}` },

	// accumulation history for this frame, into the second half of outBuf (shade overwrites it after use):
	// same pixel while the camera is still; after a move (cam.p2 bit 2) the previous accumulation is
	// reprojected with its sample count capped at 8, so view-dependent highlights fade out quickly.
	// bit 1 (lighting changed) drops it; cam.p2 >> 8 is the per-pixel sample cap.
	accProject: { uses: [ 'cam', 'gcur', 'gprev', 'out' ], code: MAIN + /* wgsl */`
		var h = vec4f( 0.0 );
		if ( ( cam.p2 & 2u ) == 0u ) {
			let g1 = gcur[ 3u * pix + 1u ];
			if ( cam.accum > 0u ) {
				h = outBuf[ pix ];
			} else if ( ( cam.p2 & 4u ) != 0u && g1.w > 0.0 ) {
				let g0 = gcur[ 3u * pix ];
				let pp = prevPixel( g0.xyz );
				if ( pp.x >= 0 ) {
					let q = u32( pp.y ) * W + u32( pp.x );
					let p0 = gprev[ 3u * q ];
					let p1 = gprev[ 3u * q + 1u ];
					if ( p1.w == g1.w && dot( p1.xyz, g1.xyz ) > 0.9 && length( p0.xyz - g0.xyz ) < 0.01 * g0.w + 1e-4 ) {
						h = outBuf[ q ];
						h.w = min( h.w, 8.0 );
					}
				}
			}
		}
		h.w = min( h.w, f32( cam.p2 >> 8u ) );
		outBuf[ W * H + pix ] = h;
	}` },

	// display: denoised while moving, then a progressive hand-over to the unbiased accumulation
	dnCompose: { uses: [ 'cam', 'outR', 'dnIn', 'disp' ], code: MAIN + /* wgsl */`
		let acc = outBuf[ pix ].rgb;
		var o = acc;
		if ( ( cam.p2 & 1u ) != 0u ) {
			let a = outBuf[ pix ].w;
			o = mix( dnIn[ pix ].rgb, acc, a / ( a + 64.0 ) );
		}
		disp[ pix ] = vec4f( o, 1.0 );
	}` },
};

// ---------------------------------------------------------------- GPU setup

// mip chain from an ImageBitmap (the browser resamples each level)
async function textureFrom( device, bitmap, format ) {

	const levels = Math.floor( Math.log2( Math.max( bitmap.width, bitmap.height ) ) ) + 1;
	const tex = device.createTexture( { size: [ bitmap.width, bitmap.height ], format, mipLevelCount: levels,
		usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST | GPUTextureUsage.RENDER_ATTACHMENT } );
	for ( let l = 0; l < levels; l ++ ) {
		const w = Math.max( 1, bitmap.width >> l ), h = Math.max( 1, bitmap.height >> l );
		const src = l === 0 ? bitmap : await createImageBitmap( bitmap, { resizeWidth: w, resizeHeight: h, resizeQuality: 'high' } );
		device.queue.copyExternalImageToTexture( { source: src }, { texture: tex, mipLevel: l }, [ w, h ] );
	}
	return tex;

}

function solidTexture( device, rgba, format ) {

	const tex = device.createTexture( { size: [ 1, 1 ], format, usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST } );
	device.queue.writeTexture( { texture: tex }, new Uint8Array( rgba ), { bytesPerRow: 4 }, [ 1, 1 ] );
	return tex;

}

export async function setupUnbiased( device, { geo, root, radius }, size = QUALITY[ 0 ] ) {

	W = size.w;
	H = size.h;
	N = W * H;
	COMMON = atResolution( COMMON_MAX );

	const S = GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST | GPUBufferUsage.COPY_SRC;
	const mk = ( size, usage = S ) => device.createBuffer( { size, usage } );
	const upload = data => { const b = mk( data.byteLength ); device.queue.writeBuffer( b, 0, data ); return b; };

	const idx = geo.index.array, p = geo.attributes.position.array, nrm = geo.attributes.normal.array, nt = idx.length / 3;
	const tri = new Float32Array( nt * 12 ), tn = new Float32Array( nt * 12 );
	for ( let t = 0; t < nt; t ++ ) {
		const a = idx[ t * 3 ] * 3, b = idx[ t * 3 + 1 ] * 3, c = idx[ t * 3 + 2 ] * 3;
		for ( let k = 0; k < 3; k ++ ) {
			tri[ t * 12 + k ] = p[ a + k ];
			tri[ t * 12 + 4 + k ] = p[ b + k ] - p[ a + k ];
			tri[ t * 12 + 8 + k ] = p[ c + k ] - p[ a + k ];
			tn[ t * 12 + k ] = nrm[ a + k ];
			tn[ t * 12 + 4 + k ] = nrm[ b + k ];
			tn[ t * 12 + 8 + k ] = nrm[ c + k ];
		}
	}
	const spots = makeSpots();
	const initial = spotBuffers( spots );
	const B = {
		cam: mk( 144, GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST ),
		nodes: upload( new Uint8Array( root ) ), tris: upload( tri ), tnorm: upload( tn ),
		g: [ mk( N * 48 ), mk( N * 48 ) ],
		lights: upload( initial.data ), alias: upload( new Uint8Array( initial.table ) ),
		resInit: mk( N * 16 ), resTemp: mk( N * 16 ), resHist: mk( N * 16 ),
		// outBuf: [0, N) accumulation, [N, 2N) this frame's raw value
		out: mk( N * 32 ), ref: mk( N * 16 ), disp: mk( N * 16 ),
		hA: [ mk( N * 16 ), mk( N * 16 ) ], hM: [ mk( N * 16 ), mk( N * 16 ) ], dn: [ mk( N * 16 ), mk( N * 16 ) ],
		guide: mk( N * 16 ),
		matU: mk( 32, GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST ),
		steps: [ 1, 2, 4, 8 ].map( st => { const b = mk( 16, GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST ); device.queue.writeBuffer( b, 0, new Uint32Array( [ st, 0, 0, 0 ] ) ); return b; } ),
	};

	// pipelines for each variant
	const pipes = [];
	for ( let v = 0; v < 3; v ++ ) {
		pipes[ v ] = {};
		for ( const [ name, k ] of Object.entries( KERNELS ) ) {
			if ( v > 0 && ( name === 'primary' || name === 'reference' ) ) { pipes[ v ][ name ] = pipes[ 0 ][ name ]; continue; }
			const decls = `const SCENE = 1u;\nconst VARIANT = ${ v }u;\n` + k.uses.map( ( u, i ) => `@group( 0 ) @binding( ${ i } ) ${ DECLS[ u ] }` ).join( '\n' );
			const module = device.createShaderModule( { code: decls + COMMON + k.code } );
			const ci = await module.getCompilationInfo();
			for ( const m of ci.messages ) if ( m.type === 'error' ) throw new Error( `${ name }: ${ m.message } (ligne ${ m.lineNum })` );
			pipes[ v ][ name ] = { k, pipe: await device.createComputePipelineAsync( { layout: 'auto', compute: { module, entryPoint: 'main' } } ) };
		}
	}

	// material: jade until a generated material arrives (1x1 textures, so the shaders never branch)
	const smp = device.createSampler( { addressModeU: 'repeat', addressModeV: 'repeat', magFilter: 'linear', minFilter: 'linear', mipmapFilter: 'linear', maxAnisotropy: 8 } );
	const JADE = {
		albedo: solidTexture( device, [ 69, 180, 124, 255 ], 'rgba8unorm-srgb' ),
		normal: solidTexture( device, [ 128, 128, 255, 255 ], 'rgba8unorm' ),
		roughness: solidTexture( device, [ 77, 77, 77, 255 ], 'rgba8unorm' ),
		metallic: solidTexture( device, [ 0, 0, 0, 255 ], 'rgba8unorm' ),
	};
	let mat = { ...JADE };
	// same density as the MatterLift preview: 2.5 tiles per bounding-sphere radius
	// look-dev settings from MatterLift: normal strength, tiling, clay
	let look = { normalScale: 1, tiling: 1, clay: false };
	let texSize = 1;
	const writeMatU = () => device.queue.writeBuffer( B.matU, 0, new Float32Array( [
		2.5 / radius * look.tiling, texSize, 2 * Math.tan( 15 * Math.PI / 180 ) / H, look.normalScale, look.clay ? 1 : 0, 0, 0, 0 ] ) );
	writeMatU();
	const setLook = settings => {
		look = { ...look, ...settings };
		writeMatU();
	};

	// bind groups for both G-Buffer parities
	const bind = ( v, name, par ) => {
		const res = { matU: B.matU, smp, tAlb: mat.albedo.createView(), tNrm: mat.normal.createView(), tRgh: mat.roughness.createView(), tMet: mat.metallic.createView(),
			cam: B.cam, nodes: B.nodes, tris: B.tris, tnorm: B.tnorm, gout: B.g[ par ], guideW: B.guide, gcur: B.g[ par ], gprev: B.g[ 1 - par ],
			lights: B.lights, alias: B.alias, out: B.out, ref: B.ref,
			resIn: { temporal: B.resInit, spatial: B.resTemp, shade: B.resHist }[ name ], hist: B.resHist,
			resOut: { initial: B.resInit, temporal: B.resTemp, spatial: B.resHist }[ name ] };
		const { k, pipe } = pipes[ v ][ name ];
		return device.createBindGroup( { layout: pipe.getBindGroupLayout( 0 ), entries: k.uses.map( ( u, i ) => ( { binding: i, resource: res[ u ] instanceof GPUBuffer ? { buffer: res[ u ] } : res[ u ] } ) ) } );
	};
	const ORDER = [ 'primary', 'initial', 'temporal', 'spatial', 'shade' ];
	const makeGroups = () => [ 0, 1, 2 ].map( v => [ 0, 1 ].map( par => Object.fromEntries( [ ...ORDER, 'reference' ].map( n => [ n, bind( v, n, par ) ] ) ) ) );
	let groups = makeGroups();
	// a generated material (ImageBitmaps; any missing map keeps the jade default), or null for jade
	const setMaterial = async maps => {
		const next = { ...JADE };
		const formats = { albedo: 'rgba8unorm-srgb', normal: 'rgba8unorm', roughness: 'rgba8unorm', metallic: 'rgba8unorm' };
		for ( const key of Object.keys( formats ) ) if ( maps?.[ key ] ) next[ key ] = await textureFrom( device, maps[ key ], formats[ key ] );
		for ( const key of Object.keys( mat ) ) if ( mat[ key ] !== JADE[ key ] ) mat[ key ].destroy();
		mat = next;
		texSize = maps?.albedo ? maps.albedo.width : 1;
		writeMatU();
		groups = makeGroups();
	};

	const dnPipes = {};
	for ( const [ name, k ] of Object.entries( DN_KERNELS ) ) {
		const decls = 'const SCENE = 1u;\nconst VARIANT = 0u;\n' + k.uses.map( ( u, i ) => `@group( 0 ) @binding( ${ i } ) ${ DECLS[ u ] }` ).join( '\n' );
		const module = device.createShaderModule( { code: decls + COMMON + k.code } );
		const ci = await module.getCompilationInfo();
		for ( const m of ci.messages ) if ( m.type === 'error' ) throw new Error( `${ name }: ${ m.message } (line ${ m.lineNum })` );
		dnPipes[ name ] = { k, pipe: await device.createComputePipelineAsync( { layout: 'auto', compute: { module, entryPoint: 'main' } } ) };
	}
	const dnBind = ( name, res ) => {
		const { k, pipe } = dnPipes[ name ];
		return device.createBindGroup( { layout: pipe.getBindGroupLayout( 0 ), entries: k.uses.map( ( u, i ) => ( { binding: i, resource: { buffer: res[ u ] } } ) ) } );
	};
	// temporal pass ping-pongs its history with the G-Buffer parity; the a-trous passes alternate dn[0] / dn[1]
	const dnGroups = [ 0, 1 ].map( par => [
		[ 'dnTemporal', dnBind( 'dnTemporal', { cam: B.cam, gcur: B.g[ par ], gprev: B.g[ 1 - par ], outR: B.out, hAin: B.hA[ 1 - par ], hMin: B.hM[ 1 - par ], hAout: B.hA[ par ], hMout: B.hM[ par ], dnOut: B.dn[ 0 ] } ) ],
		...B.steps.map( ( st, i ) => [ 'dnAtrous', dnBind( 'dnAtrous', { cam: B.cam, guide: B.guide, dnIn: B.dn[ i % 2 ], dnOut: B.dn[ 1 - i % 2 ], stepU: st } ) ] ),
		[ 'dnCompose', dnBind( 'dnCompose', { cam: B.cam, outR: B.out, dnIn: B.dn[ B.steps.length % 2 ], disp: B.disp } ) ],
	] );

	const accGroups = [ 0, 1 ].map( par => dnBind( 'accProject', { cam: B.cam, gcur: B.g[ par ], gprev: B.g[ 1 - par ], out: B.out } ) );

	const camData = new ArrayBuffer( 144 );
	const camF = new Float32Array( camData ), camU = new Uint32Array( camData );

	// encodes one frame (variant v) and optionally times each pass
	const encode = ( enc, v, frame, qs, denoise = false ) => {
		const par = frame & 1;
		ORDER.forEach( ( name, i ) => {
			const cp = enc.beginComputePass( qs ? { timestampWrites: { querySet: qs, beginningOfPassWriteIndex: i * 2, endOfPassWriteIndex: i * 2 + 1 } } : {} );
			cp.setPipeline( pipes[ v ][ name ].pipe );
			cp.setBindGroup( 0, groups[ v ][ par ][ name ] );
			cp.dispatchWorkgroups( W / 8, Math.ceil( H / 8 ) );
			cp.end();
			if ( name === 'primary' ) {
				const ap = enc.beginComputePass();
				ap.setPipeline( dnPipes.accProject.pipe );
				ap.setBindGroup( 0, accGroups[ par ] );
				ap.dispatchWorkgroups( W / 8, Math.ceil( H / 8 ) );
				ap.end();
			}
		} );
		const passes = denoise ? dnGroups[ par ] : [ dnGroups[ par ].at( - 1 ) ];
		passes.forEach( ( [ name, bg ], i ) => {
			const tw = {};
			if ( qs && i === 0 ) tw.beginningOfPassWriteIndex = 10;
			if ( qs && i === passes.length - 1 ) tw.endOfPassWriteIndex = 11;
			const cp = enc.beginComputePass( Object.keys( tw ).length ? { timestampWrites: { querySet: qs, ...tw } } : {} );
			cp.setPipeline( dnPipes[ name ].pipe );
			cp.setBindGroup( 0, bg );
			cp.dispatchWorkgroups( W / 8, Math.ceil( H / 8 ) );
			cp.end();
		} );
	};
	const encodeRef = ( enc, frame ) => {
		const cp = enc.beginComputePass();
		cp.setPipeline( pipes[ 0 ].reference.pipe );
		cp.setBindGroup( 0, groups[ 0 ][ frame & 1 ].reference );
		cp.dispatchWorkgroups( W / 8, Math.ceil( H / 8 ) );
		cp.end();
	};
	// camera basis from a three camera: origin, right * tan(fov/2) * aspect, up * tan(fov/2), forward
	const setCamera = ( cam, prev, frame, accum, live, flags = 0 ) => {
		const e = cam.matrixWorld.elements;
		const hh = Math.tan( cam.fov * Math.PI / 360 ), hw = hh * W / H;
		const basis = [ e[ 12 ], e[ 13 ], e[ 14 ], 0, e[ 0 ] * hw, e[ 1 ] * hw, e[ 2 ] * hw, 0, e[ 4 ] * hh, e[ 5 ] * hh, e[ 6 ] * hh, 0, - e[ 8 ], - e[ 9 ], - e[ 10 ], 0 ];
		camF.set( basis );
		camF.set( prev || basis, 16 );
		camU[ 32 ] = frame;
		camU[ 33 ] = accum;
		camU[ 34 ] = live ? 1 : 0;
		camU[ 35 ] = flags;
		device.queue.writeBuffer( B.cam, 0, camData );
		return basis;
	};
	// switch spots on / off, change how many are lit, or give them all one colour
	const setSpots = opts => {
		const { data, table } = spotBuffers( spots, opts );
		device.queue.writeBuffer( B.lights, 0, data );
		device.queue.writeBuffer( B.alias, 0, table );
	};
	// display pass only (denoiser on / off while rendering is stopped)
	const encodeCompose = ( enc, frame ) => {
		const [ name, bg ] = dnGroups[ frame & 1 ].at( - 1 );
		const cp = enc.beginComputePass();
		cp.setPipeline( dnPipes[ name ].pipe );
		cp.setBindGroup( 0, bg );
		cp.dispatchWorkgroups( W / 8, Math.ceil( H / 8 ) );
		cp.end();
	};
	const destroy = () => {
		for ( const b of Object.values( B ) ) for ( const x of [ b ].flat() ) x.destroy?.();
		for ( const t of Object.values( mat ) ) if ( ! Object.values( JADE ).includes( t ) ) t.destroy();
		for ( const t of Object.values( JADE ) ) t.destroy();
	};
	return { B, encode, encodeRef, encodeCompose, setCamera, setSpots, setMaterial, setLook, destroy, spots, ORDER };

}

// ---------------------------------------------------------------- bias test against the exact reference

// cam.p2 flags: per-pixel sample cap in bits 8+, 0xffffff = unlimited
const NO_CAP = 0xffffff << 8;

export async function testUnbiased( device, R, cam, log, frames = 1024 ) {

	const { B, encode, encodeRef, setCamera, ORDER } = R;
	cam.updateMatrixWorld();
	const read = async buf => {
		const rb = device.createBuffer( { size: N * 16, usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST } );
		const e = device.createCommandEncoder();
		e.copyBufferToBuffer( buf, 0, rb, 0, N * 16 );
		device.queue.submit( [ e.finish() ] );
		await rb.mapAsync( GPUMapMode.READ );
		const a = new Float32Array( rb.getMappedRange().slice( 0 ) );
		rb.destroy();
		return a;
	};
	const lumAt = ( a, i ) => 0.2126 * a[ i * 4 ] + 0.7152 * a[ i * 4 + 1 ] + 0.0722 * a[ i * 4 + 2 ];

	// reference (primary pass first, for the G-Buffer)
	setCamera( cam, null, 0, 0, false, NO_CAP );
	let enc = device.createCommandEncoder();
	encode( enc, 0, 0 );
	device.queue.submit( [ enc.finish() ] );
	let t0 = performance.now();
	enc = device.createCommandEncoder();
	encodeRef( enc, 0 );
	device.queue.submit( [ enc.finish() ] );
	await device.queue.onSubmittedWorkDone();
	const refMs = performance.now() - t0;
	const ref = await read( B.ref );
	let refSum = 0, covered = [];
	for ( let i = 0; i < N; i ++ ) { const l = lumAt( ref, i ); if ( l > 0 ) { refSum += l; covered.push( i ); } }
	log( `Exact reference (${ NUM_LIGHTS } spots x 1 shadow ray / pixel): ${ refMs.toFixed( 0 ) } ms, ${ covered.length } lit pixels` );

	const qs = device.createQuerySet( { type: 'timestamp', count: 12 } );
	const qr = device.createBuffer( { size: ORDER.length * 16, usage: GPUBufferUsage.QUERY_RESOLVE | GPUBufferUsage.COPY_SRC } );
	const qm = device.createBuffer( { size: ORDER.length * 16, usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST } );
	const out = [];
	for ( let v = 0; v < 3; v ++ ) {
		for ( const b of [ B.resInit, B.resTemp, B.resHist, B.out ] ) device.queue.writeBuffer( b, 0, new Uint8Array( N * 16 ) );
		const times = ORDER.map( () => [] );
		let oneFrame = null;
		for ( let f = 0; f < frames; f ++ ) {
			setCamera( cam, null, f, f, false, NO_CAP );
			enc = device.createCommandEncoder();
			const timed = f >= 8 && f < 68;
			encode( enc, v, f, timed ? qs : null );
			if ( timed ) {
				enc.resolveQuerySet( qs, 0, ORDER.length * 2, qr, 0 );
				// (slots 10 / 11 hold the display pass, not part of ReSTIR)
				enc.copyBufferToBuffer( qr, 0, qm, 0, ORDER.length * 16 );
			}
			device.queue.submit( [ enc.finish() ] );
			if ( timed ) {
				await qm.mapAsync( GPUMapMode.READ );
				const t = new BigInt64Array( qm.getMappedRange().slice( 0 ) );
				qm.unmap();
				ORDER.forEach( ( _, i ) => times[ i ].push( Number( t[ i * 2 + 1 ] - t[ i * 2 ] ) / 1e6 ) );
			}
			if ( f === 0 ) oneFrame = await read( B.out );
			if ( f % 64 === 63 ) await device.queue.onSubmittedWorkDone();
		}
		const acc = await read( B.out );
		let sum = 0, abs = 0, abs1 = 0;
		for ( const i of covered ) {
			const r = lumAt( ref, i );
			sum += lumAt( acc, i ) - r;
			abs += Math.abs( lumAt( acc, i ) - r );
			abs1 += Math.abs( lumAt( oneFrame, i ) - r );
		}
		const med = a => [ ...a ].sort( ( x, y ) => x - y )[ a.length >> 1 ];
		const pass = Object.fromEntries( ORDER.map( ( n, i ) => [ n, med( times[ i ] ) ] ) );
		const total = Object.values( pass ).reduce( ( a, b ) => a + b, 0 );
		const row = { variant: MODES[ v ], biasPct: sum / refSum * 100, maePct: abs / refSum * 100, mae1Pct: abs1 / refSum * 100, totalMs: total, pass };
		out.push( row );
		log( `\n[${ MODES[ v ] }]\n  mean bias ${ row.biasPct.toFixed( 2 ) } % | abs. error ${ frames } frames ${ row.maePct.toFixed( 2 ) } % | abs. error 1 frame ${ row.mae1Pct.toFixed( 1 ) } %`
			+ `\n  GPU ${ total.toFixed( 2 ) } ms : ` + ORDER.map( n => `${ n } ${ pass[ n ].toFixed( 2 ) }` ).join( ', ' ) );
	}
	return out;

}

// ---------------------------------------------------------------- live viewer

// Builds the renderer at the best quality the GPU can allocate: an out-of-memory error steps down a level.
async function buildAtQuality( device, scene, level ) {

	for ( let q = level; q < QUALITY.length; q ++ ) {
		device.pushErrorScope( 'out-of-memory' );
		const R = await setupUnbiased( device, scene, QUALITY[ q ] );
		if ( ! await device.popErrorScope() ) return { R, level: q };
		R.destroy();
	}
	throw new Error( 'not enough GPU memory, even at the lowest quality' );

}

export async function liveUnbiased( device, scene, sceneCam, results, triangles, bvh ) {

	// Live RT runs on any WebGPU GPU (NVIDIA, AMD, Intel, Apple, Qualcomm): plain WGSL, default limits,
	// GPU timestamps only when offered. "Auto" quality starts high and steps down until a frame
	// takes under ~40 ms: first the cheaper unbiased variant, then a lower internal resolution.
	let built = await buildAtQuality( device, scene, 0 );
	let R = built.R;
	let { B, encode, encodeRef, setCamera, spots } = R;
	const canvas = document.getElementById( 'view' );
	canvas.width = W;
	canvas.height = H;
	document.body.classList.add( 'live' );
	const hud = document.getElementById( 'hud' );

	const [ cp, ct, fov ] = sceneCam;
	const cam = new THREE.PerspectiveCamera( fov, 16 / 9, 0.01, 100 );
	cam.up.set( 0, 0, 1 );
	cam.position.set( ...cp );
	const controls = new OrbitControls( cam, canvas );
	controls.target.set( ...ct );
	controls.enableDamping = true;
	controls.dampingFactor = 0.12;
	controls.minDistance = 0.12;
	controls.maxDistance = 1.5;
	controls.zoomSpeed = 0.4;
	controls.maxPolarAngle = Math.PI * 0.495;
	controls.update();

	let variant = 0, showRef = false, refValid = false;

	// spot panel: on / off, how many, original colours or one picked colour
	const panel = document.getElementById( 'panel' );
	panel.innerHTML = `
		<label><input type="checkbox" id="spotsOn" checked> ${ NUM_LIGHTS } scene spots</label>
		<label>Count <input type="range" id="spotCount" min="1" max="${ NUM_LIGHTS }" value="${ NUM_LIGHTS }"> <span id="spotCountOut">${ NUM_LIGHTS }</span></label>
		<label><input type="radio" name="spotColor" value="orig" checked> Original colours</label>
		<label><input type="radio" name="spotColor" value="one"> Single colour <input type="color" id="spotPick" value="#ffd9a0"></label>
		<label>Power per spot <input type="range" id="spotGain" min="-20" max="20" value="0"> <span id="spotGainOut"></span></label>
		<div>My spots: <span id="customOut">0</span> / ${ MAX_CUSTOM } · Shift + click to place <button id="customClear">Clear</button></div>
		<label>Exposure <input type="range" id="exposure" min="-30" max="30" value="0"> <span id="exposureOut">0 EV</span></label>
		<label>Max accumulation <input type="range" id="accCap" min="0" max="12" value="11"> <span id="accCapOut">1024 frames</span></label>
		<label><input type="checkbox" id="accPause" checked> Stop rendering once converged (at the cap)</label>
		<label><input type="checkbox" id="keepAcc" checked> Keep the accumulation when the camera moves</label>
		<label><input type="checkbox" id="denoise" checked> Denoiser (SVGF)</label>
		<label>Quality <select id="quality"><option value="auto" selected>Auto</option>${ QUALITY.map( ( q, i ) => `<option value="${ i }">${ q.h }p</option>` ).join( '' ) }</select> <span id="qualityOut"></span></label>`;
	const $ = id => document.getElementById( id );
	const toLinear = hex => [ 1, 3, 5 ].map( i => ( parseInt( hex.slice( i, i + 2 ), 16 ) / 255 ) ** 2.2 );
	const applySpots = () => {
		const one = panel.querySelector( 'input[name=spotColor]:checked' ).value === 'one';
		$( 'spotCountOut' ).textContent = $( 'spotCount' ).value;
		// power slider: x0.1 to x10 on a log scale; the label shows the mean intensity of the lit spots
		const gain = 10 ** ( $( 'spotGain' ).value / 20 );
		const lit = [ ...spots.slice( 0, $( 'spotsOn' ).checked ? + $( 'spotCount' ).value : 0 ), ...custom ];
		const mean = lit.length ? lit.reduce( ( a, sp ) => a + sp.I, 0 ) / lit.length * gain : 0;
		$( 'spotGainOut' ).textContent = `x${ gain.toFixed( 2 ) } · mean intensity ${ ( mean * 1000 ).toFixed( 1 ) }`;
		R.setSpots( { on: $( 'spotsOn' ).checked, count: + $( 'spotCount' ).value, color: one ? toLinear( $( 'spotPick' ).value ) : null, custom, gain } );
		$( 'customOut' ).textContent = custom.length;
		reset = true;
		refValid = false;
	};
	// accumulation cap: 0 = off, then 1, 2, 4 ... 512 images, 11 = unlimited. At the cap the average keeps
	// a constant weight (moving average), or the GPU work stops when "pause" is ticked.
	const capOf = v => v >= 12 ? Infinity : v === 0 ? 0 : 2 ** ( v - 1 );
	let accCap = 1024;
	let composeDirty = false;
	// brightness: exposure in EV, applied at display (the radiance buffers are untouched)
	const expoData = new Float32Array( [ 1.4, 0, 0, 0 ] );
	const expoBuf = device.createBuffer( { size: 16, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST } );
	device.queue.writeBuffer( expoBuf, 0, expoData );
	panel.addEventListener( 'input', e => {
		// display-only: the denoiser toggle never restarts the accumulation
		if ( e.target.id === 'denoise' ) { composeDirty = true; return; }
		if ( e.target.id === 'keepAcc' || e.target.id === 'quality' ) return;
		if ( e.target.id === 'accCap' || e.target.id === 'accPause' ) {
			accCap = capOf( + $( 'accCap' ).value );
			$( 'accCapOut' ).textContent = accCap === Infinity ? 'unlimited' : accCap === 0 ? 'off' : `${ accCap } frames`;
			return;
		}
		if ( e.target.id === 'exposure' ) {
			const ev = $( 'exposure' ).value / 10;
			expoData[ 0 ] = 1.4 * 2 ** ev;
			device.queue.writeBuffer( expoBuf, 0, expoData );
			$( 'exposureOut' ).textContent = `${ ev > 0 ? '+' : '' }${ ev.toFixed( 1 ) } EV`;
			return;
		}
		applySpots();
	} );

	// Shift + click on the model or the floor: a spot 25 cm away, on the camera side, aimed at that point
	const custom = [];
	const raycaster = new THREE.Raycaster();
	let down = null;
	canvas.addEventListener( 'pointerdown', e => { down = [ e.clientX, e.clientY ]; } );
	canvas.addEventListener( 'pointerup', e => {
		if ( ! e.shiftKey || ! down || Math.hypot( e.clientX - down[ 0 ], e.clientY - down[ 1 ] ) > 4 ) return;
		// the canvas is letterboxed (object-fit: contain)
		const r = canvas.getBoundingClientRect();
		const cw = canvas.width, ch = canvas.height;
		const k = Math.min( r.width / cw, r.height / ch );
		const x = ( e.clientX - r.left - ( r.width - cw * k ) / 2 ) / ( cw * k ) * 2 - 1;
		const y = 1 - ( e.clientY - r.top - ( r.height - ch * k ) / 2 ) / ( ch * k ) * 2;
		if ( Math.abs( x ) > 1 || Math.abs( y ) > 1 ) return;
		raycaster.setFromCamera( new THREE.Vector2( x, y ), cam );
		const hit = bvh.raycastFirst( raycaster.ray, THREE.DoubleSide );
		if ( ! hit ) return;
		const n = hit.face.normal.clone();
		if ( n.dot( raycaster.ray.direction ) > 0 ) n.negate();
		const toCam = cam.position.clone().sub( hit.point ).normalize();
		const pos = hit.point.clone().add( toCam.multiplyScalar( 0.6 ).add( n.multiplyScalar( 0.4 ) ).add( new THREE.Vector3( 0, 0, 0.5 ) ).normalize().multiplyScalar( 0.25 ) );
		const dir = hit.point.clone().sub( pos ).normalize();
		if ( custom.length >= MAX_CUSTOM ) custom.shift();
		custom.push( { pos: pos.toArray(), dir: dir.toArray(), cosO: Math.cos( 0.26 ), cosI: Math.cos( 0.18 ), col: [ 1, 0.92, 0.82 ], I: 0.05 } );
		applySpots();
	} );
	$( 'customClear' ).addEventListener( 'click', () => { custom.length = 0; applySpots(); } );
	$( 'spotPick' ).addEventListener( 'input', () => { panel.querySelector( 'input[value=one]' ).checked = true; applySpots(); } );

	addEventListener( 'keydown', e => {
		if ( e.target.tagName === 'INPUT' ) return;
		if ( e.key >= '1' && e.key <= '3' ) { variant = + e.key - 1; showRef = false; reset = true; }
		if ( e.key === 'r' || e.key === 'R' ) { showRef = ! showRef; refValid = false; }
		if ( e.key === 'h' || e.key === 'H' ) document.body.classList.toggle( 'hide-ui' );
		if ( e.key === 'd' || e.key === 'D' ) { $( 'denoise' ).checked = ! $( 'denoise' ).checked; composeDirty = true; }
	} );

	const ctx = canvas.getContext( 'webgpu' );
	const format = navigator.gpu.getPreferredCanvasFormat();
	ctx.configure( { device, format } );
	let bp, blit;
	// the display pass reads the buffers at the internal resolution; the browser scales the canvas up
	const makeBlit = () => {
		const code = atResolution( BLIT( 1 ) ).replace( '* 1.4;', '* expo.x;' ).replace( 'var<storage, read> outBuf: array<vec4f>;', 'var<storage, read> outBuf: array<vec4f>;\n@group( 0 ) @binding( 1 ) var<uniform> expo: vec4f;' );
		const bm = device.createShaderModule( { code } );
		bp = device.createRenderPipeline( { layout: 'auto', vertex: { module: bm, entryPoint: 'vs' }, fragment: { module: bm, entryPoint: 'fs', targets: [ { format } ] } } );
		blit = [ B.disp, B.ref ].map( buf => device.createBindGroup( { layout: bp.getBindGroupLayout( 0 ), entries: [ { binding: 0, resource: { buffer: buf } }, { binding: 1, resource: { buffer: expoBuf } } ] } ) );
	};
	makeBlit();

	// GPU timer when the adapter offers it; otherwise the frame interval stands in
	// (?notimer simulates an adapter without timestamp-query)
	const ts = device.features.has( 'timestamp-query' ) && ! new URLSearchParams( location.search ).has( 'notimer' );
	const qs = ts && device.createQuerySet( { type: 'timestamp', count: 12 } );
	const qr = ts && device.createBuffer( { size: 96, usage: GPUBufferUsage.QUERY_RESOLVE | GPUBufferUsage.COPY_SRC } );
	const qm = ts && device.createBuffer( { size: 96, usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST } );
	let reading = false, gpuMs = 0, dnMs = 0, frames = 0, tFps = performance.now(), fps = 0, frameMs = 0, tLast = performance.now();
	let frame = 0, accum = 0, last = null, reset = false;

	// quality: level in QUALITY, "auto" adapts while the camera moves; rebuilding takes a second or two
	let level = built.level, auto = true, rebuilding = false, probe = { t: 0, n: 0, sum: 0 };
	const showQuality = () => { $( 'qualityOut' ).textContent = `${ W }x${ H }${ auto ? ' (auto)' : '' }`; };
	const rebuild = async next => {
		if ( rebuilding || next === level ) return;
		rebuilding = true;
		R.destroy();
		built = await buildAtQuality( device, scene, next );
		R = built.R;
		level = built.level;
		( { B, encode, encodeRef, setCamera, spots } = R );
		canvas.width = W;
		canvas.height = H;
		makeBlit();
		applySpots();
		if ( lastMaps ) await R.setMaterial( lastMaps );
		if ( lastLook ) R.setLook( lastLook );
		frame = 0;
		accum = 0;
		prevBasis = null;
		reset = true;
		refValid = false;
		probe = { t: 0, n: 0, sum: 0 };
		showQuality();
		rebuilding = false;
	};
	$( 'quality' ).addEventListener( 'input', e => {
		auto = e.target.value === 'auto';
		if ( auto ) showQuality();
		else void rebuild( + e.target.value );
	} );
	// auto: ~1 s of moving frames per level; over 40 ms, first the cheaper variant, then a lower resolution
	const adapt = ms => {
		if ( ! auto || rebuilding ) return;
		// a hidden tab or a stall (page busy, window dragged) says nothing about the GPU: start the probe over
		if ( document.hidden || ms > 250 ) { probe = { t: 0, n: 0, sum: 0 }; return; }
		if ( ! probe.t ) probe.t = performance.now();
		probe.n ++;
		probe.sum += ms;
		if ( probe.n < 8 || performance.now() - probe.t < 1000 ) return;
		const mean = probe.sum / probe.n;
		probe = { t: 0, n: 0, sum: 0 };
		if ( mean < 40 ) return;
		if ( variant === 0 ) { variant = 1; reset = true; return; }
		if ( level < QUALITY.length - 1 ) void rebuild( level + 1 );
	};

	function tick() {

		const tNow = performance.now();
		frameMs = frameMs * 0.9 + ( tNow - tLast ) * 0.1;
		tLast = tNow;
		if ( rebuilding ) { requestAnimationFrame( tick ); return; }
		controls.update();
		cam.updateMatrixWorld();
		// damping leaves sub-epsilon drift: only a visible change restarts the accumulation
		const e = Array.from( cam.matrixWorld.elements );
		const moved = ! last || e.some( ( v, i ) => Math.abs( v - last[ i ] ) > 1e-6 );
		last = e;
		accum = moved || reset ? 0 : Math.min( accum + 1, accCap, 4096 );
		// a lighting change (not a camera move) invalidates the denoiser history
		const dropHistory = reset;
		reset = false;
		const denoise = $( 'denoise' ).checked;
		// converged: nothing is traced any more until the camera, the lighting or the cap changes;
		// the orbit controls, exposure and display keep running every frame
		const paused = $( 'accPause' ).checked && accCap > 0 && accum >= accCap && ! moved && ! showRef;
		const capBits = ( accCap === Infinity ? 0xffffff : accCap ) << 8;
		prevBasis = setCamera( cam, prevBasis, frame, accum, true, ( denoise ? 1 : 0 ) | ( dropHistory ? 2 : 0 ) | ( $( 'keepAcc' ).checked ? 4 : 0 ) | capBits );

		const enc = device.createCommandEncoder();
		const timed = ts && ! reading && ! showRef && ! paused;
		if ( ! paused ) encode( enc, variant, frame, timed ? qs : null, denoise );
		else if ( composeDirty ) R.encodeCompose( enc, frame );
		composeDirty = false;
		if ( showRef && ( moved || ! refValid ) ) { encodeRef( enc, frame ); refValid = true; }
		if ( timed ) {
			enc.resolveQuerySet( qs, 0, 12, qr, 0 );
			enc.copyBufferToBuffer( qr, 0, qm, 0, 96 );
		}
		const rp = enc.beginRenderPass( { colorAttachments: [ { view: ctx.getCurrentTexture().createView(), loadOp: 'clear', storeOp: 'store', clearValue: [ 0, 0, 0, 1 ] } ] } );
		rp.setPipeline( bp );
		rp.setBindGroup( 0, blit[ showRef ? 1 : 0 ] );
		rp.draw( 3 );
		rp.end();
		device.queue.submit( [ enc.finish() ] );
		if ( timed ) {
			reading = true;
			qm.mapAsync( GPUMapMode.READ ).then( () => {
				const t = new BigInt64Array( qm.getMappedRange().slice( 0 ) );
				qm.unmap();
				gpuMs = gpuMs * 0.9 + Number( t[ 11 ] - t[ 0 ] ) / 1e6 * 0.1;
				adapt( Number( t[ 11 ] - t[ 0 ] ) / 1e6 );
				dnMs = dnMs * 0.9 + Number( t[ 11 ] - t[ 10 ] ) / 1e6 * 0.1;
				reading = false;
			} );
		}

		// without a GPU timer, the frame interval drives the automatic quality (it includes the display wait)
		if ( ! ts && ! paused && ! showRef ) adapt( frameMs );
		frames ++;
		const now = performance.now();
		if ( now - tFps > 500 ) {
			fps = frames * 1000 / ( now - tFps );
			frames = 0;
			tFps = now;
			results.live = { fps, gpuMs, dnMs, accum, variant, showRef, denoise, width: W, height: H, auto, timer: ts };
			hud.textContent = showRef
				? `EXACT REFERENCE: every spot, one shadow ray each per pixel · ${ fps.toFixed( 0 ) } FPS\n`
				: `ReSTIR DI ${ MODES[ variant ] } · ${ $( 'spotsOn' ).checked ? `${ $( 'spotCount' ).value } scene spots on` : 'scene spots off' }${ custom.length ? ` + ${ custom.length } placed` : '' }\n${ fps.toFixed( 0 ) } FPS · ${ paused ? 'GPU 0 ms (converged, rendering stopped)' : ts ? `GPU ${ gpuMs.toFixed( 2 ) } ms` : `frame ${ frameMs.toFixed( 1 ) } ms (no GPU timer)` } / frame (${ W }x${ H }${ denoise && ts ? `, denoiser ${ dnMs.toFixed( 2 ) } ms` : '' }) · ${ accum ? `accumulated ${ accum } frames${ accum >= accCap ? ' (cap)' : '' }` : 'moving' }\n`;
			hud.textContent += `${ triangles.toLocaleString( 'en' ) } triangles · Drag: orbit 360° · Wheel: zoom · Shift + click: place a spot · 1/2/3: ReSTIR variant · R: exact reference · D: denoiser · H: hide UI`;
		}
		// the frame index drives the G-Buffer / history ping-pong, so it only advances when something was rendered
		if ( ! paused ) frame ++;
		requestAnimationFrame( tick );

	}
	let prevBasis = null;
	let lastMaps = null, lastLook = null;
	showQuality();
	device.lost.then( info => {
		document.body.classList.remove( 'live' );
		const el = document.getElementById( 'loading' );
		el.classList.add( 'error' );
		el.textContent = `The GPU stopped the renderer (${ info.reason || 'device lost' }). Reload the page to try again.`;
	} );
	// inside MatterLift the spots are neutral white, so the light never tints the material being judged
	if ( document.body.classList.contains( 'embed' ) ) {
		$( 'spotPick' ).value = '#ffffff';
		panel.querySelector( 'input[value=one]' ).checked = true;
	}
	applySpots();

	// MatterLift sends the generated material as ImageBitmaps; null goes back to jade
	addEventListener( 'message', async e => {
		if ( e.source !== window.parent ) return;
		if ( e.data?.type === 'live-rt:material' ) await R.setMaterial( ( lastMaps = e.data.maps ) );
		else if ( e.data?.type === 'live-rt:settings' ) R.setLook( ( lastLook = e.data ) );
		else return;
		reset = true;
		refValid = false;
	} );
	if ( window.parent !== window ) window.parent.postMessage( { type: 'live-rt:ready' }, '*' );
	results.status = 'live';
	requestAnimationFrame( tick );

}
