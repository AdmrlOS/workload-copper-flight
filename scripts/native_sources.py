#!/usr/bin/env python3
"""Acquire immutable native inputs; never run from the simulator process."""
import hashlib
import os
from pathlib import Path
import urllib.request
import subprocess


def prepare_source(directory, revision, patches):
    directory = Path(directory)
    head = subprocess.check_output(["git", "-C", str(directory), "rev-parse", "HEAD"], text=True).strip()
    if head != revision:
        raise ValueError(f"upstream revision mismatch: {head} != {revision}")
    for patch in patches:
        command = ["git", "-C", str(directory), "apply"]
        patch = str(Path(patch).resolve())
        already = subprocess.run(command + ["--reverse", "--check", patch], capture_output=True)
        if already.returncode == 0:
            continue
        subprocess.run(command + ["--check", patch], check=True)
        subprocess.run(command + [patch], check=True)


def acquire_blob(url, destination, sha256, size):
    """Verify a complete download before atomically publishing its filename."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    try:
        digest = hashlib.sha256()
        count = 0
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                count += len(chunk)
                output.write(chunk)
        if digest.hexdigest() != sha256 or count != size:
            raise ValueError(f"checksum/size mismatch for {url}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def acquire_locked_assets(manifest, directory):
    directory = Path(directory)
    for item in manifest["assets"]:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("asset path must be relative and contained")
        target = directory / relative
        valid = (target.is_file() and target.stat().st_size == item["size"]
                 and hashlib.sha256(target.read_bytes()).hexdigest() == item["sha256"])
        if not valid:
            acquire_blob(item["url"], target, item["sha256"], item["size"])


def main():
    import argparse
    import json
    import shutil
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--source", type=Path, required=True)
    assets = commands.add_parser("assets")
    assets.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.command == "assets":
        acquire_locked_assets(json.loads((root / "native-assets.lock.json").read_text()), args.destination)
        return
    lock = json.loads((root / "native-source.lock.json").read_text())
    if not args.source.exists():
        subprocess.run(["git", "clone", "--filter=blob:none", "--no-checkout", "--", lock["repository"], str(args.source)], check=True)
        subprocess.run(["git", "-C", str(args.source), "checkout", "--detach", lock["revision"]], check=True)
    prepare_source(args.source, lock["revision"], sorted((root / "patches").glob("*.patch")))
    for name in ["native_contract.rs", "native_status.rs"]:
        shutil.copyfile(root / "patches" / name, args.source / "examples/cu_flight_controller/src" / name)
    shutil.copyfile(root / "Cargo.lock", args.source / "Cargo.lock")


if __name__ == "__main__":
    main()
