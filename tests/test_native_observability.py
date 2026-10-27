"""Real native depth preview: compact, measured and explicitly unit-labelled."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "sha256:d9a1ea877f323cdc2721186cda8710dcc4ab7adbb8a749ef1737e1e3d4e9ed24"


class NativeObservabilityTests(unittest.TestCase):
    def test_actual_mm_samples_are_quantized_without_inventing_observations(self):
        self.assertIn("pub fn depth_preview_json", (ROOT / "patches/native_contract.rs").read_text(), "missing measured depth preview encoder")
        harness = r'''#[path="/project/patches/native_contract.rs"] mod contract;
fn main() {
    let mut mm = vec![0u16; 320*240];
    for y in 0..240 { for x in 0..320 { mm[y*320+x] = if x < 160 { 1000 } else { 20000 }; } }
    println!("{}", contract::depth_preview_json(&mm, 320, 240, 7, 2.0, 3.0).unwrap());
    assert!(contract::depth_preview_json(&vec![0; 320*240], 320, 240, 0, 0.0, 0.0).is_none());
    assert!(contract::depth_preview_json(&[1], 320, 240, 0, 0.0, 0.0).is_none());
    assert!(contract::depth_preview_json(&mm, 320, 240, 0, f64::NAN, 0.0).is_none());
    assert!(contract::depth_preview_json(&vec![20001; 320*240], 320, 240, 0, 0.0, 0.0).is_none());
}'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "test.rs").write_text(harness)
            result = subprocess.run(["docker", "run", "--rm", "--network", "none", "-v", f"{ROOT}:/project:ro", "-v", f"{path}:/check", IMAGE, "bash", "-c", "rustc --edition 2024 /check/test.rs -o /check/check && /check/check"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        preview = json.loads(result.stdout)
        self.assertEqual((preview["width"], preview["height"]), (32, 24))
        self.assertEqual(preview["source_seq"], 7)
        self.assertEqual(preview["source_units"], "millimetres")
        values = bytes.fromhex(preview["data"])
        self.assertEqual(len(values), 768)
        self.assertEqual(values[0], 14)
        self.assertEqual(values[-1], 255)
        self.assertLess(len(result.stdout), 4096)

    @unittest.skipUnless(os.environ.get("RUN_NATIVE_OBSERVABILITY"), "opt-in actual native software renderer")
    def test_actual_depth_is_present_changes_and_stays_compact(self):
        binary = Path(os.environ.get("NATIVE_OBSERVABILITY_BINARY", ROOT / "vendor-assets/native-observability/quad-sim"))
        label = os.environ.get("NATIVE_OBSERVABILITY_LABEL", "green")
        output = ROOT / "artifacts/native-observability" / label
        output.mkdir(parents=True, exist_ok=True)
        command = ["docker", "run", "--rm", "--init", "--network", "none", "--shm-size", "1g",
                   "-v", f"{binary}:/opt/copper-flight/bin/quad-sim:ro", "-v", f"{output}:/data",
                   "-e", "FLIGHT_DISPLAY_MODE=headless", "-e", "FLIGHT_INFERENCE=cpu",
                   "-e", "FLIGHT_NATIVE_LOG_MODE=telemetry-only", "-e", "COPPER_FLIGHT_LOG_DIR=/data/logs",
                   "-e", "COPPER_FLIGHT_TELEMETRY=/data/telemetry.jsonl", "-e", "FLIGHT_EPISODE_SECONDS=6",
                   "-e", "WGPU_BACKEND=vulkan", "-e", "WGPU_SETTINGS_PRIO=webgpu",
                   "workload-copper-flight:native-cpu-offscreen", "/opt/copper-flight/bin/quad-sim"]
        result = subprocess.run(command, text=True, capture_output=True, timeout=300)
        (output / "console.log").write_text(result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = (output / "telemetry.jsonl").read_text().splitlines()
        rows = [json.loads(line) for line in lines]
        observed = [r for r in rows if "depth_preview" in r]
        self.assertTrue(observed, "actual completed readbacks never exported a measured depth preview")
        self.assertNotIn("depth_preview", rows[0], "default source buffer masquerades as observation")
        unique = {r["depth_preview"]["source_seq"]: r["depth_preview"] for r in observed}
        self.assertGreater(len({p["data"] for p in unique.values()}), 1, "measured depth never changes")
        samples = list(unique.values())
        self.assertTrue(all(b["sample_wall_time_s"] - a["sample_wall_time_s"] >= 0.49 for a, b in zip(samples, samples[1:])))
        for row in observed:
            p = row["depth_preview"]
            self.assertEqual((p["width"], p["height"], p["source_width"], p["source_height"]), (32, 24, 320, 240))
            self.assertEqual(p["range_m"], [0.001, 20.0])
            self.assertEqual(p["source_units"], "millimetres")
            self.assertEqual(p["source"], "SimZedFrameStore.depth/Copper.ZedSource")
            self.assertEqual(p["invalid_u8"], 0)
            values = bytes.fromhex(p["data"])
            self.assertEqual(len(values), 768)
            self.assertTrue(any(values))
            self.assertTrue(all(0.001 <= (1+(v-1)*19999/254)/1000 <= 20 for v in values if v))
            self.assertLessEqual(p["sample_wall_time_s"], row["wall_time_s"])
            self.assertLessEqual(p["sample_sim_time_s"], row["sim_time_s"])
            self.assertIsNone(row["inference_count"])
            self.assertEqual(row["copper"]["recording_mode"], "telemetry-only")
        sizes = [len(line.encode())+1 for line in lines]
        self.assertLess(max(sizes), 8192)
        self.assertEqual([r["seq"] for r in rows], list(range(len(rows))))
        self.assertTrue(all(a["wall_time_s"] < b["wall_time_s"] for a,b in zip(rows, rows[1:])))
        poses = [r for r in rows if r["position_m"] is not None]
        self.assertTrue(all(0 < b["sim_time_s"]-a["sim_time_s"] <= 1/32 for a,b in zip(poses, poses[1:])))
        self.assertFalse(list((output / "logs").glob("*.copper")))
        (output / "measurement.json").write_text(json.dumps({"rows": len(rows), "preview_rows": len(observed), "unique_source_samples": len(unique), "unique_rasters": len({p["data"] for p in unique.values()}), "max_row_bytes": max(sizes), "total_bytes": sum(sizes), "samples": [{k:v for k,v in p.items() if k != "data"} for p in samples]}, indent=2)+"\n")


if __name__ == "__main__":
    unittest.main()
