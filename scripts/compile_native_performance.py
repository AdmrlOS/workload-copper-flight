#!/usr/bin/env python3
"""Rebuild both native ARM64 performance artifacts with cached pinned inputs."""
from pathlib import Path
import hashlib
import json
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "vendor-assets/native-performance"
IMAGE = "sha256:d9a1ea877f323cdc2721186cda8710dcc4ab7adbb8a749ef1737e1e3d4e9ed24"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    subprocess.run(["python3", str(ROOT / "scripts/native_sources.py"), "prepare", "--source", str(ROOT / "upstream")], check=True)
    command = ["docker", "run", "--rm", "--network", "none", "-v", f"{ROOT / 'upstream'}:/src:ro",
               "-v", "copper-flight-native-target:/target", "-v", "copper-flight-native-registry:/usr/local/cargo/registry",
               "-v", f"{OUTPUT}:/artifacts", "-e", "CARGO_TARGET_DIR=/target", IMAGE, "bash", "-c",
               "set -eu; rustc --version; "
               "cargo build --offline --locked --release --no-default-features -p cu-flight-controller --features sim,forest-world,autonomous-demo --bin quad-sim; "
               "cp /target/release/quad-sim /artifacts/quad-sim; "
               "cargo build --offline --locked --release --no-default-features -p cu-flight-controller --features vitfly-cuda,forest-world,autonomous-demo --bin quad-sim; "
               "cp /target/release/quad-sim /artifacts/quad-sim-cuda; sha256sum /artifacts/quad-sim*"]
    started = time.monotonic()
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (OUTPUT / "build.log").write_text(result.stdout)
    report = {"command": command, "exit_code": result.returncode, "wall_s": time.monotonic() - started, "builder_image_id": IMAGE}
    if not result.returncode:
        report["binaries"] = {name: {"sha256": hashlib.sha256((OUTPUT / name).read_bytes()).hexdigest(), "bytes": (OUTPUT / name).stat().st_size} for name in ["quad-sim", "quad-sim-cuda"]}
    (OUTPUT / "build.json").write_text(json.dumps(report, indent=2) + "\n")
    print(result.stdout)
    print(json.dumps(report, indent=2))
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
