#!/usr/bin/env python3
"""Independent offline native build; never writes native-performance artifacts."""
from pathlib import Path
import hashlib
import json
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "vendor-assets/native-observability"
IMAGE = "sha256:d9a1ea877f323cdc2721186cda8710dcc4ab7adbb8a749ef1737e1e3d4e9ed24"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    protected = [ROOT / "vendor-assets/native-performance", ROOT / "artifacts/native-canary-22aa313afe15", ROOT / "artifacts/native-performance"]
    before = {str(p.relative_to(ROOT)): digest(p) for directory in protected for p in directory.rglob("*") if p.is_file() and not p.is_symlink()}
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
    after = {str(p.relative_to(ROOT)): digest(p) for directory in protected for p in directory.rglob("*") if p.is_file() and not p.is_symlink()}
    report = {"command": command, "exit_code": result.returncode, "wall_s": time.monotonic() - started, "builder_image_id": IMAGE,
              "protected_unchanged": before == after, "protected_files": before,
              "performance_cuda_sha256": digest(ROOT / "vendor-assets/native-performance/quad-sim-cuda")}
    sources = [ROOT / "patches/native_contract.rs", ROOT / "patches/native_status.rs", *sorted((ROOT / "patches").glob("*.patch")), ROOT / "Cargo.lock", ROOT / "upstream/examples/cu_flight_controller/src/sim.rs", ROOT / "upstream/examples/cu_flight_controller/src/sim_zed.rs"]
    report["sources"] = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    if not result.returncode:
        report["binaries"] = {name: {"sha256": digest(OUTPUT / name), "bytes": (OUTPUT / name).stat().st_size} for name in ["quad-sim", "quad-sim-cuda"]}
    (OUTPUT / "build.json").write_text(json.dumps(report, indent=2) + "\n")
    print(result.stdout)
    print(json.dumps({k:v for k,v in report.items() if k != "protected_files"}, indent=2))
    if not report["protected_unchanged"]:
        raise SystemExit("protected native-performance/canary evidence changed")
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
