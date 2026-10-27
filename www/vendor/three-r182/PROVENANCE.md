# Vendored Three.js

Pinned release: **r182 / 0.182.0**. Source repository: `https://github.com/mrdoob/three.js`, tag `r182`.

Files were downloaded directly from the corresponding paths under `https://raw.githubusercontent.com/mrdoob/three.js/r182/`:

- `build/three.module.js`
- `build/three.core.js`
- `examples/jsm/loaders/GLTFLoader.js`
- `examples/jsm/controls/OrbitControls.js`
- `examples/jsm/utils/BufferGeometryUtils.js`
- `LICENSE` (MIT, preserved verbatim)

Local modification: each add-on's bare `from 'three'` import is replaced with `from '../../../build/three.module.js'`. No inline import map, CDN, package resolution, bundler, or relaxed script CSP is required. All other vendor source is unchanged.

The production scene requests only `/api/scene/forest.glb` and `/api/scene/quadcopter.glb`. The API owns these assets; they are not copied or synthesized by the UI. Native physics, policy inference, and the native renderer are not implemented here.
