// MatterLift Live RT: a Stanford scan path traced with WebGPU (unbiased ReSTIR DI over 256 spot
// lights, BVH shadow rays, SVGF denoiser), wearing the material MatterLift sends it (restir.js).
//   live.html                live viewer (inside MatterLift: ?embed, controls hidden until H)
//   live.html?model=buddha   start on another scan (dragon, buddha, lucy); MatterLift can switch later
//   live.html?test           bias test against the exact reference (every light, one shadow ray each)
import * as THREE from 'three';
import { PLYLoader } from 'three/examples/jsm/loaders/PLYLoader.js';
import { MeshBVH, SAH } from 'three-mesh-bvh';
import { W, H } from './wgsl.js';
import { liveUnbiased, setupUnbiased, testUnbiased } from './restir.js';

// The decimated Stanford scans of the WebGL preview (credits: public/models/CREDITS.md).
// zUp: the file already stands on z (the renderer's up axis); the others stand on y.
const MODELS = {
	dragon: { url: 'models/stanford_dragon.ply', zUp: false },
	buddha: { url: 'models/happy_buddha.ply', zUp: false },
	lucy: { url: 'models/lucy.ply', zUp: true },
};
const SIZE = 0.2; // every scan scaled to 20 cm along its longest side, so the spot rig fits them all
const FOV = 30;

const QUERY = new URLSearchParams( location.search );
const TEST = QUERY.has( 'test' );
const logEl = document.getElementById( 'log' );
const results = window.__results = { status: 'running', scene: {} };
const log = ( ...a ) => { logEl.textContent += a.join( ' ' ) + '\n'; console.log( ...a ); };

main().catch( e => { results.status = 'error'; results.error = String( e?.stack || e ); log( 'ERROR', e?.stack || e ); showError( e ); } );

// friendly message in the loading overlay (the raw log stays below for the test page)
function showError( e ) {

	const el = document.getElementById( 'loading' );
	el.classList.add( 'error' );
	el.textContent = navigator.gpu
		? `Something went wrong: ${ e?.message || e }`
		: 'Live RT needs WebGPU. Open it in a recent Chrome or Edge (desktop), or Safari 26.';

}

async function main() {

	if ( ! navigator.gpu ) throw new Error( 'WebGPU is not available in this browser' );
	if ( TEST ) document.getElementById( 'loading' ).style.display = 'none';
	if ( QUERY.has( 'embed' ) ) document.body.classList.add( 'embed', 'hide-ui' );

	const adapter = await navigator.gpu.requestAdapter( { powerPreference: 'high-performance' } );
	if ( ! adapter ) throw new Error( 'no WebGPU adapter' );
	const device = await adapter.requestDevice( { requiredFeatures: adapter.features.has( 'timestamp-query' ) ? [ 'timestamp-query' ] : [] } );
	const info = adapter.info || {};
	results.adapter = `${ info.vendor } / ${ info.architecture } / ${ info.description || info.device }`;
	log( 'Adapter:', results.adapter, '| timestamp-query:', device.features.has( 'timestamp-query' ) );

	const name = TEST ? 'dragon' : QUERY.get( 'model' ) in MODELS ? QUERY.get( 'model' ) : 'dragon';
	const { scene, view } = await loadModel( name );
	if ( TEST ) {
		const R = await setupUnbiased( device, scene );
		results.test = await testUnbiased( device, R, camera( view ), log, + QUERY.get( 'frames' ) || 1024 );
		results.status = 'done';
		log( '\nDone.' );
		return;
	}
	await liveUnbiased( device, scene, view, results, scene.geo.index.count / 3, scene.bvh, loadModel );

}

// A scan stood upright on z, scaled to SIZE, centred on a 6 m floor, with its BVH and a camera framing it.
async function loadModel( name ) {

	const model = MODELS[ name ] ?? MODELS.dragon;
	const t0 = performance.now();
	const geo = await new PLYLoader().loadAsync( model.url );
	const p = geo.attributes.position.array;
	if ( ! model.zUp ) {
		for ( let i = 0; i < p.length; i += 3 ) {
			const y = p[ i + 1 ];
			p[ i + 1 ] = - p[ i + 2 ];
			p[ i + 2 ] = y;
		}
	}
	const box = [ Infinity, Infinity, Infinity, - Infinity, - Infinity, - Infinity ];
	for ( let i = 0; i < p.length; i += 3 ) {
		for ( let k = 0; k < 3; k ++ ) {
			box[ k ] = Math.min( box[ k ], p[ i + k ] );
			box[ k + 3 ] = Math.max( box[ k + 3 ], p[ i + k ] );
		}
	}
	const s = SIZE / Math.max( box[ 3 ] - box[ 0 ], box[ 4 ] - box[ 1 ], box[ 5 ] - box[ 2 ] );
	const off = [ - ( box[ 0 ] + box[ 3 ] ) / 2, - ( box[ 1 ] + box[ 4 ] ) / 2, - box[ 2 ] ];
	for ( let i = 0; i < p.length; i += 3 ) for ( let k = 0; k < 3; k ++ ) p[ i + k ] = ( p[ i + k ] + off[ k ] ) * s;
	const height = ( box[ 5 ] - box[ 2 ] ) * s;
	geo.attributes.position.needsUpdate = true;
	geo.computeVertexNormals();
	// model size, before the floor joins the geometry (the material's triplanar scale follows it)
	geo.computeBoundingSphere();
	const radius = geo.boundingSphere.radius;
	addFloor( geo, 3 );
	const triangles = geo.index.count / 3;
	log( `${ name }: ${ geo.attributes.position.count } vertices, ${ triangles } triangles (${ ( performance.now() - t0 ).toFixed( 0 ) } ms)` );

	const t1 = performance.now();
	const bvh = new MeshBVH( geo, { strategy: SAH, maxLeafSize: 4, maxDepth: 48 } );
	const root = bvh._roots[ 0 ];
	Object.assign( results.scene, { name, triangles, bvhNodes: root.byteLength / 32, bvhBuildCpuMs: performance.now() - t1 } );
	log( `SAH BVH: ${ root.byteLength / 32 } nodes, built in ${ ( ( performance.now() - t1 ) / 1000 ).toFixed( 1 ) } s` );

	// camera in front, aimed at mid-height, far enough for the whole height (the dragon keeps 35 cm)
	const dist = Math.max( 0.35, height / 2 / Math.tan( FOV * Math.PI / 360 ) * 1.3 );
	const view = [ [ 0, - dist, height * 0.55 ], [ 0, 0, height * 0.5 ], FOV ];
	return { scene: { geo, root, bvh, radius }, view };

}

// studio floor at z = 0 (the model sits on it after centering), 2 triangles
function addFloor( geo, half ) {

	const pos = geo.attributes.position.array, nor = geo.attributes.normal.array, idx = geo.index.array;
	const nv = pos.length / 3;
	const p = new Float32Array( pos.length + 12 ), n = new Float32Array( nor.length + 12 );
	p.set( pos );
	n.set( nor );
	p.set( [ - half, - half, 0, half, - half, 0, half, half, 0, - half, half, 0 ], pos.length );
	n.set( [ 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1 ], nor.length );
	const i = new Uint32Array( idx.length + 6 );
	i.set( idx );
	i.set( [ nv, nv + 1, nv + 2, nv, nv + 2, nv + 3 ], idx.length );
	geo.setAttribute( 'position', new THREE.BufferAttribute( p, 3 ) );
	geo.setAttribute( 'normal', new THREE.BufferAttribute( n, 3 ) );
	geo.setIndex( new THREE.BufferAttribute( i, 1 ) );

}

// the test's fixed camera
function camera( [ cp, ct, fov ] ) {

	const cam = new THREE.PerspectiveCamera( fov, W / H, 0.01, 100 );
	cam.up.set( 0, 0, 1 );
	cam.position.set( ...cp );
	cam.lookAt( new THREE.Vector3( ...ct ) );
	cam.updateMatrixWorld();
	return cam;

}
