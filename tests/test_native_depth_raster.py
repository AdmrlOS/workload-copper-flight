"""Full native sensor raster contract, exercised with the pinned Rust toolchain."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "sha256:d9a1ea877f323cdc2721186cda8710dcc4ab7adbb8a749ef1737e1e3d4e9ed24"


def rust_output(harness):
    with tempfile.TemporaryDirectory(prefix="native-depth-") as directory:
        path = Path(directory)
        (path / "test.rs").write_text(harness)
        result = subprocess.run([
            "docker", "run", "--rm", "--network", "none",
            "-v", f"{ROOT}:/project:ro", "-v", f"{path}:/check", IMAGE,
            "bash", "-c", "rustc --edition 2024 -A dead_code /check/test.rs -o /check/check && /check/check",
        ], text=True, capture_output=True, timeout=120)
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout[-4000:])
    return result.stdout


def source_pixels():
    pixels = [(i * 193 + (i // 320) * 997) % 65536 for i in range(320 * 240)]
    pixels[:8] = [0, 1, 2, 1000, 19999, 20000, 20001, 65535]
    return pixels


def quantize(raw):
    return 1 + ((raw - 1) * 254 + 9999) // 19999 if 1 <= raw <= 20000 else 0


RASTER_HARNESS = r'''#[path="/project/patches/native_contract.rs"] mod contract;
fn main() {
    let mut mm: Vec<u16> = (0..320*240).map(|i| ((i*193 + (i/320)*997) % 65536) as u16).collect();
    mm[..8].copy_from_slice(&[0, 1, 2, 1000, 19999, 20000, 20001, 65535]);
    let (metadata, full) = contract::depth_raster_json(&mm, 320, 240, 73, 2.5, 4.25).unwrap();
    println!("{metadata}\n{full}");
}'''


class NativeDepthRasterTests(unittest.TestCase):
    def test_every_source_pixel_is_directly_quantized_not_thumbnail_upscaled(self):
        self.assertIn("pub fn depth_raster_json", (ROOT / "patches/native_contract.rs").read_text(),
                      "missing native 320x240 source-pixel encoder")
        metadata, full = map(json.loads, rust_output(RASTER_HARNESS).splitlines())
        data = full["data"]
        self.assertEqual((full["width"], full["height"]), (320, 240))
        self.assertEqual(full["sampling"], "identity")
        self.assertEqual(len(data), 153600)
        self.assertRegex(data, r"^[0-9a-f]{153600}$")
        actual = bytes.fromhex(data)
        expected = bytes(map(quantize, source_pixels()))
        self.assertEqual(len(actual), 76800)
        self.assertEqual(actual, expected, "each source pixel must be quantized directly in row-major order")
        thumbnail = [expected[((2*y+1)*240//48)*320 + ((2*x+1)*320//64)]
                     for y in range(24) for x in range(32)]
        upscaled = bytes(thumbnail[(y//10)*32 + x//10] for y in range(240) for x in range(320))
        self.assertNotEqual(actual, upscaled, "fixture must detect nearest-neighbor thumbnail upscaling")
        self.assertNotIn("data", metadata)

    def test_metadata_invalid_samples_and_legacy_thumbnail_contract(self):
        harness = RASTER_HARNESS.replace(
            'println!("{metadata}\\n{full}");',
            r'''println!("{metadata}\n{full}");
    println!("{}", contract::depth_preview_json(&mm, 320, 240, 73, 2.5, 4.25).unwrap());
    assert!(contract::depth_raster_json(&[1], 320, 240, 0, 0.0, 0.0).is_none());
    assert!(contract::depth_raster_json(&mm, 240, 320, 0, 0.0, 0.0).is_none());
    assert!(contract::depth_raster_json(&vec![0; 320*240], 320, 240, 0, 0.0, 0.0).is_none());
    assert!(contract::depth_raster_json(&vec![20001; 320*240], 320, 240, 0, 0.0, 0.0).is_none());
    for invalid in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        assert!(contract::depth_raster_json(&mm, 320, 240, 0, invalid, 0.0).is_none(), "nonfinite sampling time must be rejected");
        assert!(contract::depth_raster_json(&mm, 320, 240, 0, 0.0, invalid).is_none(), "nonfinite sampling time must be rejected");
    }
    // A valid pixel missed by the legacy thumbnail must still produce a full raster.
    let mut sparse = vec![0u16; 320*240]; sparse[0] = 1;
    assert!(contract::depth_raster_json(&sparse, 320, 240, 1, 0.0, 0.0).is_some());
    assert!(contract::depth_preview_json(&sparse, 320, 240, 1, 0.0, 0.0).is_none());''')
        metadata, full, preview = map(json.loads, rust_output(harness).splitlines())
        expected = dict(source="SimZedFrameStore.depth/Copper.ZedSource", source_seq=73,
                        source_width=320, source_height=240, width=320, height=240,
                        sample_sim_time_s=2.5, sample_wall_time_s=4.25,
                        encoding="u8-hex", sampling="identity", source_units="millimetres",
                        range_m=[0.001, 20.0], invalid_u8=0,
                        invalid_rule="source_mm == 0 or source_mm > 20000",
                        decode_m="(1 + (q - 1) * 19999 / 254) / 1000; q=0 invalid")
        self.assertEqual(metadata, expected)
        self.assertEqual({k: v for k, v in full.items() if k != "data"}, expected)
        self.assertEqual(bytes.fromhex(full["data"])[:8], bytes([0, 1, 1, 14, 255, 255, 0, 0]))
        expected_preview = dict(expected, width=32, height=24, sampling="nearest-cell-center")
        self.assertEqual({k: v for k, v in preview.items() if k != "data"}, expected_preview)
        pixels = source_pixels()
        self.assertEqual(bytes.fromhex(preview["data"]), bytes(
            quantize(pixels[((2*y+1)*240//48)*320 + ((2*x+1)*320//64)])
            for y in range(24) for x in range(32)))

    def test_file_events_precede_pose_metadata_are_cached_and_do_not_consume_pose_seq(self):
        status_source = (ROOT / "patches/native_status.rs").read_text()
        self.assertEqual(status_source.count(".with_inner("), 1,
                         "legacy thumbnail and raster must share the existing CPU handle access")
        harness = (ROOT / "tests/native_depth_status_harness.rs").read_text().replace(
            "// NATIVE_STATUS_IMPLEMENTATION", status_source.replace("#[derive(Resource)]", ""))
        rows = [json.loads(line) for line in rust_output(harness).splitlines()]
        events = [row for row in rows if row.get("kind") == "depth-raster"]
        poses = [row for row in rows if row.get("kind") != "depth-raster"]
        self.assertEqual(len(events), 3, "missing standalone depth-raster JSONL events in telemetry file")
        self.assertEqual([row["seq"] for row in poses], list(range(8)))
        self.assertEqual([row.get("depth_raster", {}).get("source_seq") for row in poses],
                         [None, 41, 41, 42, 42, None, None, 44])
        self.assertEqual([event["depth_raster"]["source_seq"] for event in events], [41, 42, 44])
        for index, row in enumerate(rows):
            if row.get("kind") == "depth-raster":
                self.assertEqual(set(row), {"schema_version", "kind", "depth_raster"})
                self.assertEqual(row["schema_version"], 1)
                raster = row["depth_raster"]
                self.assertEqual(len(raster["data"]), 153600)
                self.assertLess(len(json.dumps(row)), 192 * 1024)
                self.assertEqual(rows[index+1]["depth_raster"], {k: v for k, v in raster.items() if k != "data"})
            else:
                self.assertLess(len(json.dumps(row)), 8192)
                if "depth_raster" in row:
                    self.assertNotIn("data", row["depth_raster"])
        self.assertEqual(poses[1]["depth_raster"], poses[2]["depth_raster"])
        self.assertEqual(poses[3]["depth_raster"], poses[4]["depth_raster"])
        self.assertEqual(poses[1]["depth_preview"], poses[2]["depth_preview"])
        self.assertEqual(poses[1]["depth_preview"]["data"], "0e" * 768)
        self.assertEqual(poses[3]["depth_preview"]["data"], "ff" * 768)
        for index in [0, 5, 6, 7]:
            self.assertNotIn("depth_preview", poses[index])
        samples = [event["depth_raster"] for event in events]
        self.assertTrue(all(b["sample_wall_time_s"] - a["sample_wall_time_s"] >= 0.5
                            for a, b in zip(samples, samples[1:])))
        self.assertEqual(bytes.fromhex(samples[-1]["data"]), bytes([1]) + bytes(76800-1))


if __name__ == "__main__":
    unittest.main()
