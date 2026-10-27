#!/usr/bin/env python3
"""Acquire immutable native inputs; never run from the simulator process."""
import hashlib
import os
from pathlib import Path
import urllib.request
import subprocess
import tempfile


def prepare_source(directory, revision, patches):
    """Accept pristine or a known patch-stack prefix, never overwrite unknown edits."""
    directory = Path(directory)
    head = subprocess.check_output(["git", "-C", str(directory), "rev-parse", "HEAD"], text=True).strip()
    if head != revision:
        raise ValueError(f"upstream revision mismatch: {head} != {revision}")
    patches = [str(Path(patch).resolve()) for patch in patches]
    if not patches:
        return
    paths = set()
    for patch in patches:
        stats = subprocess.check_output(["git", "apply", "--numstat", patch], text=True)
        for line in stats.splitlines():
            name = line.split('\t', 2)[2]
            path = Path(name)
            if path.is_absolute() or '..' in path.parts or name.startswith('"'):
                raise ValueError('unsupported or unsafe patch path')
            paths.add(name)

    def snapshot(root):
        return {name: (root / name).read_bytes() if (root / name).is_file() else None for name in paths}

    # Reverse-checking an early patch independently is not idempotent when a
    # later patch overlaps its hunks. Reconstruct the small touched-file set.
    with tempfile.TemporaryDirectory(prefix='copper-patch-stack-') as temporary:
        expected = Path(temporary)
        subprocess.run(['git', 'init', '--quiet', str(expected)], check=True)
        for name in paths:
            original = subprocess.run(['git', '-C', str(directory), 'show', f'{revision}:{name}'], capture_output=True)
            if original.returncode == 0:
                target = expected / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(original.stdout)
        stages = [snapshot(expected)]
        for patch in patches:
            subprocess.run(['git', '-C', str(expected), 'apply', '--check', patch], check=True)
            subprocess.run(['git', '-C', str(expected), 'apply', patch], check=True)
            stages.append(snapshot(expected))
        current = snapshot(directory)
        matches = [index for index, stage in enumerate(stages) if current == stage]
        if not matches:
            raise ValueError('source has unrecognized edits in patched files; refusing to overwrite')
        for patch in patches[max(matches):]:
            command = ['git', '-C', str(directory), 'apply']
            subprocess.run(command + ['--check', patch], check=True)
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
