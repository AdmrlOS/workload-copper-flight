"""Synthetic test inputs only; production endpoints expose actual native frames."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock
from contextlib import contextmanager
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_service import frame

RUN = '20261027T000000Z-1234abcd'
OTHER = '20261027T000001Z-1234abcd'


@contextmanager
def http_fixture(state=None):
    from service import StateStore, RecordingStore, make_server
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        web = root / 'www'; web.mkdir()
        store = RecordingStore(root / 'runs')
        server = make_server(state or StateStore(), store, web, host='127.0.0.1', port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_address[1]}', store, root
        finally:
            server.shutdown(); server.server_close(); thread.join(2)


class PlaybackTests(unittest.TestCase):
    def test_supervisor_records_original_provenance_not_current_playback_host(self):
        from service import StateStore, RecordingStore, FlightSupervisor, completed_telemetry
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            store = RecordingStore(root / 'runs')
            state = StateStore(revision='recording-image-fixture', inference='cpu', episode_seconds=.2)
            samples = [dict(frame(seq, seq / 10), inference_backend='cpu', armed=True,
                            auto_enabled=True, policy_prediction_m_s=dict(x=1, y=0, z=0)) for seq in range(3)]
            payload = ''.join(json.dumps(sample) + '\n' for sample in samples)
            script = "import os,pathlib; pathlib.Path(os.environ['COPPER_FLIGHT_TELEMETRY']).write_text(" + repr(payload) + ")"
            supervisor = FlightSupervisor(state, store, [sys.executable, '-c', script], threading.Event(),
                                          cwd=root, poll_interval=.01, terminate_grace=.01)
            supervisor.episode(RUN)
            result = completed_telemetry(store, RUN)
            self.assertEqual(result['provenance']['recording_id'], RUN)
            self.assertEqual(result['provenance']['engine']['revision'], 'recording-image-fixture')
            self.assertEqual(result['provenance']['configuration']['inference'], 'cpu')
            self.assertFalse(result['provenance']['native_replay_verified'])
            self.assertFalse(result['native_replay_verified'])

    def test_only_valid_complete_native_telemetry_is_exposed_without_current_revision_fabrication(self):
        from service import StateStore
        with http_fixture(StateStore(revision='not-the-recording-revision')) as (url, store, root):
            run = store.begin(RUN)
            payload = ''.join(json.dumps(frame(seq, seq / 30)) + '\n' for seq in range(3)).encode()
            (run / 'telemetry.jsonl').write_bytes(payload)
            endpoint = url + f'/api/recordings/{RUN}/telemetry'
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(endpoint)
            self.assertEqual(error.exception.code, 409)
            store.complete(RUN)
            result = json.load(urllib.request.urlopen(endpoint))
            self.assertEqual(result['schema_version'], 1)
            self.assertEqual(result['recording']['id'], RUN)
            self.assertTrue(result['recording']['completed'])
            self.assertIsNone(result['provenance'])
            self.assertNotIn('not-the-recording-revision', json.dumps(result))
            self.assertFalse(result['native_replay_verified'])
            self.assertEqual([f['seq'] for f in result['frames']], [0, 1, 2])
            self.assertTrue(all(f['inference_count'] is None for f in result['frames']))
            self.assertEqual((run / 'telemetry.jsonl').read_bytes(), payload)
            for invalid in [payload[:-1], b'{}\n', payload + payload, b'', b'x' * 65537 + b'\n']:
                (run / 'telemetry.jsonl').write_bytes(invalid)
                with self.subTest(invalid_length=len(invalid)), self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(endpoint)
                self.assertEqual(error.exception.code, 400)
            (run / 'telemetry.jsonl').unlink()
            (root / 'outside').write_bytes(payload)
            (run / 'telemetry.jsonl').symlink_to(root / 'outside')
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(endpoint)
            self.assertEqual(error.exception.code, 400)
            self.assertEqual((root / 'outside').read_bytes(), payload)


class LiveBatchTests(unittest.TestCase):
    def test_http_cursor_contract_is_read_only_and_rejects_ambiguous_parameters(self):
        from service import StateStore
        state = StateStore(revision='synthetic-test-fixture')
        state.begin(RUN)
        state.publish(frame())
        state.publish(frame(1, .1))
        with http_fixture(state) as (url, _, _):
            initial = json.load(urllib.request.urlopen(url + '/api/telemetry'))
            self.assertEqual([f['seq'] for f in initial['frames']], [0, 1])
            self.assertEqual(initial['engine']['revision'], 'synthetic-test-fixture')
            latest = json.load(urllib.request.urlopen(url + f'/api/telemetry?after_seq=0&episode_id={RUN}'))
            self.assertEqual([f['seq'] for f in latest['frames']], [1])
            self.assertFalse(latest['reset'])
            for query in ['after_seq=-1', 'after_seq=true', 'after_seq=1.0', 'after_seq=99999999999999999999',
                          f'after_seq=0&after_seq=1&episode_id={RUN}', f'episode_id={RUN}',
                          'after_seq=0&episode_id=../escape', f'after_seq=0&episode_id={RUN}&extra=1']:
                with self.subTest(query=query), self.assertRaises(urllib.error.HTTPError) as result:
                    urllib.request.urlopen(url + '/api/telemetry?' + query)
                self.assertEqual(result.exception.code, 400)
            with self.assertRaises(urllib.error.HTTPError) as result:
                urllib.request.urlopen(urllib.request.Request(url + '/api/telemetry', method='POST'))
            self.assertEqual(result.exception.code, 405)

    def test_cursor_returns_every_buffered_observation_without_inventing_samples(self):
        from service import StateStore
        state = StateStore(revision='test-fixture', history_limit=3)
        state.begin(RUN)
        for seq in range(5):
            state.publish(frame(seq, seq / 30))
        batch = state.telemetry_snapshot(after_seq=2, episode_id=RUN)
        self.assertEqual(batch['schema_version'], 1)
        self.assertEqual([f['seq'] for f in batch['frames']], [3, 4])
        self.assertEqual(batch['oldest_seq'], 2)
        self.assertEqual(batch['latest_seq'], 4)
        self.assertFalse(batch['reset'])
        self.assertIsNone(batch['frames'][0]['inference_count'])
        self.assertEqual(state.telemetry_snapshot(after_seq=4, episode_id=RUN)['frames'], [])
        batch['frames'][0]['seq'] = 999
        self.assertEqual(state.telemetry_snapshot(after_seq=2, episode_id=RUN)['frames'][0]['seq'], 3)
        for cursor, episode in [(0, RUN), (10, RUN), (2, OTHER), (None, None)]:
            reset = state.telemetry_snapshot(after_seq=cursor, episode_id=episode)
            self.assertTrue(reset['reset'])
            self.assertEqual([f['seq'] for f in reset['frames']], [2, 3, 4])
        state.begin(OTHER)
        empty = state.telemetry_snapshot(after_seq=4, episode_id=RUN)
        self.assertEqual(empty['frames'], [])
        self.assertIsNone(empty['latest_seq'])
        self.assertEqual(empty['episode']['id'], OTHER)
