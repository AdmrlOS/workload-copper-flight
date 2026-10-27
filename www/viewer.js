import * as THREE from './vendor/three-r182/build/three.module.js';
import { GLTFLoader } from './vendor/three-r182/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from './vendor/three-r182/examples/jsm/controls/OrbitControls.js';
import { chaseView } from './pose.js';

// Presentation only: no physics, policy, extrapolation or invented rotor motion.
export async function createViewer(getPresentation) {
  const node = id => document.getElementById(id);
  const host = node('scene-canvas'); const overlay = node('scene-overlay');
  const focusButton = node('frame-vehicle'); const chaseButton = node('chase-camera');
  const cue = node('vehicle-cue');
  let chasing = true; let disposed = false; let animationFrame;
  const setChasing = value => { chasing = value; chaseButton.setAttribute('aria-pressed', String(value)); node('scene-camera').textContent = value ? 'Follow pose' : 'Orbit view'; };
  const announce = (title, detail) => { overlay.hidden = false; node('scene-overlay-title').textContent = title; node('scene-overlay-detail').textContent = detail; };
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' }); }
  catch { announce('WebGL2 unavailable', 'The Copper data inspector still works. No browser 3D scene can be rendered in this context.'); return { dispose() {} }; }
  const canvas = renderer.domElement;
  canvas.setAttribute('aria-label', 'Forest visualization using genuine native pose samples. Not a video feed.');
  canvas.setAttribute('tabindex', '0'); canvas.setAttribute('role', 'img'); host.prepend(canvas);
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5));
  renderer.outputColorSpace = THREE.SRGBColorSpace; renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1;
  const scene = new THREE.Scene(); scene.background = new THREE.Color('#c6ccbd'); scene.fog = new THREE.Fog('#c6ccbd', 110, 300);
  const camera = new THREE.PerspectiveCamera(52, 1, .02, 900);
  const controls = new OrbitControls(camera, canvas); controls.enableDamping = false; controls.maxPolarAngle = Math.PI * .49; controls.minDistance = .2; controls.maxDistance = 650;
  const overview = () => { camera.position.set(95, 180, -80); controls.target.set(0, 0, -215); controls.update(); };
  overview();
  node('reset-scene').addEventListener('click', () => { setChasing(false); overview(); });
  controls.addEventListener('start', () => setChasing(false));
  scene.add(new THREE.HemisphereLight('#ecf2eb', '#5a6750', 2.2));
  const sun = new THREE.DirectionalLight('#fff4d9', 3); sun.position.set(-30, 60, 30); scene.add(sun);
  const vehicle = new THREE.Group(); vehicle.visible = false; scene.add(vehicle);
  const traceGeometry = new THREE.BufferGeometry(); const tracePoints = new Float32Array(600 * 3);
  traceGeometry.setAttribute('position', new THREE.BufferAttribute(tracePoints, 3)); traceGeometry.setDrawRange(0, 0);
  const trace = new THREE.Line(traceGeometry, new THREE.LineBasicMaterial({ color: '#2152ee', depthTest: false, transparent: true, opacity: .85 }));
  trace.frustumCulled = false; trace.renderOrder = 2; scene.add(trace);
  let forest; let assetsReady = false; let assetError = null; let contextLost = false;
  let renderedKey = null; let traceKey = null; let hasPlaced = false;
  const resize = new ResizeObserver(() => { const { width, height } = host.getBoundingClientRect(); renderer.setSize(Math.max(1, width), Math.max(1, height), false); camera.aspect = Math.max(1, width) / Math.max(1, height); camera.updateProjectionMatrix(); });
  resize.observe(host);
  canvas.addEventListener('webglcontextlost', event => { event.preventDefault(); contextLost = true; });
  canvas.addEventListener('webglcontextrestored', () => { contextLost = false; });
  const followVehicle = () => { const view = chaseView({ position: vehicle.position }); camera.position.set(view.position.x, view.position.y, view.position.z); controls.target.set(view.target.x, view.target.y, view.target.z); controls.update(); };
  focusButton.addEventListener('click', () => { if (vehicle.visible) { setChasing(false); followVehicle(); } });
  chaseButton.addEventListener('click', () => { setChasing(!chasing); if (chasing && vehicle.visible) followVehicle(); });
  const loader = new GLTFLoader();
  Promise.all([loader.loadAsync('/api/scene/forest.glb'), loader.loadAsync('/api/scene/quadcopter.glb')]).then(([environment, quadcopter]) => {
    if (disposed) return;
    // Identity forest root; preserve every source transform. Aircraft is 0.1185 m wide.
    forest = environment.scene; scene.add(forest); vehicle.add(quadcopter.scene);
    assetsReady = true; host.dataset.assets = 'loaded'; node('scene-assets').textContent = 'Source GLBs · true scale';
  }).catch(failure => { assetError = 'Could not load the two local /api/scene/ GLBs.'; host.dataset.assets = 'failed'; console.error('Copper scene asset loading failed:', failure); });
  const projected = new THREE.Vector3();
  function draw(now) {
    if (disposed) return;
    const view = getPresentation(now);
    const key = JSON.stringify([view.mode, view.key]);
    if (key !== renderedKey) { vehicle.visible = false; hasPlaced = false; traceKey = null; renderedKey = key; }
    const worldMatches = view.frame?.world === 'forest';
    if (forest) forest.visible = !view.frame?.world || worldMatches;
    const permitted = worldMatches && view.pose && (view.mode === 'recorded' || view.live);
    if (assetsReady && permitted && !contextLost) {
      const { position, rotation } = view.pose;
      vehicle.position.set(position.x, position.y, position.z);
      vehicle.quaternion.set(rotation.x, rotation.y, rotation.z, rotation.w);
      vehicle.visible = true; hasPlaced = true;
      if (chasing) followVehicle();
      overlay.hidden = true;
      host.dataset.source = view.mode === 'recorded' ? 'recorded' : 'connected';
      node('scene-sample').textContent = view.interpolated ? `Interpolated pose · source seq ${view.bracket[0]}→${view.bracket[1]}` : `Observed endpoint · seq ${view.frame.seq}`;
      node('scene-source').textContent = view.mode === 'recorded' ? 'Recorded native mission visualization' : 'Live native observations · buffered';
    } else {
      host.dataset.source = 'paused';
      node('scene-source').textContent = view.reason;
      node('scene-sample').textContent = hasPlaced ? 'Last displayed pose · frozen' : 'No vehicle pose displayed';
      if (contextLost) announce('WebGL context lost', 'Flight visualization is paused. Native data remains available in the inspector.');
      else if (assetError) announce('Scene unavailable', assetError);
      else if (!assetsReady) announce('Loading source geometry', 'Reading the local forest and quadcopter GLBs. The browser does not generate or simulate flight.');
      else announce(view.mode === 'recorded' ? view.frame ? 'Recorded pose unavailable' : 'Open a native mission' : hasPlaced ? 'Native source paused' : 'Waiting for native progress', view.mode === 'recorded' ? view.frame ? 'This source frame has no usable position/attitude. Move forward in simulation time; no pose is invented for startup.' : 'Select a completed mission above and open it. Recorded telemetry can be explored in simulation time; no native replay is claimed.' : `${view.reason}. Static scene until fresh source position and attitude are available.`);
    }
    const nextTraceKey = JSON.stringify([key, view.frame?.seq]);
    if (nextTraceKey !== traceKey) {
      traceKey = nextTraceKey;
      const points = worldMatches ? view.frames.filter(f => f.sim_time_s <= view.frame.sim_time_s && f.position_m).slice(-600) : [];
      points.forEach((frame, index) => tracePoints.set([frame.position_m.x, frame.position_m.y, frame.position_m.z], index * 3));
      traceGeometry.attributes.position.needsUpdate = true; traceGeometry.setDrawRange(0, points.length);
      node('scene-trace').textContent = `${points.length} source samples`;
    }
    if (!contextLost) renderer.render(scene, camera);
    if (vehicle.visible && !contextLost) {
      projected.copy(vehicle.position).project(camera);
      const onScreen = projected.z >= -1 && projected.z <= 1 && Math.abs(projected.x) < .95 && Math.abs(projected.y) < .95;
      cue.hidden = !onScreen;
      if (onScreen) { cue.style.left = `${(projected.x * .5 + .5) * host.clientWidth}px`; cue.style.top = `${(-projected.y * .5 + .5) * host.clientHeight}px`; }
    } else cue.hidden = true;
    focusButton.disabled = !vehicle.visible; chaseButton.disabled = !vehicle.visible;
    animationFrame = requestAnimationFrame(draw);
  }
  animationFrame = requestAnimationFrame(draw);
  return { dispose() { disposed = true; cancelAnimationFrame(animationFrame); resize.disconnect(); controls.dispose(); scene.traverse(object => { object.geometry?.dispose(); for (const material of Array.isArray(object.material) ? object.material : [object.material]) material?.dispose(); }); renderer.dispose(); } };
}
