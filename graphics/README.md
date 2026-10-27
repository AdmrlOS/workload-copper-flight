# Isolated headless Vulkan payload and depth probe

## Verified outcome and current packaging blocker

The release probe was built and executed as **Linux ARM64**, using the cached
native toolchain and a separate `copper-flight-graphics-target` volume. No native
application target was shared or modified. `verification.json` records actual
commands' results and immutable local image/executable identities.

The explicit `--software-verification` invocation selected Mesa llvmpipe
(`vendor=0x10005`, `device_type=Cpu`, Vulkan), rasterized the triangle into a
64×64 Depth32Float attachment, and mapped 16,384 bytes: center `(32,32)=0.25`,
background `(4,4)=1.0`. This is **software-not-Jetson-proof**. Default invocation
forced NVIDIA and failed locally with `surface-free adapter request: No suitable
graphics adapter found ... vulkan drivers/libraries could not be loaded`.
No Jetson graphics process was run, and neither result establishes Bevy's actual
camera or native CUDA-policy acceptance.

**Completed locally:** following renewed user approval, the real two NVIDIA
archives were checksum-verified and assembled without installation. The lock now
contains 18 paths: seven missing matching libraries, the ICD JSON and its packaged
link, and nine documentation/license files. Every staged byte and link was checked
against the lock, and all 25 injected basenames remain excluded. Evidence is in
`artifacts/graphics-payload/verification.json`; target GPU execution remains a
separate acceptance gate. This does not establish legal clearance for unrestricted
redistribution; the original vendor notices are retained in `licenses/` and rootfs.

All six cached archives under
`/Users/aturner/.hermes/cache/scratch/jetson-graphics-research` were independently
rehashed in this task and matched the recorded NVIDIA HTTPS-index hashes:

| archive | SHA-256 |
|---|---|
| nvidia-l4t-3d-core.deb | `77fcb6c2c11ed67403f8e7697aab9d6ef11a2acbde86dd38a062a8945d5d8631` |
| nvidia-l4t-core.deb | `277a6fb25f2c06cc2dee6d352bef3abb15929739f396fea1cee70d1dea83008b` |
| nvidia-l4t-libvulkan.deb | `5a5f99a93d413f0bad14498729381311f904025fe077dc4b40f0698fa03286c3` |
| nvidia-l4t-gbm.deb | `e84d118dcdab013b783f34416865c981a27fa669e91d054067e54ef3f724c6d1` |
| nvidia-l4t-wayland.deb | `980cb672d5aa6a0fe1b817ba23bc1646344d8233f6cfb6cdb1923c0c3fcd8b20` |
| nvidia-l4t-weston.deb | `e755b030e728aa2253534c33873bd94226d60eec4bdba3deb6185228ce52c8ff` |

These are package hashes, not independently verified repository signatures. The
research report, package index, minimal candidate, live manifest, ELF inventory
and package copyright material were read locally; no repository package scripts
were executed. Only core + 3d-core are needed by the initial candidate; select a
single distro `libvulkan1` loader, not the NVIDIA generic loader as well.

## Assembler contract

`assemble.py --lock LOCK --archives DIR --destination NEW_ROOTFS` is a Linux
builder operation. It:

* verifies entire archive SHA-256/size before reading package metadata;
* verifies exact package name/version/architecture using `dpkg-deb --field`;
* obtains data only with `dpkg-deb --fsys-tarfile`, never `dpkg -i`, apt, or
  maintainer-script execution;
* parses tar members itself and selects exact locked paths with size/checksum
  validation, rather than using tar extraction;
* rejects noncanonical paths, duplicate tar members, unsupported selected types,
  duplicate lock paths, existing output roots, symlink ancestors and injected
  library basenames in any output directory;
* validates each selected symlink against its exact packaged target and requires
  that target to be an allowlisted regular file. The absolute ICD link is
  image-root-relative and is preserved without dereferencing the host path;
* creates selected symlinks only after regular files, then publishes the new
  staging directory. It never merges with an existing rootfs.

The lock must list `packages` with `name`, basename `archive`, `version`,
`architecture`, `bytes`, `sha256` (plus source URL/provenance), `files` with
`package`, canonical relative `path`, `type=file`, `bytes`, `sha256`, or
`type=symlink`, exact `target`, and `injected_library_exclusions` containing
**every** live manifest library key. Preserve all pertinent package copyright,
Tegra Software License Agreement, `LICENSE.libnvidia-rmapi-tegra`, and graphics
third-party license/notice files under `/usr/share/doc/<package>/` in the rootfs.
The distribution owner must review the actual licenses; a research hash is not
license approval.

## Native engineer integration fragment (not applied)

The pinned NVIDIA graphics payload must match the observed live profile
`tegra234-nvgpu-r39.2.1-v1`, L4T `39.2.1`, package
`39.2.1-20260806224157`, driver `595.78`. Refuse a mismatch rather than silently
loading a different version. After completing the pinned lock, use a named
read-only `graphics-debs` context pointing at the existing cached archives:

```dockerfile
FROM native-toolchain AS headless-graphics-payload
COPY graphics/assemble.py graphics/payload.lock.json /graphics/
COPY --from=graphics-debs /nvidia-l4t-3d-core.deb /debs/nvidia-l4t-3d-core.deb
COPY --from=graphics-debs /nvidia-l4t-core.deb /debs/nvidia-l4t-core.deb
RUN python3 /graphics/assemble.py --archives /debs --destination /graphics-rootfs

FROM native-toolchain AS headless-depth-probe
COPY graphics/probe/ /graphics-probe/
WORKDIR /graphics-probe
RUN --mount=type=cache,id=copper-flight-registry,target=/usr/local/cargo/registry \
    cargo build --release --locked --target-dir /graphics-probe-target

# In native-runtime-base (ordinary distro userspace only):
# apt-get install --no-install-recommends libvulkan1 libx11-6 libxext6
COPY --from=headless-graphics-payload /graphics-rootfs/ /
COPY --from=headless-depth-probe /graphics-probe-target/release/copper-vulkan-depth-probe /usr/local/bin/copper-vulkan-depth-probe
RUN printf '%s\n' /usr/lib/aarch64-linux-gnu/nvidia > /etc/ld.so.conf.d/copper-headless-vulkan.conf \
    && ldconfig
ENV VK_DRIVER_FILES=/etc/vulkan/icd.d/nvidia_icd.json \
    VK_ICD_FILENAMES=/etc/vulkan/icd.d/nvidia_icd.json
```

Do not replace or demote the runtime's injected-library precedence. Keep the
observed `/run/admiral/nvidia/lib` first in the effective `LD_LIBRARY_PATH`, then
the image-owned graphics directory and existing application/CUDA paths. Do not
copy **any** injected basename into the image's graphics directory, even if it
has matching bytes. Verify the final rootfs with its own ARM64 loader/`ldd`;
image-only `ldd` may correctly report injected NVGPU companions missing until
Admiral supplies them. Do not “repair” that by adding duplicates.

No EGL, GBM, compositor, KMS surface, X server, module, firmware, host package,
or container toolkit is needed by this independent probe. A display-controller
failure is not evidence that this surface-free NVGPU test fails.

## Probe contract and reproduction

`probe/Cargo.toml` pins wgpu `29.0.4` and serde_json `1.0.154`; `probe/Cargo.lock`
contains actual resolved registry checksums. The API was checked against the
cached exact-version upstream crate sources, and compiled against those crates.
The probe restricts the instance to Vulkan, creates no display handle or surface,
requests `compatible_surface=None`, `force_fallback_adapter=false`, and rejects
non-NVIDIA or CPU adapters by default. The explicit software flag requires a
CPU Vulkan adapter and replaces **both** ICD environment variables consistently
with `/usr/share/vulkan/icd.d/lvp_icd.json` (the local verification image's Mesa
ICD). Thus an image-wide forced NVIDIA setting cannot accidentally defeat the
software test or produce an NVIDIA hardware-success label.

The vertex shader provides three vertices at NDC depth 0.25. A real draw call
rasterizes a triangle into a Depth32Float texture cleared to 1.0, then copies its
DepthOnly aspect into a MAP_READ buffer with 256-byte rows. CPU validation uses
actual mapped center/background bytes and finite-value/tolerance checks; it
cannot pass on enumeration or a buffer copy alone. Polling is limited to 10s,
the callback wait to 1s, and a whole-process watchdog exits 124 at 25s. Use an
outer 30s process/container deadline as an additional operator-side bound.

From the project root, local build/tests (no network needed):

```sh
docker run --rm --platform linux/arm64 \
  -v "$PWD/graphics/probe":/probe \
  -v copper-flight-native-registry:/usr/local/cargo/registry:ro \
  -v copper-flight-graphics-target:/target \
  -e CARGO_TARGET_DIR=/target -e CARGO_BUILD_JOBS=3 -w /probe \
  --entrypoint cargo workload-copper-flight:toolchain test --offline --locked
# Same mounts, replace test with: build --release --offline --locked
```

Release artifact:
`/Users/aturner/.hermes/cache/scratch/copper-flight-graphics-proof/copper-vulkan-depth-probe`
(SHA-256 `6e7189182cba629910e259936de27c23828e09fbd81dd3e1ffceadfc51b93c0d`).

The local-only image was built with the Docker Desktop **docker** driver
(`--builder desktop-linux`), because the selected `tos` docker-container builder
cannot resolve the daemon-local runtime base and attempted an unauthorized
registry lookup. Nothing was published. Rebuild the standalone local artifact:

```sh
docker buildx build --builder desktop-linux --load --platform linux/arm64 \
  --build-context probe-binary=/Users/aturner/.hermes/cache/scratch/copper-flight-graphics-proof \
  -f graphics/Probe.Dockerfile -t workload-copper-flight:graphics-probe-local .

docker run --rm --network none --platform linux/arm64 \
  workload-copper-flight:graphics-probe-local --software-verification
# Expected locally: exit 0, proof=software-not-Jetson-proof, depths=.25/1.
docker run --rm --network none --platform linux/arm64 \
  workload-copper-flight:graphics-probe-local
# Expected locally: exit 1, proof=NVIDIA-hardware-required, no rasterization.

docker run --rm --network none --platform linux/arm64 \
  -v "$PWD":/project:ro -w /project \
  -e GRAPHICS_PROBE_BIN=/usr/local/bin/copper-vulkan-depth-probe \
  --entrypoint python3 workload-copper-flight:graphics-probe-local \
  -m unittest discover -s tests -p test_graphics_payload.py -v
```

Eight Python graphics tests passed in that exact local image, including genuine
fixture-deb extraction (postinst marker remained absent), actual Mesa raster
readback, and NVIDIA-only failure. Three Rust unit tests passed. The project-wide
host suite ran 66 tests, passing with six expected opt-in/platform skips.
No tracked files were staged or committed.

## Remaining device gate

Only the parent may integrate/publish/deploy or touch registry/config/fleet/device
state. Complete the payload-lock/license blocker and verify real staging first;
then the parent must check the **current** injected manifest identity and exclusion
set, preserve injection precedence, run the default probe with a real outer
timeout, and record NVIDIA `0x10de`, non-CPU Vulkan adapter, real depth assertions,
exit code and relevant kernel errors. Stop at the platform boundary on RM/NVGPU
failure; no driver/module/firmware repair is authorized. Even a successful probe
is not the native Bevy camera→ViTFly/CUDA→browser acceptance gate.
