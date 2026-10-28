"""Synthetic contract/security tests, not native execution evidence."""
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import urlopen
from urllib.error import HTTPError
from urllib.request import Request
import gzip

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import service
from test_service import frame

ROOT = Path(__file__).resolve().parents[1]
RUN = '20261027T000000Z-1234abcd'
OTHER = '20261027T000001Z-1234abcd'


def raster(seq=7):
    return dict(service.DEPTH_CONSTANTS, width=320, height=240, sampling='identity',
                source_seq=seq, sample_wall_time_s=2, sample_sim_time_s=1,
                range_m=[.001, 20], data=bytes(range(256)).hex() * 300)


def event(value=None):
    return dict(schema_version=1, kind='depth-raster', depth_raster=value or raster())


def descriptor(value=None):
    return {k: v for k, v in (value or raster()).items() if k != 'data'}


def rows(*values):
    return b''.join(json.dumps(v).encode() + b'\n' for v in values)


class DepthFullresTests(unittest.TestCase):
    def test_cached_run_sequence_binding_cannot_be_replaced_with_different_pixels(self):
        state = service.StateStore()
        state.begin(RUN)
        state.publish(event())
        state.publish(event())
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            state.publish(event(dict(raster(), data='ff' * 76800)))
        self.assertEqual(state.depth_raster(RUN, 7), raster())
        self.assertIsNone(state.depth_raster(OTHER, 7))

    def test_pinned_scan_survives_retention_without_holding_the_recording_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = service.RecordingStore(Path(tmp).resolve() / 'runs')
            run = store.begin(RUN)
            (run / 'telemetry.jsonl').write_bytes(rows(event(), frame()))
            store.complete(RUN)
            validate = service.validate_native_record
            first = True
            def remove_after_pin(payload):
                nonlocal first
                if first:
                    first = False
                    acquired = []
                    def probe():
                        acquired.append(store.lock.acquire(blocking=False))
                        if acquired[-1]:
                            store.lock.release()
                    worker = threading.Thread(target=probe); worker.start(); worker.join()
                    self.assertEqual(acquired, [True])
                    (run / 'telemetry.jsonl').unlink()
                return validate(payload)
            with patch.object(service, 'validate_native_record', side_effect=remove_after_pin):
                self.assertEqual(service.recorded_depth_raster(store, RUN, 7), raster())

    def test_sensor_events_only_cannot_satisfy_actual_supervisor_startup_or_terminal_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            script = root / 'test-engine.py'
            script.write_text("import os,json,time\nfrom pathlib import Path\n" +
                              f"value={event()!r}\n" +
                              "out=Path(os.environ['COPPER_FLIGHT_TELEMETRY'])\n" +
                              "for i in range(100):\n value['depth_raster']['source_seq']=i\n" +
                              " with out.open('a') as stream: stream.write(json.dumps(value)+'\\n')\n time.sleep(.01)\n")
            store = service.RecordingStore(root / 'runs')
            state = service.StateStore()
            supervisor = service.FlightSupervisor(state, store, [sys.executable, str(script)], threading.Event(),
                                                   cwd=root, startup_timeout=.15, poll_interval=.01, terminate_grace=.01)
            with self.assertRaisesRegex(TimeoutError, 'startup'):
                supervisor.episode(RUN)
            self.assertIsNone(state.updated); self.assertIsNone(state.progress_at)
            self.assertEqual(state.snapshot()['status'], 'failed')
            self.assertEqual(state.telemetry_snapshot()['frames'], [])
            self.assertFalse(state.ready())

    def test_full_raster_http_security_limits_and_gzip_negotiation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = service.RecordingStore(Path(tmp).resolve() / 'runs')
            run = store.begin(RUN)
            telemetry = run / 'telemetry.jsonl'
            good = rows(event(), dict(frame(), wall_time_s=3, sim_time_s=2, depth_raster=descriptor()))
            telemetry.write_bytes(good)
            store.complete(RUN)
            state = service.StateStore()
            server = service.make_server(state, store, ROOT / 'www', host='127.0.0.1', port=0)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f'http://127.0.0.1:{server.server_port}'
            path = f'/api/recordings/{RUN}/depth/7'
            def status(target, expected):
                with self.assertRaises(HTTPError) as caught:
                    urlopen(base + target)
                self.assertEqual(caught.exception.code, expected, target)
            try:
                for header, compressed in [('gzip', True), ('br, gzip;q=0.5', True),
                                           ('gzip;q=0', False), ('gzip;q=0, *;q=1', False),
                                           ('xgzip', False), ('gzip;q=wat', False), ('*', False)]:
                    with urlopen(Request(base + path, headers={'Accept-Encoding': header})) as response:
                        body = response.read()
                        self.assertEqual(response.headers.get('Content-Encoding'), 'gzip' if compressed else None)
                        self.assertEqual(json.loads(gzip.decompress(body) if compressed else body), raster())
                        self.assertEqual(response.headers.get('Vary'), 'Accept-Encoding')
                with urlopen(Request(base + '/api/state', headers={'Accept-Encoding': 'gzip'})) as response:
                    self.assertIsNone(response.headers.get('Content-Encoding'))
                for suffix in ['-1', '01', '9007199254740992', 'true', '7/extra', '7?x=1', '%37']:
                    status(f'/api/recordings/{RUN}/depth/{suffix}', 400)
                for target in [f'/api/recordings/%2e%2e/depth/7', f'/api/recordings/{RUN}%2f../depth/7',
                               f'/api/recordings/%32{RUN[1:]}/depth/7']:
                    status(target, 400)
                store.playback_slot.acquire(); store.playback_slot.acquire()
                try:
                    status(path, 429)
                finally:
                    store.playback_slot.release(); store.playback_slot.release()
                for bad in [rows(event(dict(raster(), data='ff'))), rows(event(dict(raster(), width=32))),
                            rows(dict(event(), seq=0)), good[:-1], b'x' * (service.MAX_NATIVE_EVENT + 1),
                            rows(event(dict(raster(), sample_wall_time_s=float('nan'))))]:
                    telemetry.write_bytes(bad)
                    status(path, 400)
                with telemetry.open('wb') as stream:
                    stream.truncate(service.MAX_PLAYBACK_BYTES + 1)
                status(path, 413)
                telemetry.unlink()
                outside = Path(tmp) / 'outside'
                outside.write_bytes(good)
                telemetry.symlink_to(outside)
                status(path, 400)
                telemetry.unlink()
                os.link(outside, telemetry)
                status(path, 400)
                telemetry.unlink()
                telemetry.write_bytes(good)
                alias = store.root / OTHER
                alias.symlink_to(run, target_is_directory=True)
                status(f'/api/recordings/{OTHER}/depth/7', 400)
                self.assertEqual(sorted(p.name for p in run.iterdir()), ['logs', 'manifest.json', 'telemetry.jsonl'])
            finally:
                server.shutdown(); server.server_close(); worker.join()

    def test_full_metadata_validation_and_pose_descriptor_allowlisting(self):
        for changes in [dict(width=True), dict(height=24), dict(sampling='nearest-cell-center'),
                        dict(data='ff' * 76799), dict(data='FF' * 76800), dict(data='zz' * 76800),
                        dict(source_seq=2**53), dict(source_seq=True), dict(source_seq=-1),
                        dict(sample_wall_time_s=-1), dict(sample_sim_time_s=float('inf')),
                        dict(range_m=[True, 20]), dict(invalid_rule='wrong'), dict(source_units='metres')]:
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                service.validate_native_record(json.dumps(event(dict(raster(), **changes))))
        pose = dict(frame(), wall_time_s=3, sim_time_s=2, depth_raster=descriptor())
        for changes in [dict(sample_wall_time_s=4), dict(sample_sim_time_s=3), dict(data=raster()['data'])]:
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                service.validate_frame(json.dumps(dict(pose, depth_raster=dict(descriptor(), **changes))))
        pose['depth_raster']['ignored'] = '<script>'
        self.assertNotIn('ignored', service.normalize_frame(pose)['depth_raster'])
        for raw in [b'{"kind":"depth-raster","kind":"depth-raster"}',
                    rows(event(dict(raster(), ignored='x' * service.MAX_NATIVE_EVENT)))]:
            with self.assertRaises(ValueError):
                service.validate_native_record(raw)

    def test_exact_http_live_and_completed_rasters_do_not_enter_recorded_poses(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = service.RecordingStore(Path(tmp).resolve() / 'runs')
            run = store.begin(RUN)
            pose = dict(frame(), wall_time_s=3, sim_time_s=2, depth_raster=descriptor())
            (run / 'telemetry.jsonl').write_bytes(rows(event(), pose))
            state = service.StateStore()
            state.begin(RUN)
            server = service.make_server(state, store, ROOT / 'www', host='127.0.0.1', port=0)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                with urlopen(f'{base}/api/recordings/{RUN}/depth/7') as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.load(response), raster())
                store.complete(RUN)
                bundle = service.completed_telemetry(store, RUN)
                self.assertEqual(len(bundle['frames']), 1)
                self.assertEqual(bundle['frames'][0]['depth_raster'], descriptor())
                self.assertNotIn('data', bundle['frames'][0]['depth_raster'])
                self.assertFalse(bundle['native_replay_verified'])
                for path in [f'{RUN}/depth/8', f'{OTHER}/depth/7']:
                    with self.assertRaises(HTTPError) as caught:
                        urlopen(f'{base}/api/recordings/{path}')
                    self.assertEqual(caught.exception.code, 404)
                # Pinned scan must remain available after the bounded live cache evicts.
                state.publish(event())
                for seq in range(8, 8 + service.MAX_DEPTH_CACHE):
                    state.publish(event(raster(seq)))
                self.assertIsNone(state.depth_raster(RUN, 7))
                with urlopen(f'{base}/api/recordings/{RUN}/depth/7') as response:
                    self.assertEqual(json.load(response), raster())
            finally:
                server.shutdown()
                server.server_close()
                worker.join()

    def test_events_are_bounded_separate_from_pose_sequence_history_and_progress(self):
        pose = dict(frame(), wall_time_s=3, sim_time_s=2, depth_raster=descriptor())
        reader = service.TelemetryReader(io.BytesIO(rows(event(), pose)))
        observed = []
        while reader.offset < len(reader.stream.getvalue()):
            observed.extend(reader.poll())
        self.assertEqual(observed, [event(), pose])
        self.assertEqual(reader.last, pose)
        state = service.StateStore()
        state.begin(RUN)
        state.publish(observed[0])
        self.assertIsNone(state.updated)
        self.assertIsNone(state.progress_at)
        self.assertFalse(state.ready())
        self.assertEqual(state.telemetry_snapshot()['frames'], [])
        self.assertIsNone(state.snapshot()['frame'])
        self.assertEqual(state.depth_raster(RUN, 7), raster())
        state.publish(observed[1])
        self.assertEqual(len(state.telemetry_snapshot()['frames']), 1)
        self.assertNotIn('data', state.snapshot()['frame']['depth_raster'])
        self.assertFalse(state.ready())
        self.assertEqual(service.MAX_JSON, 65536)
        self.assertEqual(service.MAX_NATIVE_EVENT, 192 * 1024)
        with self.assertRaises(ValueError):
            service.validate_frame(json.dumps(dict(pose, extra='x' * 65536)))
        state.begin(OTHER)
        self.assertIsNone(state.depth_raster(RUN, 7))
