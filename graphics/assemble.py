#!/usr/bin/env python3
"""Allowlist-only NVIDIA deb data extraction; never install a package."""
from pathlib import Path, PurePosixPath
import argparse
import json
import os
import subprocess
import tempfile
import hashlib
import tarfile


def stage_tar(archive, files, root):
    expected = {entry["path"]: entry for entry in files}
    found = set()
    seen = set()
    with (tarfile.open(fileobj=archive, mode="r:") if hasattr(archive, "read") else tarfile.open(archive, "r:")) as tar:
        for member in tar:
            if member.name in (".", "./"):
                continue
            name = member.name.removeprefix("./")
            safe_path(name)
            if name in seen:
                raise ValueError(f"duplicate tar member: {name}")
            seen.add(name)
            if name not in expected:
                continue
            entry = expected[name]
            if entry["type"] == "symlink":
                if not member.issym() or member.linkname != entry["target"]:
                    raise ValueError(f"symlink target mismatch: {name}")
                found.add(name)
                continue
            if not member.isfile():
                raise ValueError(f"expected regular file: {name}")
            stream = tar.extractfile(member)
            assert stream is not None
            content = stream.read()
            if len(content) != entry["bytes"] or hashlib.sha256(content).hexdigest() != entry["sha256"]:
                raise ValueError(f"payload checksum mismatch: {name}")
            destination = root / name
            if root.is_symlink() or any(parent.is_symlink() for parent in destination.parents if parent == root or root in parent.parents):
                raise ValueError(f"symlink ancestor forbidden: {name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as target:
                target.write(content)
            destination.chmod(0o644)
            found.add(name)
    if found != set(expected):
        raise ValueError(f"missing payload paths: {sorted(set(expected) - found)}")


def assemble(lock, archives, destination):
    validate_lock(lock)
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("destination already exists; never merge a payload")
    if not destination.parent.is_dir() or destination.parent.resolve() != destination.parent:
        raise ValueError("destination parent must exist without symlink ancestors")
    packages = lock["packages"]
    if len({p["name"] for p in packages}) != len(packages):
        raise ValueError("duplicate package")
    if {f["package"] for f in lock["files"]} - {p["name"] for p in packages}:
        raise ValueError("payload references unknown package")
    verified = []
    for package in packages:
        name = safe_path(package["archive"])
        if len(name.parts) != 1:
            raise ValueError("archive name must be a basename")
        archive = Path(archives) / str(name)
        if archive.is_symlink() or not archive.is_file():
            raise ValueError(f"archive must be a regular file: {archive}")
        with archive.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        if archive.stat().st_size != package["bytes"] or checksum != package["sha256"]:
            raise ValueError(f"archive checksum mismatch: {archive.name}")
        for field, key in (("Package", "name"), ("Version", "version"), ("Architecture", "architecture")):
            actual = subprocess.run(["dpkg-deb", "--field", str(archive), field], check=True,
                                    capture_output=True, text=True, timeout=15).stdout.strip()
            if actual != package[key]:
                raise ValueError(f"package identity mismatch: {archive.name} {field}")
        verified.append((package, archive))
    with tempfile.TemporaryDirectory(prefix=".graphics-", dir=destination.parent) as work:
        work = Path(work)
        root = work / "rootfs"
        root.mkdir()
        for package, archive in verified:
            with tempfile.TemporaryFile(dir=work) as data:
                subprocess.run(["dpkg-deb", "--fsys-tarfile", str(archive)], stdout=data,
                               stderr=subprocess.PIPE, check=True, timeout=120)
                data.seek(0)
                # Parse members ourselves: no tar extraction or script execution.
                stage_tar(data, [f for f in lock["files"] if f["package"] == package["name"]], root)
        for entry in lock["files"]:
            if entry["type"] == "symlink":
                link = root / entry["path"]
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(entry["target"])
        for path in root.rglob("*"):
            if path.name in lock["injected_library_exclusions"]:
                raise ValueError(f"injected basename found in staged payload: {path}")
        os.rename(root, destination)
    return {"status": "assembled-not-device-verified", "files": len(lock["files"]),
            "packages": len(packages), "destination": str(destination)}


def safe_path(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or str(path) != value or ".." in path.parts:
        raise ValueError(f"noncanonical payload path: {value!r}")
    return path


def validate_lock(lock):
    entries = {}
    for entry in lock["files"]:
        path = safe_path(entry["path"])
        if path.name in lock["injected_library_exclusions"]:
            raise ValueError(f"injected library basename forbidden: {path.name}")
        if str(path) in entries or entry["type"] not in ("file", "symlink"):
            raise ValueError(f"duplicate path or unsupported type: {path}")
        entries[str(path)] = entry
    for path, entry in entries.items():
        if any(str(parent) in entries for parent in safe_path(path).parents):
            raise ValueError(f"payload parent is not a directory: {path}")
        if entry["type"] == "symlink":
            target = entry["target"]
            # Absolute links are image-root-relative, never host-dereferenced.
            resolved = safe_path(target[1:] if target.startswith("/") else str(PurePosixPath(path).parent / target))
            if str(resolved) not in entries or entries[str(resolved)]["type"] != "file":
                raise ValueError(f"symlink must target an allowlisted regular file: {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=Path(__file__).with_name("payload.lock.json"))
    parser.add_argument("--archives", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(assemble(json.loads(args.lock.read_text()), args.archives, args.destination), sort_keys=True))
