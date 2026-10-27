"""Native behavior probes: genuine fixed-step poses and explicit recording policy."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativePerformanceTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("RUN_NATIVE_PERFORMANCE"), "opt-in native Linux execution")
    def test_real_fixed_ticks_are_not_collapsed_into_update_frames(self):
        output, rows = self.run_native("full")
        self.assertEqual([row["seq"] for row in rows], list(range(len(rows))))
        self.assertTrue(all("wall_time_s" in row for row in rows), "missing native per-sample monotonic wall time")
        self.assertTrue(all(a["wall_time_s"] < b["wall_time_s"] for a, b in zip(rows, rows[1:])))
        self.assertTrue(all(a["sim_time_s"] <= b["sim_time_s"] for a, b in zip(rows, rows[1:])))
        self.assertTrue(all(len(line.encode()) <= 65536 for line in (output / "telemetry.jsonl").read_text().splitlines()))

    @unittest.skipUnless(os.environ.get("RUN_NATIVE_PERFORMANCE"), "opt-in native Linux execution")
    def test_demo_profile_avoids_raster_recording_but_keeps_real_policy(self):
        output, rows = self.run_native("telemetry-only")
        self.assertFalse(list((output / "logs").glob("*.copper")), "demo profile still serialized raw camera logs")
        self.assertTrue(any(row["policy_prediction_m_s"] is not None for row in rows))
        self.assertTrue(all(row["copper"]["recording_mode"] == "telemetry-only" for row in rows))
        self.assertTrue(all(row["copper"]["full_recording"] is False for row in rows))

    def run_native(self, mode):
        binary = Path(os.environ.get("NATIVE_PERFORMANCE_BINARY", ROOT / "vendor-assets/adapter-proof/quad-sim"))
        output = ROOT / "artifacts/native-performance" / (os.environ.get("NATIVE_PERFORMANCE_LABEL", "probe") + "-" + mode)
        output.mkdir(parents=True, exist_ok=True)
        command = ["docker", "run", "--rm", "--init", "--network", "none", "--shm-size", "1g",
                   "-v", f"{binary}:/opt/copper-flight/bin/quad-sim:ro", "-v", f"{output}:/data",
                   "-e", "FLIGHT_DISPLAY_MODE=headless", "-e", "FLIGHT_INFERENCE=cpu",
                   "-e", f"FLIGHT_NATIVE_LOG_MODE={mode}", "-e", "COPPER_FLIGHT_LOG_DIR=/data/logs",
                   "-e", "COPPER_FLIGHT_TELEMETRY=/data/telemetry.jsonl", "-e", "FLIGHT_EPISODE_SECONDS=2",
                   "-e", "WGPU_BACKEND=vulkan", "-e", "WGPU_SETTINGS_PRIO=webgpu",
                   "workload-copper-flight:native-cpu-offscreen", "/opt/copper-flight/bin/quad-sim"]
        import time
        start = time.monotonic()
        result = subprocess.run(command, text=True, capture_output=True, timeout=90)
        wall = time.monotonic() - start
        (output / "console.log").write_text(result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = [json.loads(line) for line in (output / "telemetry.jsonl").read_text().splitlines()]
        poses = [row for row in rows if row["position_m"] is not None]
        times = [row["sim_time_s"] for row in poses]
        (output / "measurement.json").write_text(json.dumps({"wall_s": wall, "rows": len(rows), "pose_rows": len(poses), "first_sim_s": times[0], "last_sim_s": times[-1], "max_sim_gap_s": max(b-a for a,b in zip(times, times[1:]))}, indent=2))
        if mode == "full":
            self.assertTrue(list((output / "logs").glob("*.copper")), "full recording must retain actual binary logs")
        else:
            self.assertFalse(list((output / "logs").glob("*.copper")), "demo profile still serialized raw camera logs")
        self.assertGreaterEqual(len(poses), 60, "genuine fixed-step poses were collapsed or wall-throttled")
        self.assertTrue(all(0 < b-a <= 1/32 for a,b in zip(times, times[1:])), "pose export skipped genuine physics steps")
        return output, rows

    def test_recording_mode_defaults_full_and_rejects_ambiguous_values(self):
        harness = r'''#[path="/project/patches/native_contract.rs"] mod contract;
#[test] fn logging_policy_is_explicit() {
    assert_eq!(contract::native_log_mode(None).unwrap(), contract::NativeLogMode::Full);
    assert_eq!(contract::native_log_mode(Some("full")).unwrap(), contract::NativeLogMode::Full);
    assert_eq!(contract::native_log_mode(Some("telemetry-only")).unwrap(), contract::NativeLogMode::TelemetryOnly);
    for bad in ["", "off", "fast", "FULL"] { assert!(contract::native_log_mode(Some(bad)).is_err()); }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "test.rs").write_text(harness)
            result = subprocess.run(["docker", "run", "--rm", "--network", "none", "-v", f"{ROOT}:/project:ro", "-v", f"{path}:/check", "workload-copper-flight:toolchain", "bash", "-c", "rustc --edition 2024 --test /check/test.rs -o /check/check && /check/check"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
