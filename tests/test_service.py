import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def frame(seq=0, sim=0.0):
    # Deliberately synthetic TEST INPUT only, never production telemetry.
    return dict(schema_version=1, seq=seq, sim_time_s=sim,
                position_m=None, velocity_m_s=None, armed=False,
                auto_enabled=False, mode="Angle", world="forest",
                policy_prediction_m_s=None, inference_backend=None,
                inference_count=None, graphics_backend=None, graphics_adapter=None)


class StateTests(unittest.TestCase):
    def test_unknown_adapter_metadata_stays_nullable_in_normalized_graphics(self):
        from service import StateStore, validate_frame
        unknown = dict(backend=None, adapter_name=None, vendor_id=None, device_type=None)
        samples = [frame(),
                   {key: value for key, value in frame().items() if not key.startswith("graphics_")},
                   dict(frame(), graphics=dict(backend=None, adapter_name=None)),
                   dict(frame(), graphics_vendor_id=None, graphics_device_type=None),
                   dict(frame(), graphics=unknown)]
        for sample in samples:
            with self.subTest(sample=sample):
                observed = validate_frame(json.dumps(sample))
                state = StateStore()
                state.publish(observed)
                published = state.snapshot()["frame"]
                self.assertEqual(published["graphics"], unknown)
                self.assertIsNone(published["inference_count"])
                self.assertEqual(observed, sample)

    def test_flat_actual_graphics_normalizes_for_ui_without_inventing_counts(self):
        from service import StateStore
        state = StateStore()
        state.publish(dict(frame(), graphics_backend="Vulkan", graphics_adapter="observed NVIDIA adapter"))
        self.assertEqual(state.snapshot()["frame"]["graphics"],
                         dict(backend="Vulkan", adapter_name="observed NVIDIA adapter", vendor_id=None, device_type=None))
        self.assertIsNone(state.snapshot()["frame"]["inference_count"])

    def test_health_requires_advancing_simulation_not_fps_or_cuda_flag(self):
        from service import StateStore
        state = StateStore(revision="test", world="forest", inference="cpu", inactivity_timeout=0.2)
        self.assertFalse(state.ready())
        state.begin("20261027T000000Z-1234abcd")
        state.publish(frame())
        self.assertFalse(state.ready())
        state.publish(frame(1, .1))
        self.assertTrue(state.ready())
        progress = state.progress_at
        state.publish(frame(2, .1))
        self.assertFalse(state.ready(now=progress + .3))
        snap = state.snapshot()
        self.assertTrue(snap["engine"]["native"])
        self.assertEqual(snap["configuration"]["episode_seconds"], 45)
        self.assertEqual(snap["frame"], dict(frame(2, .1), graphics=dict(backend=None, adapter_name=None, vendor_id=None, device_type=None)))
        snap["frame"]["seq"] = 88
        self.assertEqual(state.snapshot()["frame"]["seq"], 2)
        state.fail("engine died")
        self.assertEqual(state.snapshot()["status"], "failed")
        self.assertFalse(state.ready())


class TelemetryTests(unittest.TestCase):
    def test_adapter_metadata_rejects_invalid_vendor_types_ranges_and_device_enum(self):
        from service import validate_frame
        for key, invalid in (("vendor_id", [True, False, -1, 4294967296, 65541.0, "65541", [], {}]),
                             ("device_type", [True, 1, "DeviceTypeCpu", "cpu", "Unknown", "NVIDIA", [], {}])):
            for value in invalid:
                for nested in (False, True):
                    sample = frame()
                    if nested:
                        sample["graphics"] = dict(backend="Vulkan", adapter_name="observed adapter", **{key: value})
                    else:
                        sample["graphics_" + key] = value
                    with self.subTest(key=key, value=value, nested=nested), self.assertRaises(ValueError):
                        validate_frame(json.dumps(sample))

    def test_actual_cpu_metadata_normalizes_without_becoming_a_gpu_or_inference_count(self):
        from service import StateStore, validate_frame
        graphics = dict(backend="Vulkan", adapter_name="llvmpipe (LLVM TEST)", vendor_id=65541, device_type="Cpu")
        samples = [dict(frame(), graphics_backend=graphics["backend"], graphics_adapter=graphics["adapter_name"],
                        graphics_vendor_id=65541, graphics_device_type="Cpu"), dict(frame(), graphics=graphics)]
        for sample in samples:
            sample.update(policy_observation_seq=17, inference_backend="cpu")
            with self.subTest(sample=sample):
                validated = validate_frame(json.dumps(sample))
                state = StateStore()
                state.publish(validated)
                published = state.snapshot()["frame"]
                self.assertEqual(published["graphics"], graphics)
                self.assertEqual(published["policy_observation_seq"], 17)
                self.assertEqual(published["inference_backend"], "cpu")
                self.assertIsNone(published["inference_count"])
                self.assertEqual(validated, sample)
        for vendor in (None, 0, 4318, 4294967295):
            for device in (None, "IntegratedGpu", "DiscreteGpu", "Cpu", "VirtualGpu", "Other"):
                for nested in (False, True):
                    sample = frame()
                    if nested:
                        sample["graphics"] = dict(graphics, vendor_id=vendor, device_type=device)
                    else:
                        sample.update(graphics_vendor_id=vendor, graphics_device_type=device)
                    with self.subTest(vendor=vendor, device=device, nested=nested):
                        self.assertEqual(validate_frame(json.dumps(sample)), sample)

    def test_known_policy_counter_and_malformed_containers_are_rejected_safely(self):
        from service import validate_frame
        for updates in [dict(policy_observation_seq=-1), dict(policy_observation_seq=True),
                        dict(policy_observation_seq="12"), dict(world=[]), dict(inference_backend={}),
                        dict(sim_time_s=10**400), dict(rotation=dict(x=0, y=0, z=0, w=0))]:
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                validate_frame(json.dumps(dict(frame(), **updates)))
        observed = dict(frame(), policy_observation_seq=12)
        self.assertEqual(validate_frame(json.dumps(observed)), observed)

    def test_bounded_native_frames_reject_malformed_nonfinite_and_regression(self):
        from service import TelemetryReader, validate_frame
        valid = frame()
        self.assertEqual(validate_frame(json.dumps(valid)), valid)
        observed = frame(1, .5)
        observed.update(position_m=dict(x=1, y=2, z=3), inference_backend="cuda",
                        graphics=dict(backend="Vulkan", adapter_name="observed adapter"))
        self.assertEqual(validate_frame(json.dumps(observed)), observed)
        bad = [None, [], dict(valid, seq=True), dict(valid, sim_time_s=float("nan")),
               dict(valid, armed=1), dict(valid, world="../urban"),
               dict(valid, position_m=dict(x=1, y=2)), dict(valid, inference_backend="compiled_cuda"),
               dict(valid, extra={"nan": float("inf")}), dict(valid, schema_version=2)]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_frame(json.dumps(value))
        for payload in ['{"schema_version":1,"x":' + '[' * 10000 + '0' + ']' * 10000 + '}',
                        'x' * 65537, '{"seq":0,"seq":1}', '{']:
            with self.assertRaises(ValueError):
                validate_frame(payload)
        with tempfile.TemporaryFile() as stream:
            reader = TelemetryReader(stream)
            stream.write((json.dumps(frame()) + '\n' + json.dumps(frame(1, .1))[:10]).encode())
            stream.flush()
            self.assertEqual(reader.poll(), [frame()])
            stream.seek(0, 2)
            stream.write((json.dumps(frame(1, .1))[10:] + '\n').encode())
            stream.flush()
            self.assertEqual(reader.poll(), [frame(1, .1)])
            stream.seek(0, 2)
            stream.write((json.dumps(frame(2, .05)) + '\n').encode())
            stream.flush()
            with self.assertRaisesRegex(ValueError, "regress"):
                reader.poll()


class RecordingTests(unittest.TestCase):
    def test_recording_root_rejects_symlink_ancestors_before_creating_anything(self):
        from service import RecordingStore
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            outside = root / "outside"
            outside.mkdir()
            (root / "alias").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(OSError):
                RecordingStore(root / "alias/runs")
            self.assertEqual(list(outside.iterdir()), [])

    def test_archive_includes_native_logs_subdirectory_and_rejects_external_aliases(self):
        import io
        import tarfile
        from service import RecordingStore, archive_into
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            store = RecordingStore(root / "runs")
            run_id = "20261027T000000Z-1234abcd"
            run = store.begin(run_id)
            logs = run / "logs"
            self.assertTrue(logs.is_dir(), "run has no isolated native log directory")
            for family in ["flight_compute_sim", "flight_controller_sim"]:
                (logs / (family + "_0.copper")).write_bytes(b"TEST slab zero")
                (logs / (family + "_1.copper")).write_bytes(b"TEST slab one")
                (logs / (family + ".copper")).symlink_to(family + "_0.copper")
            (logs / "bad.copper").symlink_to("../../secret")
            store.complete(run_id)
            with tempfile.TemporaryFile() as output:
                archive_into(store, run_id, output)
                output.seek(0)
                with tarfile.open(fileobj=output, mode="r:gz") as tar:
                    names = {m.name for m in tar.getmembers()}
                    self.assertNotIn(f"{run_id}/logs/bad.copper", names)
                    self.assertEqual(len(names), 7)
                    alias = tar.getmember(f"{run_id}/logs/flight_compute_sim.copper")
                    self.assertTrue(alias.issym())
                    self.assertEqual(alias.linkname, "flight_compute_sim_0.copper")

    def test_completed_manifests_restore_with_safe_ids_and_aggregate_retention(self):
        from service import RecordingStore
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "unrelated").mkdir()
            store = RecordingStore(root / "runs", max_runs=2, max_bytes=3000)
            ids = [f"20261027T00000{i}Z-1234abcd" for i in range(4)]
            for run_id in ids[:3]:
                run = store.begin(run_id)
                (run / "slab_0.copper").write_bytes(b"x" * 400)
                store.complete(run_id)
            store.prune()
            self.assertEqual([r["id"] for r in store.summaries()], list(reversed(ids[1:3])))
            active = store.begin(ids[3])
            self.assertNotIn(ids[3], [r["id"] for r in store.summaries()])
            (active / "huge.copper").write_bytes(b"x" * 3001)
            with self.assertRaisesRegex(RuntimeError, "budget"):
                store.prune(protect=ids[3])
            self.assertTrue(active.exists())
            self.assertTrue((root / "unrelated").exists())
            with self.assertRaises(ValueError):
                store.directory("../runs")
            outside = root / "outside"
            outside.mkdir()
            alias_id = "20261027T000009Z-1234abcd"
            (store.root / alias_id).symlink_to(outside, target_is_directory=True)
            with self.assertRaises((ValueError, OSError)):
                store.directory(alias_id)
            # Corrupt/deep/reserved manifests must not become completed recordings.
            manifest = active / "manifest.json"
            for payload in ['[]', '{"id":"../escape"}', '[' * 10000 + '0' + ']' * 10000]:
                manifest.write_text(payload)
                self.assertEqual(store.summaries(), [])


class SupervisorTests(unittest.TestCase):
    def fixture(self, root, body):
        script = root / "test-engine.py"
        script.write_text("import os,json,time,subprocess,sys,signal\nfrom pathlib import Path\n" +
                          "out=Path(os.environ['COPPER_FLIGHT_TELEMETRY'])\n" + body)
        return [sys.executable, str(script)]

    def test_actual_stalled_process_and_fps_only_stream_fail_and_are_killed(self):
        from service import FlightSupervisor, RecordingStore, StateStore
        for emitting in (False, True):
            with self.subTest(emitting=emitting), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                body = f"Path({str(root / 'pid')!r}).write_text(str(os.getpid()))\n"
                if emitting:
                    body += (f"f={frame()!r}\nfor i in range(300):\n f['seq']=i\n"
                             " with out.open('a') as s: s.write(json.dumps(f)+'\\n')\n time.sleep(.01)\n")
                else:
                    body += "time.sleep(30)\n"
                state, stop = StateStore(), threading.Event()
                sup = FlightSupervisor(state, RecordingStore(root / "runs"),
                                       self.fixture(root, body), stop, cwd=root,
                                       startup_timeout=.5, inactivity_timeout=.15, poll_interval=.02,
                                       terminate_grace=.1)
                worker = threading.Thread(target=sup.run)
                worker.start()
                worker.join(3)
                try:
                    self.assertFalse(worker.is_alive())
                    self.assertTrue(stop.is_set())
                    self.assertEqual(state.snapshot()["status"], "failed")
                    self.assertIn("inactivity" if emitting else "startup", state.snapshot()["error"])
                    with self.assertRaises(ProcessLookupError):
                        os.kill(int((root / "pid").read_text()), 0)
                    self.assertEqual(sup.recordings.summaries(), [])
                finally:
                    stop.set()
                    worker.join(3)

    def test_clean_native_contract_episode_requires_final_progress_and_preserves_no_replay_claim(self):
        from service import FlightSupervisor, RecordingStore, StateStore
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            final = dict(frame(1, 45), armed=True, auto_enabled=True, inference_backend="cpu",
                         policy_prediction_m_s=dict(x=0.0, y=0.0, z=0.0), policy_observation_seq=1)
            body = (f"frames={[frame(), final]!r}\n"
                    "for f in frames:\n with out.open('a') as s: s.write(json.dumps(f)+'\\n')\n time.sleep(.06)\n"
                    "assert os.environ['FLIGHT_EPISODE_SECONDS']=='45'\n"
                    "assert os.environ['FLIGHT_WORLD']=='forest'\n"
                    "assert os.environ['COPPER_FLIGHT_LOG_DIR']==str(out.parent/'logs')\n"
                    "(Path(os.environ['COPPER_FLIGHT_LOG_DIR'])/'flight_compute_sim_0.copper').write_bytes(b'test fixture')\n")
            state = StateStore()
            recordings = RecordingStore(root / "runs")
            sup = FlightSupervisor(state, recordings, self.fixture(root, body), threading.Event(),
                                   cwd=root, poll_interval=.02)
            run_id = "20261027T000000Z-1234abcd"
            sup.episode(run_id)
            snap = state.snapshot()
            self.assertEqual(snap["status"], "between_episodes")
            self.assertTrue(recordings.summaries()[0]["completed"])
            self.assertNotIn("verified", recordings.summaries()[0])
            self.assertEqual(snap["frame"]["sim_time_s"], 45)
            # Reuse the same executable with an early clean exit: cannot count as completed.
            self.fixture(root, "out.write_text(json.dumps(" + repr(frame()) + ")+ '\\n')\n")
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                sup.episode("20261027T000001Z-1234abcd")

    def test_clean_fast_exit_drains_more_than_one_telemetry_read_before_completion(self):
        from service import FlightSupervisor, RecordingStore, StateStore
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            sample = dict(frame(), armed=True, auto_enabled=True, inference_backend="cpu",
                          policy_prediction_m_s=dict(x=0.0, y=0.0, z=0.0))
            body = (f"sample={sample!r}\nrows=[]\nfor i in range(500):\n sample['seq']=i\n"
                    " sample['sim_time_s']=45*i/499\n rows.append(json.dumps(sample)+'\\n')\n"
                    "out.write_text(''.join(rows))\n")
            store, state = RecordingStore(root / "runs"), StateStore()
            sup = FlightSupervisor(state, store, self.fixture(root, body), threading.Event(), cwd=root,
                                   poll_interval=.1)
            sup.episode("20261027T000000Z-1234abcd")
            self.assertEqual(state.snapshot()["frame"]["seq"], 499)
            self.assertTrue(store.summaries()[0]["completed"])

    def test_clean_exit_without_actual_policy_output_is_not_a_completed_learned_episode(self):
        from service import FlightSupervisor, RecordingStore, StateStore
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            final = dict(frame(1, 45), armed=True, auto_enabled=True, inference_backend="cpu")
            body = f"out.write_text('\\n'.join(json.dumps(f) for f in {[frame(), final]!r})+'\\n')\n"
            store, state = RecordingStore(root / "runs"), StateStore()
            sup = FlightSupervisor(state, store, self.fixture(root, body), threading.Event(), cwd=root,
                                   poll_interval=.01)
            with self.assertRaisesRegex(RuntimeError, "policy"):
                sup.episode("20261027T000000Z-1234abcd")
            self.assertEqual(store.summaries(), [])
            self.assertEqual(state.snapshot()["status"], "failed")

    def test_wrong_backend_or_software_adapter_fail_before_exposing_live_state(self):
        from service import FlightSupervisor, RecordingStore, StateStore
        from unittest.mock import patch
        for actual in [dict(inference_backend="cuda"), dict(graphics_adapter="llvmpipe (LLVM TEST)"),
                       dict(graphics_adapter="SwiftShader TEST")]:
            with self.subTest(actual=actual), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                sample = dict(frame(1, 45), armed=True, auto_enabled=True, inference_backend="cpu",
                              policy_prediction_m_s=dict(x=1.0, y=0.0, z=0.0))
                sample.update(actual)
                body = f"out.write_text('\\n'.join(json.dumps(x) for x in {[frame(), sample]!r})+'\\n')\ntime.sleep(30)\n"
                state = StateStore()
                sup = FlightSupervisor(state, RecordingStore(root / "runs"), self.fixture(root, body),
                                       threading.Event(), cwd=root, poll_interval=.01, terminate_grace=.1,
                                       startup_timeout=.5, inactivity_timeout=.1)
                # Observe state at the teardown boundary, not only after .run catches it.
                import service
                original = service.terminate_group
                def inspect(process, grace):
                    try:
                        self.assertEqual(state.snapshot()["status"], "failed")
                        self.assertFalse(state.ready())
                    finally:
                        original(process, grace)
                with patch("service.terminate_group", side_effect=inspect), self.assertRaises(RuntimeError):
                    sup.episode("20261027T000000Z-1234abcd")

    def test_recording_growth_is_bounded_while_process_is_running(self):
        from service import FlightSupervisor, RecordingStore, StateStore
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            body = "(out.parent/'camera_0.copper').write_bytes(b'x'*5000)\ntime.sleep(30)\n"
            state, stop = StateStore(), threading.Event()
            sup = FlightSupervisor(state, RecordingStore(root / "runs", max_bytes=2000),
                                   self.fixture(root, body), stop, cwd=root,
                                   startup_timeout=2, poll_interval=.02, terminate_grace=.1)
            sup.run()
            self.assertIn("budget", state.snapshot()["error"])
            self.assertFalse(state.ready())


class HttpTests(unittest.TestCase):
    def test_read_only_http_downloads_confined_full_slab_family_without_replay_badge(self):
        import io
        import tarfile
        import urllib.error
        import urllib.request
        from service import make_server, StateStore, RecordingStore
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            state, store = StateStore(), RecordingStore(root / "runs")
            run_id = "20261027T000000Z-1234abcd"
            run = store.begin(run_id)
            for name in ["flight_compute_sim_0.copper", "flight_compute_sim_1.copper",
                         "flight_controller_sim_0.copper", "flight_controller_sim_1.copper"]:
                (run / name).write_bytes(b"test fixture binary slab")
            (run / "flight_compute_sim.copper").symlink_to("flight_compute_sim_0.copper")
            (run / "absolute.copper").symlink_to(root / "secret")
            (root / "secret").write_text("secret")
            (run / "hardlink.copper").hardlink_to(root / "secret")
            os.mkfifo(run / "fifo.copper")
            (run / "nested.copper").mkdir()
            store.complete(run_id)
            (root / "index.html").write_text("flight dashboard")
            (root / "app.js").symlink_to(root / "secret")
            server = make_server(state, store, root, host="127.0.0.1", port=0)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urllib.request.urlopen(base + "/api/state") as response:
                    self.assertEqual(json.load(response)["status"], "starting")
                    self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                for path, expected in [("/healthz", 503), ("/../service.py", 404),
                                       ("/api/recordings/..%2Fbad/download", 400), ("/app.js", 400)]:
                    with self.subTest(path=path), self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(base + path)
                    self.assertEqual(caught.exception.code, expected)
                    caught.exception.close()
                for method in ["POST", "PUT", "DELETE", "PATCH"]:
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(urllib.request.Request(base + "/api/state", method=method))
                    self.assertEqual(caught.exception.code, 405)
                    caught.exception.close()
                with urllib.request.urlopen(base + f"/api/recordings/{run_id}/download") as response:
                    archive = response.read()
                with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
                    names = {m.name for m in tar.getmembers()}
                    self.assertEqual(names, {f"{run_id}/{name}" for name in ["manifest.json",
                        "flight_compute_sim.copper", "flight_compute_sim_0.copper", "flight_compute_sim_1.copper",
                        "flight_controller_sim_0.copper", "flight_controller_sim_1.copper"]})
                    self.assertEqual(tar.getmember(f"{run_id}/flight_compute_sim.copper").linkname,
                                     "flight_compute_sim_0.copper")
            finally:
                server.shutdown()
                server.server_close()
                worker.join()

    def test_packaged_static_inventory_is_finite_and_nested_paths_cannot_follow_symlinks(self):
        import urllib.error
        import urllib.request
        from service import make_server, RecordingStore, StateStore
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            web = root / "www"
            (web / "vendor").mkdir(parents=True)
            (web / "assets/fonts").mkdir(parents=True)
            for name in ["index.html", "styles.css", "state.js", "format.js", "transport.js", "monitor.js",
                         "vendor/three.module.js", "assets/fonts/test.woff2"]:
                (web / name).write_text("TEST packaged artifact " + name)
            (web / "private.txt").write_text("private")
            (web / "leak").symlink_to(root, target_is_directory=True)
            server = make_server(StateStore(), RecordingStore(root / "runs"), web, "127.0.0.1", 0)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                for name in ["styles.css", "state.js", "format.js", "transport.js", "monitor.js",
                             "vendor/three.module.js", "assets/fonts/test.woff2"]:
                    with urllib.request.urlopen(base + "/" + name) as response:
                        self.assertIn(b"TEST packaged artifact", response.read())
                        self.assertNotIn("unsafe-inline", response.headers["Content-Security-Policy"])
                        self.assertIn("img-src 'self' blob:", response.headers["Content-Security-Policy"])
                        self.assertIn("script-src 'self';", response.headers["Content-Security-Policy"])
                # New files aren't part of the fixed startup inventory.
                (web / "after-start.js").write_text("not packaged at startup")
                for name in ["private.txt", "after-start.js", "leak/private.txt", "../service.py"]:
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(base + "/" + name)
                    self.assertEqual(caught.exception.code, 404)
                    caught.exception.close()
                (web / "vendor/three.module.js").unlink()
                (web / "vendor/three.module.js").symlink_to(web / "private.txt")
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(base + "/vendor/three.module.js")
                self.assertEqual(caught.exception.code, 400)
                caught.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                worker.join()

    def test_scene_asset_whitelist_streams_regular_files_and_never_exposes_other_paths(self):
        import http.client
        from unittest.mock import patch
        from service import make_server, RecordingStore, StateStore, validate_frame
        native = dict(frame(), rotation=dict(x=0.0, y=0.0, z=0.0, w=1.0))
        self.assertEqual(validate_frame(json.dumps(native))["rotation"], native["rotation"])
        for rotation in [dict(x=0, y=0, z=0), dict(x=0, y=0, z=0, w=float("inf")), "bad"]:
            with self.assertRaises(ValueError):
                validate_frame(json.dumps(dict(frame(), rotation=rotation)))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            assets = root / "assets"
            assets.mkdir()
            (assets / "forest.glb").write_bytes(b"TESTglb\x00not-a-real-scene")
            (assets / "quadcopter.glb").write_bytes(b"TESTquad")
            (assets / "private.glb").write_text("private")
            server = make_server(StateStore(), RecordingStore(root / "runs"), root,
                                 "127.0.0.1", 0, asset_root=assets, socket_timeout=.2)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            def request(path):
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                try:
                    conn.request("GET", path)
                    response = conn.getresponse()
                    return response.status, response.getheader("Content-Type"), response.read()
                finally:
                    conn.close()
            try:
                self.assertEqual(request("/api/scene/forest.glb"),
                                 (200, "model/gltf-binary", (assets / "forest.glb").read_bytes()))
                self.assertEqual(request("/api/scene/quadcopter.glb")[2], b"TESTquad")
                for path in ["/api/scene/private.glb", "/api/scene/../private.glb",
                             "/api/scene/%2e%2e/private.glb", "/api/scene/%66orest.glb"]:
                    self.assertEqual(request(path)[0], 404)
                (assets / "quadcopter.glb").unlink()
                (assets / "quadcopter.glb").symlink_to(assets / "private.glb")
                self.assertEqual(request("/api/scene/quadcopter.glb")[0], 400)
                (assets / "quadcopter.glb").unlink()
                os.mkfifo(assets / "quadcopter.glb")
                self.assertEqual(request("/api/scene/quadcopter.glb")[0], 400)
                # A mid-stream disk failure must close, not append JSON/second HTTP headers.
                with patch("service.stream_file", side_effect=OSError("TEST read failure")):
                    with self.assertRaises(http.client.IncompleteRead):
                        request("/api/scene/forest.glb")
            finally:
                server.shutdown()
                server.server_close()
                worker.join()

    def test_stalled_download_does_not_hold_retention_lock_and_socket_times_out(self):
        import socket
        from service import make_server, StateStore, RecordingStore
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            store = RecordingStore(root / "runs")
            run_id = "20261027T000000Z-1234abcd"
            run = store.begin(run_id)
            (run / "camera_0.copper").write_bytes(os.urandom(6 * 1024**2))
            store.complete(run_id)
            server = make_server(StateStore(), store, root, "127.0.0.1", 0, socket_timeout=.25)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            client = socket.socket()
            client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
            client.settimeout(3)
            try:
                client.connect(("127.0.0.1", server.server_port))
                client.sendall(f"GET /api/recordings/{run_id}/download HTTP/1.0\r\n\r\n".encode())
                headers = b""
                while not headers.endswith(b"\r\n\r\n"):
                    chunk = client.recv(1)
                    self.assertTrue(chunk, "server disconnected before headers")
                    headers += chunk
                self.assertIn(b"200 OK", headers)
                acquired = store.lock.acquire(timeout=.2)
                if acquired:
                    store.lock.release()
                self.assertTrue(acquired, "socket blocked retention")
                self.assertTrue(store.download_slot.acquire(timeout=2), "download did not time out")
                store.download_slot.release()
            finally:
                client.close()
                server.shutdown()
                server.server_close()
                worker.join()


class ProcessGroupTests(unittest.TestCase):
    def test_descendant_ignoring_term_is_killed_even_after_leader_already_exited(self):
        import subprocess
        from service import terminate_group
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            pidfile = root / "test-descendant.pid"
            child = ("import os,pathlib,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                     f"pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid())); time.sleep(30)")
            leader = ("import pathlib,subprocess,sys,time; "
                      f"subprocess.Popen([sys.executable,'-c',{child!r}]); "
                      f"p=pathlib.Path({str(pidfile)!r})\nwhile not p.exists(): time.sleep(.01)\n")
            process = subprocess.Popen([sys.executable, "-c", leader], start_new_session=True,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                process.wait(timeout=3)
                pid = int(pidfile.read_text())
                terminate_group(process, grace=.1)
                status = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
                if status.returncode == 0:
                    self.assertTrue(status.stdout.strip().startswith("Z"),
                                    "descendant still running after group TERM/KILL: " + status.stdout)
            finally:
                terminate_group(process, grace=.1)


class EntrypointTests(unittest.TestCase):
    def test_service_process_exits_nonzero_after_watchdog_instead_of_just_serving_http(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            launcher = root / "stall"
            launcher.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
            launcher.chmod(0o755)
            env = dict(os.environ, FLIGHT_DATA_DIR=str(root), COPPER_FLIGHT_LAUNCHER=str(launcher),
                       FLIGHT_STARTUP_TIMEOUT_SECONDS=".2", FLIGHT_INACTIVITY_TIMEOUT_SECONDS=".1", PORT="0")
            result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "service.py")],
                                    env=env, capture_output=True, text=True, timeout=8)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("startup deadline", result.stderr)
            self.assertIn("listening", result.stdout)

    def test_configuration_rejects_nonfinite_and_out_of_bound_watchdogs(self):
        from service import configuration
        for key, value in [("FLIGHT_STARTUP_TIMEOUT_SECONDS", "301"),
                           ("FLIGHT_INACTIVITY_TIMEOUT_SECONDS", "31"),
                           ("FLIGHT_STARTUP_TIMEOUT_SECONDS", "nan"), ("FLIGHT_EPISODE_SECONDS", "4"),
                           ("FLIGHT_WORLD", "../forest"), ("FLIGHT_INFERENCE", "auto")]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                configuration({key: value})


if __name__ == "__main__":
    unittest.main()
