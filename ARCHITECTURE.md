# Browser-first Copper × Admiral flight demonstration

## Execution boundary

The primary presentation is an Admiral-branded browser monitor with a WebGL 3D viewer. The browser renders the real forest and quadcopter assets and displays observed native vehicle transforms. It does not simulate a second vehicle, produce policy predictions, or claim to execute CUDA.

The Jetson workload owns the upstream native Copper flight application:

1. Bevy simulates the vehicle and generates the camera/depth observations.
2. Copper schedules the native source, learned ViTFly policy, autonomy and control graph.
3. ViTFly loads the packaged Safetensors model and uses the explicitly selected CPU or CUDA backend. A requested backend is not proof it was actually observed.
4. Native Copper recording writes both controller and compute log families into persistent run directories.
5. A read-only supervisor API exposes observed state and completed downloadable recordings, and serves the offline browser UI and a strict scene-asset whitelist.

The browser uses those observations to position the drone. Interpolation is a display operation between observed poses, not a second control loop; stale data freezes the view and is labeled. Camera navigation changes only the viewer, not the native flight mission.

## Important graphics distinction

A browser viewer removes the requirement for a connected Jetson display. It does **not** remove the native simulator's graphics requirement: the Jetson still needs a working graphics path to produce the simulated depth used by the learned policy. Headless native Vulkan/EGL and CUDA inference require independent device acceptance. Successful browser WebGL rendering does not establish either.

The supported architecture being integrated is native simulation plus browser visualization. A full client-side WASM simulator is a different execution mode. The upstream BevyMon browser preview selects a placeholder policy graph and must not be presented as evidence of Jetson-side learned autonomy.

## Evidence, not labels

The runtime reports the actually observed renderer adapter/backend and loaded policy device. A compiled feature, requested environment variable, moving browser model, or node called `vitfly` is insufficient evidence.

`policy_observation_seq` is the upstream prediction-preview publication sequence. Raw and conditioned policy outputs can both advance it, so it is deliberately **not** called an inference count. An unknown exact inference count stays null. Acceptance requires new native simulation observations and new learned-policy observations in the same episode, with finite policy output, AUTO engaged, and the expected loaded backend.

Native binary recordings are not themselves verified replay. This flight workload must not claim algorithm recomputation or bitwise replay verification based on archive downloads or browser scrubbing. The separate rover workload retains its independently tested native replay demonstration.

## Offline and isolation

Source is pinned to Copper commit `d46ef87a65c7ba93bcad3c236da99e52cd77f319`, with a committed dependency lockfile and checksum-locked public model/scene inputs. UI fonts, logos and rendering libraries are packaged locally. The runtime must not depend on CDN access during a demonstration.

The flight project and image are separate from `workload-copper`. Mutable flight runs live under `/data/copper-flight`; replacing an image must preserve that persistence destination. The production API is read-only and does not actuate a physical drone.

## Deployment scope

The user explicitly approved a temporary canary on the Jetson currently in `orin-cuda-debug`, with its previous Configuration saved for rollback. Configuration creation, publication and fleet selection remain separate operations. Before any approved selection change, refresh the fleet, confirm that its membership is still exactly the approved Jetson, preserve its latest Configuration selection and use optimistic concurrency. Verify each external write by reading back the exact target.

No device success is implied by this architecture document. Image execution, offline behavior, native graphics, actual CUDA policy execution, closed-loop progress, browser visualization and persistence each need recorded acceptance results.
