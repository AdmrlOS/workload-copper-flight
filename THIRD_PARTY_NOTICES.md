# Third-party provenance and sharing boundary

This private evaluation repository does not grant additional licensing rights.

- **Copper:** native flight source comes from `copper-project/copper-rs` at commit `d46ef87a65c7ba93bcad3c236da99e52cd77f319`; its upstream LICENSE is packaged as `COPPER-LICENSE`. Local changes are expressed in `patches/`. Preserve upstream attribution and dependency notices. The Rust code license alone does not establish rights to separately downloaded model weights or scenes.
- **Model and scenes:** `native-assets.lock.json` records exact upstream CDN URLs, sizes and hashes for ViTFly weights, forest/quadcopter geometry and environment textures. These large assets are not committed here. A checksum establishes identity, not redistribution permission. Explicit redistribution terms for the exact CDN artifacts have not been established in this evaluation. Obtain Copper/asset-owner confirmation before giving a populated image or asset bundle to a customer.
- **NVIDIA:** `graphics/payload.lock.json` and `graphics/licenses/` identify the matching Jetson graphics userspace and preserved notices. CUDA runtime notices are included by the image recipe. Distribution is subject to the applicable NVIDIA agreements; do not treat a private image as permission to redistribute vendor components.
- **Browser dependencies:** locally vendored Three.js code retains its upstream license. See `www/vendor/three-r182/`. The browser is presentation code, not a replacement for the native Copper runtime.
- **Admiral branding and fonts:** SVG marks, textures, Archivo and IBM Plex Mono were supplied in the Admiral brand bundle. Preserve the owners' attribution and obtain approval for customer-facing use/distribution. No independent grant for the supplied brand bundle is made here.

Keep operational credentials, native binaries, customer recordings, rollout snapshots and internal artifacts out of source exports. The intended release is private evaluation, not a public/open-source relicensing of all components. Customer GitHub/GHCR/Admiral access must be granted separately by an authorized owner.
