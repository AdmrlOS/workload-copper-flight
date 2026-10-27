"""Image-owned graphics assembly contract; no device access required."""
import importlib.util
import io
import hashlib
import tarfile
import tempfile
import sys
import json
import shutil
import subprocess
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
if sys.platform == "darwin":
    tempfile.tempdir = str(Path.home() / ".hermes/cache/scratch")


class GraphicsPayloadTests(unittest.TestCase):
    def module(self):
        path = ROOT / "graphics" / "assemble.py"
        self.assertTrue(path.exists(), "graphics assembler must exist")
        spec = importlib.util.spec_from_file_location("graphics_assemble", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_rejects_noncanonical_source_paths(self):
        module = self.module()
        for value in ("/etc/passwd", "../escape", "usr/../escape", "usr//file", "./usr/file", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.safe_path(value)
        self.assertEqual(str(module.safe_path("usr/lib/example.so")), "usr/lib/example.so")

    def test_lock_rejects_injected_basename_in_any_directory(self):
        module = self.module()
        self.assertTrue(hasattr(module, "validate_lock"), "lock validation is required")
        lock = {"injected_library_exclusions": ["libcuda.so.1"], "files": [
            {"path": "opt/hidden/libcuda.so.1", "type": "file"}]}
        with self.assertRaisesRegex(ValueError, "injected"):
            module.validate_lock(lock)

    def test_lock_graph_rejects_duplicates_and_symlink_escapes(self):
        module = self.module()
        file = {"path": "usr/lib/target", "type": "file"}
        valid_link = {"path": "etc/icd.json", "type": "symlink", "target": "/usr/lib/target"}
        module.validate_lock({"files": [file, valid_link], "injected_library_exclusions": []})
        invalid = [
            [file, file],
            [file, {**valid_link, "target": "../../../escape"}],
            [file, {**valid_link, "target": "/missing"}],
            [file, {"path": "usr", "type": "symlink", "target": "/usr/lib/target"}],
            [file, {"path": "opt/target", "type": "hardlink", "target": "/usr/lib/target"}],
        ]
        for files in invalid:
            with self.subTest(files=files), self.assertRaises(ValueError):
                module.validate_lock({"files": files, "injected_library_exclusions": []})

    def test_extract_only_locked_regular_files_with_matching_hash(self):
        module = self.module()
        self.assertTrue(hasattr(module, "stage_tar"), "safe tar selection is required")
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            archive = base / "data.tar"
            content = b"real-selected-bytes"
            entry = {"path": "usr/lib/example.so", "type": "file", "bytes": len(content),
                     "sha256": hashlib.sha256(content).hexdigest()}
            with tarfile.open(archive, "w") as tar:
                for name in (entry["path"], "etc/not-allowlisted"):
                    member = tarfile.TarInfo("./" + name)
                    member.size = len(content)
                    tar.addfile(member, io.BytesIO(content))
            out = base / "rootfs"
            out.mkdir()
            module.stage_tar(archive, [entry], out)
            self.assertEqual((out / entry["path"]).read_bytes(), content)
            self.assertFalse((out / "etc").exists())
            bad = base / "bad"
            bad.mkdir()
            with self.assertRaisesRegex(ValueError, "checksum"):
                module.stage_tar(archive, [{**entry, "sha256": "0" * 64}], bad)

    def test_tar_rejects_existing_symlink_ancestors_and_duplicate_members(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            archive = base / "data.tar"
            entry = {"path": "usr/example", "type": "file", "bytes": 1,
                     "sha256": hashlib.sha256(b"x").hexdigest()}
            with tarfile.open(archive, "w") as tar:
                for _ in range(1):
                    member = tarfile.TarInfo("./usr/example")
                    member.size = 1
                    tar.addfile(member, io.BytesIO(b"x"))
            root = base / "root"
            root.mkdir()
            outside = base / "outside"
            outside.mkdir()
            (root / "usr").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                module.stage_tar(archive, [entry], root)
            self.assertFalse((outside / "example").exists())
            (root / "usr").unlink()
            with tarfile.open(archive, "a") as tar:
                member = tarfile.TarInfo("./usr/example")
                member.size = 1
                tar.addfile(member, io.BytesIO(b"x"))
            with self.assertRaisesRegex(ValueError, "duplicate"):
                module.stage_tar(archive, [entry], root)

    @unittest.skipUnless(sys.platform == "linux" and shutil.which("dpkg-deb"), "Linux dpkg-deb required")
    def test_assemble_real_deb_without_installing_or_following_links(self):
        module = self.module()
        self.assertTrue(hasattr(module, "assemble"), "assembly entry point required")
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "package"
            (source / "DEBIAN").mkdir(parents=True)
            (source / "DEBIAN/control").write_text("Package: fixture-graphics\nVersion: 1\nArchitecture: arm64\nMaintainer: Test <test@example.invalid>\nDescription: test only\n")
            marker = base / "must-not-run"
            script = source / "DEBIAN/postinst"
            script.write_text(f"#!/bin/sh\ntouch {marker}\n")
            script.chmod(0o755)
            library = source / "usr/lib/example.so"
            library.parent.mkdir(parents=True)
            library.write_bytes(b"fixture-library")
            link = source / "etc/icd.json"
            link.parent.mkdir()
            link.symlink_to("/usr/lib/example.so")
            deb = base / "fixture-graphics.deb"
            subprocess.run(["dpkg-deb", "--build", str(source), str(deb)], check=True, capture_output=True)
            lock = {"injected_library_exclusions": ["libcuda.so.1"], "packages": [{
                "name": "fixture-graphics", "archive": deb.name, "version": "1", "architecture": "arm64",
                "bytes": deb.stat().st_size, "sha256": hashlib.sha256(deb.read_bytes()).hexdigest()}],
                "files": [{"package": "fixture-graphics", "path": "usr/lib/example.so", "type": "file",
                           "bytes": library.stat().st_size, "sha256": hashlib.sha256(library.read_bytes()).hexdigest()},
                          {"package": "fixture-graphics", "path": "etc/icd.json", "type": "symlink", "target": "/usr/lib/example.so"}]}
            out = base / "rootfs"
            module.assemble(lock, base, out)
            self.assertEqual((out / "usr/lib/example.so").read_bytes(), library.read_bytes())
            self.assertEqual((out / "etc/icd.json").readlink().as_posix(), "/usr/lib/example.so")
            self.assertFalse(marker.exists())
            self.assertFalse((out / "DEBIAN").exists())
            with self.assertRaisesRegex(ValueError, "exist"):
                module.assemble(lock, base, out)
            deb.write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "archive checksum"):
                module.assemble(lock, base, base / "bad")
            self.assertFalse((base / "bad").exists())


@unittest.skipUnless(os.environ.get("GRAPHICS_PROBE_BIN"), "set GRAPHICS_PROBE_BIN in local Linux Mesa image")
class LocalRasterProbeTests(unittest.TestCase):
    def probe(self, *arguments):
        binary = Path(os.environ["GRAPHICS_PROBE_BIN"])
        self.assertTrue(binary.is_file(), "built probe binary must exist")
        environment = dict(os.environ, VK_DRIVER_FILES="/etc/vulkan/icd.d/nvidia_icd.json",
                           VK_ICD_FILENAMES="/etc/vulkan/icd.d/nvidia_icd.json")
        result = subprocess.run([str(binary), *arguments], capture_output=True, text=True,
                                timeout=30, env=environment)
        return result, json.loads(result.stdout)

    def test_explicit_software_rasterizes_and_overrides_both_icd_variables(self):
        result, report = self.probe("--software-verification")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(report["proof"], "software-not-Jetson-proof")
        self.assertEqual(report["adapter"]["device_type"], "Cpu")
        self.assertEqual(report["adapter"]["backend"], "Vulkan")
        self.assertEqual(report["vk_driver_files"], report["vk_icd_filenames"])
        self.assertIn("lvp", report["vk_driver_files"])
        self.assertIsNone(report["compatible_surface"])
        self.assertFalse(report["force_fallback_adapter"])
        self.assertTrue(report["rasterized"])
        self.assertEqual(report["bytes_per_row"], 256)
        self.assertAlmostEqual(report["depth"]["center"], 0.25, places=4)
        self.assertAlmostEqual(report["depth"]["background"], 1.0, places=4)

    def test_default_is_nvidia_only_and_fails_on_local_mesa_host(self):
        result, report = self.probe()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["proof"], "NVIDIA-hardware-required")
        self.assertFalse(report["rasterized"])
        self.assertIn("nvidia_icd.json", report["vk_driver_files"])


if __name__ == "__main__":
    unittest.main()
