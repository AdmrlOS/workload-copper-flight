import * as THREE from './vendor/three-r182/build/three.module.js';
import { GLTFLoader } from './vendor/three-r182/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from './vendor/three-r182/examples/jsm/controls/OrbitControls.js';
import { ingestSample, samplePose, sourceConnection, chaseView } from './pose.js';

// Rendering only: no physics, policy, extrapolation, rotor animation or controls.
export async function createViewer(getSnapshot) {
  const host = document.getElementById('scene-canvas');
  const overlay = document.getElementById('scene-overlay');
  const overlayTitle = document.getElementById('scene-overlay-title');
  const overlayDetail = document.getElementById('scene-overlay-detail');
  const sourceLabel = document.getElementById('scene-source');
  const sampleLabel = document.getElementById('scene-sample');
  const focusButton = document.getElementById('frame-vehicle');
  const chaseButton = document.getElementById('chase-camera');
  const resetButton = document.getElementById('reset-scene');
  let chasing = true;
  const setChasing = (value) => {
    chasing = value;
    chaseButton.setAttribute('aria-pressed', String(value));
    document.getElementById('scene-camera').textContent = value ? 'Chase pose' : 'Orbit view';
  };
  const announce = (title, detail) => {
    overlay.hidden = false;
    overlayTitle.textContent = title;
    overlayDetail.textContent = detail;
  };
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  } catch {
    announce('WebGL2 unavailable', 'Telemetry still works. This browser could not create a WebGL2 context.');
    sourceLabel.textContent = 'Browser renderer unavailable';
    return { dispose() {} };
  }
  const canvas = renderer.domElement;
  canvas.setAttribute('aria-label', 'Forest scene rendered in browser WebGL2; native pose only when connected');
  canvas.setAttribute('tabindex', '0');
  canvas.setAttribute('role', 'img');
  host.prepend(canvas);
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#c6ccbd');
  scene.fog = new THREE.Fog('#c6ccbd', 95, 260);
  const camera = new THREE.PerspectiveCamera(52, 1, 0.02, 800);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = false;
  controls.maxPolarAngle = Math.PI * 0.49;
  controls.minDistance = 0.4;
  controls.maxDistance = 180;
  const resetCamera = () => {
    camera.position.set(-24, 21, 32);
    controls.target.set(0, 1, 0);
    controls.update();
  };
  resetCamera();
  resetButton.addEventListener('click', () => { setChasing(false); resetCamera(); });
  controls.addEventListener('start', () => setChasing(false));
  scene.add(new THREE.HemisphereLight('#ecf2eb', '#5a6750', 2.2));
  const sun = new THREE.DirectionalLight('#fff4d9', 3);
  sun.position.set(-30, 60, 30);
  scene.add(sun);
  const vehicle = new THREE.Group();
  vehicle.visible = false;
  scene.add(vehicle);
  const traceGeometry = new THREE.BufferGeometry();
  const tracePoints = new Float32Array(256 * 3);
  traceGeometry.setAttribute('position', new THREE.BufferAttribute(tracePoints, 3));
  traceGeometry.setDrawRange(0, 0);
  const trace = new THREE.Line(traceGeometry, new THREE.LineBasicMaterial({ color: '#2152ee', transparent: true, opacity: 0.9, depthTest: false }));
  trace.renderOrder = 2;
  trace.frustumCulled = false;
  scene.add(trace);
  let forest = null;
  let assetsReady = false;
  let assetError = null;
  let contextLost = false;
  let history = null;
  let renderedKey = null;

  let disposed = false;
  let animationFrame;
  const resize = new ResizeObserver(() => {
    const { width, height } = host.getBoundingClientRect();
    renderer.setSize(Math.max(1, width), Math.max(1, height), false);
    camera.aspect = Math.max(1, width) / Math.max(1, height);
    camera.updateProjectionMatrix();
  });
  resize.observe(host);
  canvas.addEventListener('webglcontextlost', (event) => { event.preventDefault(); contextLost = true; });
  canvas.addEventListener('webglcontextrestored', () => { contextLost = false; });
  const focusVehicle = () => {
    if (!vehicle.visible) return;
    controls.target.copy(vehicle.position);
    camera.position.copy(vehicle.position).add(new THREE.Vector3(0.75, 0.55, 1.1));
    controls.update();
  };
  const followVehicle = () => {
    const view = chaseView({ position: vehicle.position });
    camera.position.set(view.position.x, view.position.y, view.position.z);
    controls.target.set(view.target.x, view.target.y, view.target.z);
    controls.update();
  };
  focusButton.addEventListener('click', () => { setChasing(false); focusVehicle(); });
  chaseButton.addEventListener('click', () => { setChasing(!chasing); if (chasing && vehicle.visible) followVehicle(); });

  const loader = new GLTFLoader();
  // GLBs are served by the backend's two explicit asset routes, never a CDN.
  Promise.all([
    loader.loadAsync('/api/scene/forest.glb'),
    loader.loadAsync('/api/scene/quadcopter.glb'),
  ]).then(([environment, quadcopter]) => {
    if (disposed) return;
    forest = environment.scene;
    // Pinned Bevy forest world root: translation ZERO, scale 1, identity rotation.
    // Preserve every transform contained in the GLB itself. Both renderers are Y-up.
    scene.add(forest);
    vehicle.add(quadcopter.scene);
    assetsReady = true;
    host.dataset.assets = 'loaded';
    document.getElementById('scene-assets').textContent = 'forest.glb + quadcopter.glb';
  }).catch((failure) => {
    assetError = 'Scene asset request or GLB decoding failed. Check the two /api/scene/ routes.';
    host.dataset.assets = 'failed';
    console.error('Copper scene asset loading failed:', failure);
  });

  function draw(nowMs) {
    if (disposed) return;
    const snapshot = getSnapshot();
    const connection = sourceConnection(snapshot);
    const updated = ingestSample(history, snapshot);
    if (updated !== history) {
      history = updated;
      for (let index = 0; index < history.trace.length; index += 1) {
        const point = history.trace[index];
        tracePoints.set([point.x, point.y, point.z], index * 3);
      }
      traceGeometry.attributes.position.needsUpdate = true;
      traceGeometry.setDrawRange(0, history.trace.length);
    }
    if (forest) forest.visible = !snapshot.state?.frame?.world || snapshot.state.frame.world === 'forest';
    if (renderedKey !== null && history && renderedKey !== history.key) vehicle.visible = false;
    if (assetsReady && connection.live && history && !contextLost) {
      const sample = samplePose(history, nowMs - 200);
      if (sample) {
        const { position, rotation } = sample.pose;
        vehicle.position.set(position.x, position.y, position.z);
        vehicle.quaternion.set(rotation.x, rotation.y, rotation.z, rotation.w);
        vehicle.visible = true;
        renderedKey = history.key;
        if (chasing) followVehicle();
        sampleLabel.textContent = sample.interpolated ? 'Interpolated between observed samples' : 'Holding latest observed endpoint';
      }
      overlay.hidden = true;
      sourceLabel.textContent = 'Native pose connected';
      host.dataset.source = 'connected';
    } else {
      host.dataset.source = 'paused';
      sourceLabel.textContent = connection.reason;
      sampleLabel.textContent = vehicle.visible ? 'Last displayed pose · frozen' : 'No vehicle pose displayed';
      if (contextLost) announce('WebGL context lost', 'Pose visualization is paused. Telemetry remains available below.');
      else if (assetError) announce('Scene unavailable', assetError);
      else if (!assetsReady) announce('Loading local scene assets', 'Fetching the forest and quadcopter GLBs from this workload.');
      else announce(vehicle.visible ? 'Native source paused' : 'Waiting for native pose', `${connection.reason}. Static scene only until fresh native position and quaternion are available.`);
    }
    focusButton.disabled = !vehicle.visible;
    chaseButton.disabled = !vehicle.visible;
    document.getElementById('scene-trace').textContent = `${history?.trace.length ?? 0} / 256 observed points`;
    if (!contextLost) renderer.render(scene, camera);
    animationFrame = requestAnimationFrame(draw);
  }
  animationFrame = requestAnimationFrame(draw);
  return {
    dispose() {
      disposed = true;
      cancelAnimationFrame(animationFrame);
      resize.disconnect();
      controls.dispose();
      scene.traverse((object) => {
        object.geometry?.dispose();
        for (const material of Array.isArray(object.material) ? object.material : [object.material]) material?.dispose();
      });
      renderer.dispose();
    },
  };
}
