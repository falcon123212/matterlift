// MatterLift Live RT: the material study path traced with WebGPU (unbiased ReSTIR DI over 256 spot
// lights, BVH shadow rays, SVGF denoiser), wearing the material MatterLift sends it (restir.js).
//   live.html                live viewer (inside MatterLift: ?embed; H hides the controls)
//   live.html?model=study    start on a given model (MODELS); MatterLift can switch later
//   live.html?test           bias test against the exact reference (every light, one shadow ray each)
import * as THREE from 'three';
import { PLYLoader } from 'three/examples/jsm/loaders/PLYLoader.js';
import { MeshBVH, SAH } from 'three-mesh-bvh';
import { W, H } from './wgsl.js';
import { liveUnbiased, setupUnbiased, testUnbiased } from './restir.js';

// The models of the WebGL preview: MatterLift's own material study (scripts/material_study.py, MIT;
// public/models/CREDITS.md). zUp: the file stands on z (the renderer's up axis), else on y.
// elevation: the camera's angle above the model (the study is wide and low: 18° shows the plinth's top).
const MODELS = {
	study: { url: 'models/material_study.ply', zUp: true, label: 'the material study', elevation: 18 },
};
// a step that never settles (driver, network) ends in an error with a retry instead of an endless load
const ADAPTER_TIMEOUT = 15000;
const MODEL_TIMEOUT = 60000;
const SIZE = 0.2; // every model scaled to 20 cm along its longest side, so the spot rig fits it
const FOV = 30;

const QUERY = new URLSearchParams( location.search );
const TEST = QUERY.has( 'test' );
const logEl = document.getElementById( 'log' );
const results = window.__results = { status: 'running', scene: {} };
const log = ( ...a ) => { logEl.textContent += a.join( ' ' ) + '\n'; console.log( ...a ); };

main().catch( e => { results.status = 'error'; results.error = String( e?.stack || e ); log( 'ERROR', e?.stack || e ); showError( e ); } );

// friendly message in the loading overlay, with a retry (the raw log stays below for the test page)
function showError( e ) {

	const el = document.getElementById( 'loading' );
	el.classList.add( 'error' );
	el.style.pointerEvents = 'auto';
	document.body.classList.remove( 'live' );
	const text = document.createElement( 'span' );
	text.textContent = navigator.gpu
		? `Something went wrong: ${ e?.message || e }`
		: 'Live RT needs WebGPU. Open it in a recent Chrome or Edge (desktop), or Safari 26.';
	const retry = document.createElement( 'button' );
	retry.textContent = 'Retry';
	retry.style.marginLeft = '12px';
	retry.addEventListener( 'click', () => location.reload() );
	el.replaceChildren( text, ...( navigator.gpu ? [ retry ] : [] ) );

}

function setLoading( text ) {

	document.getElementById( 'loading' ).textContent = text;

}

function withTimeout( promise, ms, what ) {

	let timer;
	const timeout = new Promise( ( _, reject ) => {
		timer = setTimeout( () => reject( new Error( `${ what } did not answer within ${ ms / 1000 } s` ) ), ms );
	} );
	return Promise.race( [ promise, timeout ] ).finally( () => clearTimeout( timer ) );

}

async function main() {

	if ( ! navigator.gpu ) throw new Error( 'WebGPU is not available in this browser' );
	if ( TEST ) document.getElementById( 'loading' ).style.display = 'none';
	// inside MatterLift the render controls show from the start; H hides them
	if ( QUERY.has( 'embed' ) ) document.body.classList.add( 'embed' );

	const name = TEST ? 'study' : QUERY.get( 'model' ) in MODELS ? QUERY.get( 'model' ) : 'study';
	setLoading( `Starting WebGPU for ${ MODELS[ name ].label }…` );
	const adapter = await withTimeout( navigator.gpu.requestAdapter( { powerPreference: 'high-performance' } ), ADAPTER_TIMEOUT, 'The GPU (WebGPU adapter)' );
	if ( ! adapter ) throw new Error( 'no WebGPU adapter' );
	const device = await withTimeout(
		adapter.requestDevice( { requiredFeatures: adapter.features.has( 'timestamp-query' ) ? [ 'timestamp-query' ] : [] } ),
		ADAPTER_TIMEOUT, 'The GPU (WebGPU device)' );
	const info = adapter.info || {};
	results.adapter = `${ info.vendor } / ${ info.architecture } / ${ info.description || info.device }`;
	log( 'Adapter:', results.adapter, '| timestamp-query:', device.features.has( 'timestamp-query' ) );

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

// A model stood upright on z, scaled to SIZE, centred on a 6 m floor, with its BVH and a camera framing it.
async function loadModel( name ) {

	const model = MODELS[ name ] ?? MODELS.study;
	const t0 = performance.now();
	setLoading( `Loading ${ model.label } and building its BVH…` );
	// revalidated fetch (a stale cached 404 must not stick), checked before parsing
	const abort = new AbortController();
	const timer = setTimeout( () => abort.abort(), MODEL_TIMEOUT );
	let data;
	try {
		const r = await fetch( model.url, { cache: 'no-cache', signal: abort.signal } );
		if ( ! r.ok ) throw new Error( `${ model.label }: ${ model.url } answered ${ r.status }` );
		data = await r.arrayBuffer();
	} catch ( e ) {
		throw abort.signal.aborted ? new Error( `${ model.label } did not load within ${ MODEL_TIMEOUT / 1000 } s` ) : e;
	} finally {
		clearTimeout( timer );
	}
	if ( new TextDecoder().decode( data.slice( 0, 3 ) ) !== 'ply' ) {
		throw new Error( `${ model.label } could not be loaded: the server sent something else than the model (${ model.url })` );
	}
	const geo = new PLYLoader().parse( data );
	if ( ! geo.index?.count || ! geo.attributes.position?.count ) throw new Error( `${ model.url } has no triangles` );
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
	// the study ships its normals (its UV seams split vertices; normals from one side would show them);
	// a mesh without them gets them. A uniform scale and shift leave normals as they are. UVs: unused here (triplanar)
	if ( ! geo.attributes.normal ) geo.computeVertexNormals();
	geo.deleteAttribute( 'uv' );
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

	// camera in front, framed on the model's height and width, `elevation` degrees above, aimed low
	const half = Math.tan( FOV * Math.PI / 360 );
	const width = ( box[ 3 ] - box[ 0 ] ) * s;
	const dist = Math.max( height / 2 / half, width / 2 / ( half * 16 / 9 ) ) * 1.2;
	const a = model.elevation * Math.PI / 180;
	const view = [ [ 0, - dist * Math.cos( a ), height * 0.4 + dist * Math.sin( a ) ], [ 0, 0, height * 0.4 ], FOV ];
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
