#!/usr/bin/env python3
"""Offline/locked CPU + CUDA candidate; preserve earlier verified binaries."""
from pathlib import Path
import hashlib
import json
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "vendor-assets/native-customer-perf"
IMAGE = "sha256:d9a1ea877f323cdc2721186cda8710dcc4ab7adbb8a749ef1737e1e3d4e9ed24"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def protected_hashes():
    return {str(p.relative_to(ROOT)): digest(p)
            for directory in [ROOT / "vendor-assets/native-performance", ROOT / "vendor-assets/native-observability"]
            for p in directory.rglob("*") if p.is_file() and not p.is_symlink()}


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if any((OUTPUT / name).exists() for name in ["quad-sim", "quad-sim-cuda"]):
        raise SystemExit("refusing to overwrite existing customer-performance candidate")
    before = protected_hashes()
    subprocess.run(["python3", str(ROOT / "scripts/native_sources.py"), "prepare", "--source", str(ROOT / "upstream")], check=True)
    sources = [ROOT / "patches/native_contract.rs", ROOT / "patches/native_status.rs", *sorted((ROOT / "patches").glob("*.patch")), ROOT / "Cargo.lock", ROOT / "upstream/examples/cu_flight_controller/src/sim.rs", ROOT / "upstream/examples/cu_flight_controller/src/sim_zed.rs"]
    source_hashes = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    command = ["docker", "run", "--rm", "--network", "none", "-v", f"{ROOT / 'upstream'}:/src:ro",
               "-v", "copper-flight-native-target:/target", "-v", "copper-flight-native-registry:/usr/local/cargo/registry",
               "-v", f"{OUTPUT}:/artifacts", "-e", "CARGO_TARGET_DIR=/target", IMAGE, "bash", "-c",
               "set -eu; rustc --version; "
               "cargo build --offline --locked --release --no-default-features -p cu-flight-controller --features sim,forest-world,autonomous-demo --bin quad-sim; "
               "cp /target/release/quad-sim /artifacts/quad-sim; "
               "cargo build --offline --locked --release --no-default-features -p cu-flight-controller --features vitfly-cuda,forest-world,autonomous-demo --bin quad-sim; "
               "cp /target/release/quad-sim /artifacts/quad-sim-cuda; sha256sum /artifacts/quad-sim*"]
    started = time.monotonic()
    with (OUTPUT / "build.log").open("w") as log:
        result = subprocess.run(command, text=True, stdout=log, stderr=subprocess.STDOUT)
    after = protected_hashes()
    report = {"command": command, "exit_code": result.returncode, "wall_s": time.monotonic() - started,
              "builder_image_id": IMAGE, "protected_unchanged": before == after,
              "protected_files": before, "sources": source_hashes,
              "sources_unchanged_during_build": source_hashes == {str(p.relative_to(ROOT)): digest(p) for p in sources}}
    report["binaries"] = {name: {"sha256": digest(OUTPUT / name), "bytes": (OUTPUT / name).stat().st_size}
                          for name in ["quad-sim", "quad-sim-cuda"] if (OUTPUT / name).exists()}
    (OUTPUT / "build.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k:v for k,v in report.items() if k not in ("protected_files", "sources")}, indent=2))
    if not report["protected_unchanged"] or not report["sources_unchanged_during_build"]:
        raise SystemExit("protected artifacts or build sources changed")
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
