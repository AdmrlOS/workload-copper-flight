# syntax=docker/dockerfile:1
ARG RUST_IMAGE=rust:slim-bookworm@sha256:86234e857a413004348b471d11a4ebe1aa92d2eae2b6b143cac68fd1ac3c48be
ARG NATIVE_RUNTIME=native
ARG UBUNTU_IMAGE=ubuntu:26.04@sha256:e03767b4dc7cb87fc57b1f119d40d9a997ecc5570dc6e22d57d6b7e333bbe78c
FROM ${RUST_IMAGE} AS native-toolchain
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential pkg-config clang lld libudev-dev libwayland-dev libxkbcommon-dev \
    libx11-dev libxcursor-dev libxi-dev libxrandr-dev libasound2-dev libssl-dev \
    ca-certificates curl git python3 patch \
    && rm -rf /var/lib/apt/lists/*
ENV CARGO_INCREMENTAL=0 CARGO_PROFILE_RELEASE_DEBUG=0 CARGO_BUILD_JOBS=3 \
    CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0
WORKDIR /src

# CUDA compiler and link libraries only; driver stubs never enter runtime.
FROM native-toolchain AS native-cuda-toolchain
RUN curl -fsSL https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/arm64/cuda-keyring_1.1-1_all.deb -o /tmp/cuda-keyring.deb \
    && echo '2778cdec0d834b2f895ccef906ff1d33a49acd9a3fe3bf798b67475b9338eff7  /tmp/cuda-keyring.deb' | sha256sum -c - \
    && dpkg -i /tmp/cuda-keyring.deb && rm /tmp/cuda-keyring.deb \
    && apt-get update && apt-get install -y --no-install-recommends \
       cuda-nvcc-12-6=12.6.85-1 cuda-nvvm-12-6=12.6.85-1 cuda-crt-12-6=12.6.85-1 \
       cuda-cudart-12-6=12.6.77-1 cuda-cudart-dev-12-6=12.6.77-1 \
       cuda-driver-dev-12-6=12.6.77-1 cuda-cccl-12-6=12.6.77-1 \
       cuda-nvrtc-dev-12-6 libcublas-dev-12-6 libcurand-dev-12-6 \
    && rm -rf /var/lib/apt/lists/*
ENV CUDA_HOME=/usr/local/cuda-12.6 CUDA_PATH=/usr/local/cuda-12.6 CUDA_COMPUTE_CAP=87 \
    PATH=/usr/local/cuda-12.6/bin:/usr/local/cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    LIBRARY_PATH=/usr/local/cuda-12.6/targets/aarch64-linux/lib/stubs:/usr/local/cuda-12.6/targets/aarch64-linux/lib \
    LD_LIBRARY_PATH=/usr/local/cuda-12.6/targets/aarch64-linux/lib

FROM native-cuda-toolchain AS native-cuda-libraries
RUN mkdir -p /cuda-runtime-libs \
    && for library in libcudart libcublas libcublasLt libcurand libnvrtc libnvrtc-builtins; do \
         cp -a /usr/local/cuda-12.6/targets/aarch64-linux/lib/${library}.so* /cuda-runtime-libs/; \
       done

FROM native-toolchain AS native-source
COPY Cargo.lock native-assets.lock.json native-source.lock.json /integration/
COPY scripts/native_sources.py /integration/scripts/native_sources.py
COPY patches/ /integration/patches/
RUN python3 /integration/scripts/native_sources.py prepare --source /source \
    && python3 /integration/scripts/native_sources.py assets --destination /inputs \
    && rm /inputs/city-fixed.glb

FROM native-cuda-toolchain AS native-build
ARG NATIVE_FEATURES=vitfly-cuda,forest-world,autonomous-demo
COPY --from=native-source /source/ /src/
RUN --mount=type=cache,id=copper-flight-registry,target=/usr/local/cargo/registry \
    --mount=type=cache,id=copper-flight-build,target=/target \
    CARGO_TARGET_DIR=/target cargo build --locked --release --no-default-features \
       -p cu-flight-controller --features "${NATIVE_FEATURES}" --bin quad-sim \
    && mkdir -p /out && cp /target/release/quad-sim /out/quad-sim \
    && sha256sum /out/quad-sim > /out/sha256.txt

FROM ${UBUNTU_IMAGE} AS native-runtime-base
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ca-certificates python3 tini util-linux procps \
    libvulkan1 mesa-vulkan-drivers libegl1 libgl1 libgles2 \
    libwayland-client0 libwayland-egl1 libxkbcommon0 libxkbcommon-x11-0 libx11-6 libxcursor1 libxi6 libxrandr2 \
    libudev1 libasound2t64 xvfb xauth weston cage \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/copper-flight/bin /opt/copper-flight/assets /opt/copper-flight/models /opt/copper-flight/provenance /data
COPY --from=native-source /inputs/ /opt/copper-flight/assets/
RUN mv /opt/copper-flight/assets/models/vitfly-vitlstm-f32.safetensors /opt/copper-flight/models/ \
    && rmdir /opt/copper-flight/assets/models
COPY --from=native-source /source/examples/cu_flight_controller/assets/ /opt/copper-flight/assets/
COPY --from=native-source /source/LICENSE /opt/copper-flight/provenance/COPPER-LICENSE
COPY Cargo.lock native-source.lock.json native-assets.lock.json native-contract.md /opt/copper-flight/provenance/
ENV COPPER_FLIGHT_ASSET_DIR=/opt/copper-flight/assets \
    COPPER_FLIGHT_MODEL=/opt/copper-flight/models/vitfly-vitlstm-f32.safetensors \
    FLIGHT_WORLD=forest FLIGHT_EPISODE_SECONDS=45
WORKDIR /opt/copper-flight

# Local artifact handoff: --build-context native-binary=vendor-assets/native
FROM native-runtime-base AS native-local
COPY --from=native-binary /quad-sim /opt/copper-flight/bin/quad-sim
ENV FLIGHT_INFERENCE=cpu
CMD ["/opt/copper-flight/bin/quad-sim"]

FROM native-runtime-base AS native-cuda-runtime
# Only real toolkit user libraries, never libcuda or its link stubs.
COPY --from=native-cuda-libraries /cuda-runtime-libs/ /usr/local/lib/
COPY --from=native-cuda-toolchain /usr/share/doc/cuda-cudart-12-6/copyright /opt/copper-flight/provenance/CUDA-CUDART-LICENSE
COPY --from=native-cuda-toolchain /usr/share/doc/libcublas-12-6/copyright /opt/copper-flight/provenance/CUDA-CUBLAS-LICENSE
COPY --from=native-cuda-toolchain /usr/share/doc/libcurand-12-6/copyright /opt/copper-flight/provenance/CUDA-CURAND-LICENSE
COPY --from=native-cuda-toolchain /usr/share/doc/cuda-nvrtc-12-6/copyright /opt/copper-flight/provenance/CUDA-NVRTC-LICENSE
RUN ldconfig && test ! -e /usr/local/lib/libcuda.so
ENV FLIGHT_INFERENCE=cuda WGPU_BACKEND=vulkan VK_DRIVER_FILES=/etc/vulkan/icd.d/nvidia_icd.json
CMD ["/opt/copper-flight/bin/quad-sim"]

FROM native-cuda-runtime AS native-local-cuda
COPY --from=native-binary /quad-sim-cuda /opt/copper-flight/bin/quad-sim

FROM native-cuda-runtime AS native
COPY --from=native-build /out/quad-sim /opt/copper-flight/bin/quad-sim

# Data-only extraction of the exact matching image-owned NVIDIA graphics files.
FROM native-toolchain AS headless-graphics-payload
COPY graphics/assemble.py graphics/payload.lock.json /graphics/
COPY --from=graphics-debs /nvidia-l4t-3d-core.deb /debs/nvidia-l4t-3d-core.deb
COPY --from=graphics-debs /nvidia-l4t-core.deb /debs/nvidia-l4t-core.deb
RUN python3 /graphics/assemble.py --archives /debs --destination /graphics-rootfs

# Independent native targets above; the supervisor/UI are a separate final layer.
# Local release: native-binary=vendor-assets/adapter-proof; graphics-debs and probe-binary are named contexts.
FROM ${NATIVE_RUNTIME} AS flight
ARG IMAGE_REVISION=unknown
LABEL org.opencontainers.image.revision=${IMAGE_REVISION}
ENV IMAGE_REVISION=${IMAGE_REVISION}
COPY --from=headless-graphics-payload /graphics-rootfs/ /
COPY --from=probe-binary /copper-vulkan-depth-probe /usr/local/bin/copper-vulkan-depth-probe
COPY graphics/payload.lock.json /opt/copper-flight/provenance/payload.lock.json
RUN printf '%s\n' /usr/lib/aarch64-linux-gnu/nvidia > /etc/ld.so.conf.d/copper-headless-vulkan.conf && ldconfig
ENV VK_DRIVER_FILES=/etc/vulkan/icd.d/nvidia_icd.json \
    VK_ICD_FILENAMES=/etc/vulkan/icd.d/nvidia_icd.json \
    LD_LIBRARY_PATH=/run/admiral/nvidia/lib:/usr/lib/aarch64-linux-gnu/nvidia:/usr/local/lib
COPY service.py boot.py /opt/copper-flight/
COPY runtime/ /opt/copper-flight/runtime/
COPY scripts/start-flight scripts/run-native-flight /opt/copper-flight/scripts/
COPY www/ /opt/copper-flight/www/
RUN groupadd --gid 10001 copper-flight \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /data/copper-flight --shell /usr/sbin/nologin copper-flight \
    && chmod 0555 /opt/copper-flight/scripts/start-flight /opt/copper-flight/scripts/run-native-flight \
    && dpkg-query -W > /opt/copper-flight/provenance/runtime-packages.txt
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080 FLIGHT_DISPLAY_MODE=headless \
    FLIGHT_MAX_BYTES=8589934592
EXPOSE 8080
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/opt/copper-flight/scripts/start-flight"]
CMD []
