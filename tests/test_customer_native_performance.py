"""Native presentation-only optimization; no sensor/control-rate substitutions."""
import json
import os
from pathlib import Path
import subprocess
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CustomerNativePerformanceTests(unittest.TestCase):
    def test_only_offscreen_presentation_camera_is_disabled(self):
        source = (ROOT / "upstream/examples/cu_flight_controller/src/sim.rs").read_text()
        presentation = source.split('let mut camera = commands.spawn((', 1)[1].split('let depth_texture =', 1)[0]
        self.assertIn('is_active: !native_offscreen(),', presentation,
                      "offscreen presentation camera still submits unused 800x600 drawing")
        sensors = source.split('Name::new("zed2i-left-depth-camera")', 1)[1].split('Name::new("sun")', 1)[0]
        self.assertNotIn('is_active:', sensors, "sensor camera activation must remain unchanged")
        self.assertIn('DepthPrepass,', sensors)
        self.assertIn('.observe(capture_zed_depth)', sensors)
        self.assertIn('.observe(capture_zed_left_image)', sensors)
        self.assertIn('.observe(capture_zed_right_image)', sensors)

    @unittest.skipUnless(os.environ.get("RUN_CUSTOMER_NATIVE_PERF"), "opt-in real native/software execution")
    def test_sensor_policy_physics_progress_without_presentation(self):
        binary = Path(os.environ.get("CUSTOMER_NATIVE_PERF_BINARY", ROOT / "vendor-assets/native-customer-perf/quad-sim"))
        label = os.environ.get("CUSTOMER_NATIVE_PERF_LABEL", "green")
        output = ROOT / "artifacts/native-customer-perf" / label
        output.mkdir(parents=True, exist_ok=True)
        command = ["docker", "run", "--rm", "--init", "--network", "none", "--shm-size", "1g",
                   "-v", f"{binary}:/opt/copper-flight/bin/quad-sim:ro", "-v", f"{output}:/data",
                   "-e", "FLIGHT_DISPLAY_MODE=headless", "-e", "FLIGHT_INFERENCE=cpu",
                   "-e", "FLIGHT_NATIVE_LOG_MODE=telemetry-only", "-e", "COPPER_FLIGHT_LOG_DIR=/data/logs",
                   "-e", "COPPER_FLIGHT_TELEMETRY=/data/telemetry.jsonl", "-e", "FLIGHT_EPISODE_SECONDS=6",
                   "-e", "WGPU_BACKEND=vulkan", "-e", "WGPU_SETTINGS_PRIO=webgpu",
                   "sha256:689ddbe3caff4ae9e45a569d1e2a7f409cc202455f0869d6ddac0dada862f3c5", "/opt/copper-flight/bin/quad-sim"]
        started = time.monotonic()
        result = subprocess.run(command, text=True, capture_output=True, timeout=240)
        wall = time.monotonic() - started
        (output / "console.log").write_text(result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = [json.loads(line) for line in (output / "telemetry.jsonl").read_text().splitlines()]
        poses = [r for r in rows if r["position_m"] is not None]
        observed = [r for r in rows if "depth_preview" in r]
        self.assertTrue(observed, "no actual completed depth readbacks")
        first_observed = next(i for i,r in enumerate(rows) if "depth_preview" in r)
        self.assertTrue(all("depth_preview" in r for r in rows[first_observed:]), "depth observations disappeared")
        previews = {r["depth_preview"]["source_seq"]: r["depth_preview"] for r in observed}
        self.assertGreater(len(previews), 1, "depth readback sequence did not advance")
        self.assertGreater(len({p["data"] for p in previews.values()}), 1, "actual depth pixels did not change")
        self.assertTrue(all((p["source_width"], p["source_height"]) == (320, 240) for p in previews.values()))
        self.assertGreater(len(poses), 300, "physics steps missing")
        gaps = [b["sim_time_s"] - a["sim_time_s"] for a,b in zip(poses, poses[1:])]
        self.assertTrue(all(0 < gap <= 1/32 for gap in gaps), "fixed physics steps skipped")
        self.assertGreater(len({r["policy_observation_seq"] for r in observed}), 1, "Copper policy publications stopped")
        self.assertTrue(all(r["policy_prediction_m_s"] is not None for r in observed), "missing policy observation after depth readback")
        self.assertTrue(any(r["armed"] and r["auto_enabled"] for r in poses), "autonomous flight never started")
        self.assertGreater(len({tuple(r["position_m"][axis] for axis in 'xyz') for r in poses}), 5, "physical pose never changed")
        self.assertEqual([r["seq"] for r in rows], list(range(len(rows))))
        self.assertFalse(list((output / "logs").glob("*.copper")))
        summary = {"binary": str(binary), "command": command, "wall_s": wall, "rows": len(rows),
                   "pose_rows": len(poses), "max_sim_gap_s": max(gaps), "depth_samples": len(previews),
                   "unique_depth_rasters": len({p["data"] for p in previews.values()}),
                   "first_observed_row": first_observed,
                   "policy_publications_first": observed[0]["policy_observation_seq"],
                   "policy_publications_last": observed[-1]["policy_observation_seq"],
                   "last_sim_s": poses[-1]["sim_time_s"], "software_renderer_not_jetson_benchmark": True}
        (output / "measurement.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main()
