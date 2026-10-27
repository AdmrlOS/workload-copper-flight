"""Regression tests for pinned native source and asset acquisition."""
import hashlib
import importlib.util
import pathlib
import os
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def sources_module():
    path = ROOT / "scripts" / "native_sources.py"
    if not path.is_file():
        raise AssertionError("missing native source/asset acquisition helper")
    spec = importlib.util.spec_from_file_location("native_sources", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SourcesTests(unittest.TestCase):
    def test_locked_download_checks_bytes_before_publication(self):
        source = sources_module()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            origin, destination = root / "origin", root / "asset"
            origin.write_bytes(b"real acquisition fixture")
            digest = hashlib.sha256(origin.read_bytes()).hexdigest()
            source.acquire_blob(origin.as_uri(), destination, digest, origin.stat().st_size)
            self.assertEqual(destination.read_bytes(), origin.read_bytes())
            destination.unlink()
            with self.assertRaisesRegex(ValueError, "checksum"):
                source.acquire_blob(origin.as_uri(), destination, "0" * 64, origin.stat().st_size)
            self.assertFalse(destination.exists())


    def test_corrupt_cached_asset_is_rejected_and_reacquired(self):
        source = sources_module()
        self.assertTrue(hasattr(source, "acquire_locked_assets"), "missing lock manifest acquisition")
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            original = root / "original"
            original.write_bytes(b"asset")
            entry = {"url": original.as_uri(), "path": "scene.glb", "sha256": hashlib.sha256(b"asset").hexdigest(), "size": 5}
            target = root / "assets"
            target.mkdir()
            (target / "scene.glb").write_bytes(b"corrupt")
            source.acquire_locked_assets({"assets": [entry]}, target)
            self.assertEqual((target / "scene.glb").read_bytes(), b"asset")


    def test_locked_paths_cannot_escape_the_acquisition_root(self):
        source = sources_module()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            origin = root / "original"
            origin.write_bytes(b"asset")
            fields = {"url": origin.as_uri(), "size": 5, "sha256": hashlib.sha256(b"asset").hexdigest()}
            with self.assertRaisesRegex(ValueError, "relative"):
                source.acquire_locked_assets({"assets": [{**fields, "path": "../escape"}]}, root / "safe")
            with self.assertRaisesRegex(ValueError, "relative"):
                source.acquire_locked_assets({"assets": [{"path": "/escape"}]}, root)


    @unittest.skipUnless(os.environ.get("RUN_NATIVE_RUST_TESTS"), "opt-in Linux Rust toolchain test")
    def test_native_duration_parser_rejects_invalid_deadlines(self):
        self.assertTrue((ROOT / "patches/native_contract.rs").is_file(), "missing native runtime contract helper")
        harness = r'''#[path="/project/patches/native_contract.rs"] mod contract;
#[test] fn offscreen() {
    assert!(contract::offscreen_mode(Some("headless")));
    assert!(contract::offscreen_mode(Some("software")));
    for mode in [None, Some("drm"), Some("existing")] { assert!(!contract::offscreen_mode(mode)); }
}
#[test] fn duration() {
    assert_eq!(contract::episode_seconds(None).unwrap(), 45.0);
    assert_eq!(contract::episode_seconds(Some("12.5")).unwrap(), 12.5);
    for bad in ["", "-1", "0", "NaN", "inf", "wat"] {
        assert!(contract::episode_seconds(Some(bad)).is_err(), "{bad}");
    }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / "test.rs").write_text(harness)
            result = subprocess.run(["docker", "run", "--rm", "--network", "none", "-v", f"{ROOT}:/project:ro", "-v", f"{path}:/check", "workload-copper-flight:toolchain", "bash", "-c", "rustc --edition 2024 --test /check/test.rs -o /check/check && /check/check"], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


    def test_native_status_exports_observed_adapter_vendor_and_device_type(self):
        status = (ROOT / "patches/native_status.rs").read_text()
        self.assertIn("graphics_vendor_id: adapter.as_ref().map(|info| info.vendor)", status)
        self.assertIn('adapter.as_ref().map(|info| format!("{:?}", info.device_type))', status)
        self.assertIn("graphics_device_type: graphics_device_type.as_deref()", status)
        self.assertNotIn("unwrap_or", status)

    def test_source_revision_mismatch_is_not_silently_repaired(self):
        source = sources_module()
        self.assertTrue(hasattr(source, "prepare_source"), "missing pinned source preparation")
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "upstream"
            subprocess.run(["git", "clone", "--shared", "--no-checkout", str(ROOT / "upstream"), str(target)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(target), "checkout", "--detach", "d46ef87a65c7ba93bcad3c236da99e52cd77f319"], check=True, capture_output=True)
            source.prepare_source(target, "d46ef87a65c7ba93bcad3c236da99e52cd77f319", [])
            with self.assertRaisesRegex(ValueError, "revision"):
                source.prepare_source(target, "0" * 40, [])


    @unittest.skipUnless(os.environ.get("RUN_NATIVE_RUST_TESTS"), "opt-in Linux Rust toolchain test")
    def test_telemetry_serializer_preserves_unknowns_and_escapes(self):
        self.assertIn("pub struct Snapshot", (ROOT / "patches/native_contract.rs").read_text(), "missing telemetry snapshot")
        harness = r'''#[path="/project/patches/native_contract.rs"] mod contract;
fn main() {
    let sample = contract::Snapshot {
        seq: 2, sim_time_s: 4.5, position_m: Some([1.0, 2.0, 3.0]), rotation: Some([0.0, 0.0, 0.0, 1.0]),
        velocity_m_s: None, armed: true, auto_enabled: true,
        mode: "Angle", world: "forest", policy_prediction_m_s: None, policy_observation_seq: 7,
        inference_backend: Some("cpu"), graphics_backend: Some("Vulkan"),
        graphics_adapter: Some("quoted\"\\\n\u{0001} adapter"),
        graphics_vendor_id: None, graphics_device_type: None,
    };
    println!("{}", sample.json());
    let cpu = contract::Snapshot {
        graphics_vendor_id: Some(65541), graphics_device_type: Some("Cpu"), ..sample
    };
    println!("{}", cpu.json());
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / "test.rs").write_text(harness)
            result = subprocess.run(["docker", "run", "--rm", "--network", "none", "-v", f"{ROOT}:/project:ro", "-v", f"{path}:/check", "workload-copper-flight:toolchain", "bash", "-c", "rustc --edition 2024 /check/test.rs -o /check/check && /check/check"], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            import json
            row, cpu = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertIsNone(row["graphics_vendor_id"])
            self.assertIsNone(row["graphics_device_type"])
            self.assertEqual(cpu, dict(row, graphics_vendor_id=65541, graphics_device_type="Cpu"))
            self.assertEqual(row["position_m"], {"x": 1.0, "y": 2.0, "z": 3.0})
            self.assertEqual(row["graphics_adapter"], 'quoted"\\\n\x01 adapter')
            self.assertIsNone(row["inference_count"])
            self.assertIsNone(row["velocity_m_s"])
            self.assertEqual(row["rotation"], {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0})
            self.assertEqual(row["policy_observation_seq"], 7)
            self.assertEqual(row["schema_version"], 1)


    def test_source_patches_apply_idempotently(self):
        source = sources_module()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            target = root / "upstream"
            subprocess.run(["git", "clone", "--shared", str(ROOT / "upstream"), str(target)], check=True, capture_output=True)
            patch = root / "example.patch"
            patch.write_text('diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1,2 @@\n+Test fixture header\n <h1 align="center">\n')
            revision = "d46ef87a65c7ba93bcad3c236da99e52cd77f319"
            source.prepare_source(target, revision, [patch])
            self.assertTrue((target / "README.md").read_text().startswith("Test fixture header"))
            source.prepare_source(target, revision, [patch])
            self.assertEqual((target / "README.md").read_text().count("Test fixture header"), 1)


    def test_prepare_cli_reconstructs_the_pinned_patched_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "upstream"
            subprocess.run(["git", "clone", "--shared", str(ROOT / "upstream"), str(target)], check=True, capture_output=True)
            result = subprocess.run(["python3", str(ROOT / "scripts/native_sources.py"), "prepare", "--source", str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("mod native_status;", (target / "examples/cu_flight_controller/src/sim.rs").read_text())
            self.assertEqual((target / "examples/cu_flight_controller/src/native_contract.rs").read_bytes(), (ROOT / "patches/native_contract.rs").read_bytes())
            self.assertEqual((target / "Cargo.lock").read_bytes(), (ROOT / "Cargo.lock").read_bytes())
            # Later patches overlap earlier hunks; reconstruction must still be idempotent.
            again = subprocess.run(["python3", str(ROOT / "scripts/native_sources.py"), "prepare", "--source", str(target)], capture_output=True, text=True)
            self.assertEqual(again.returncode, 0, again.stdout + again.stderr)


if __name__ == "__main__":
    unittest.main()
