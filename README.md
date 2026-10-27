# Copper flight on Admiral

A native edge-autonomy demonstration with a browser mission monitor. Copper runs the simulated flight and learned ViTFly policy on the edge device; the browser visualizes observed native telemetry. No physical drone is controlled.

- **Native execution:** Bevy physics and simulated stereo/depth, Copper control/compute graphs, CPU or CUDA learned inference, and an explicit recording policy.
- **Browser presentation:** live observed poses, completed-mission visualization, and locally packaged scene assets. Browser animation is not native compute throughput.
- **Operational workflow:** immutable workload images, persistent run data, bounded retention, observed-backend acceptance and authenticated EdgeWire access. Fleet-wide capacity and throughput are **UNVERIFIED**.

## Start here

1. [Customer guide](docs/CUSTOMER_GUIDE.md): execution boundaries, Live versus Recorded, build prerequisites and off-network access.
2. [Acceptance checklist](docs/ACCEPTANCE.md): evidence required for the exact delivered revision/image, performance measurement and known limits.
3. [Native telemetry contract](native-contract.md): units, clocks, recording modes and evidence semantics.
4. [Third-party notices](THIRD_PARTY_NOTICES.md): source provenance and unresolved asset/model distribution permissions.

**Release status:** a private development candidate now has verified Jetson CUDA/NVIDIA execution, depth/UI checks and a 90-second measurement. It achieved **0.9193× real time and 58.84 genuine source samples/s**, so the strict ≥1.0× realtime release gate remains **FAILED**. See [tested candidate identity and evidence](CUSTOMER_RELEASE.md); it is not a passed final release. Native flight replay/recomputation is **NOT IMPLEMENTED**; recorded browser playback must not be presented as replay verification.

## Tests without GPU or proprietary model assets

Python 3.12+, Node 24, Git and the pinned upstream checkout are needed. No Python/Node packages are required for these tests.

```sh
python3 scripts/native_sources.py prepare --source upstream
python3 - <<'PY'
import pathlib, unittest
suite = unittest.TestSuite()
loader = unittest.TestLoader()
# These two modules require local Docker/native artifacts even for helper tests.
excluded = {'test_native_performance.py', 'test_native_observability.py'}
for path in sorted(pathlib.Path('tests').glob('test_*.py')):
    if path.name not in excluded:
        suite.addTests(loader.discover('tests', pattern=path.name))
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
PY
npm test --prefix www
```

CI executes these existing suites, without credentials, deployment or image publication. Platform/image/Rust opt-in skips are not native acceptance. See [acceptance](docs/ACCEPTANCE.md) before enabling native tests.

## Sharing boundary

This repository does not grant a new open-source license for Admiral integration code, model weights, scene assets, branding, fonts or vendor binaries. Preserve applicable upstream notices and obtain the distribution owner's approval before sharing assets or images. Keep `artifacts/`, `vendor-assets/`, recordings, credentials and local upstream/build caches out of customer source exports. The explicitly attributed, software-rendered parser fixture in `tests/fixtures/` is an exception: it is unchanged test input, not customer or Jetson performance evidence. The internal deployment helper is not a customer provisioning interface; use the parameterized guide instead.
