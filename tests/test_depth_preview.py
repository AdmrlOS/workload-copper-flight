"""Depth boundary tests using the saved, real software-native observation."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import validate_frame, normalize_frame, StateStore, RecordingStore, completed_telemetry

ROOT = Path(__file__).resolve().parents[1]
RUN = '20261027T000000Z-1234abcd'
TRACE = ROOT / 'tests/fixtures/native-depth-observations.jsonl'


class DepthContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = [json.loads(line) for line in TRACE.read_bytes().splitlines()]
        cls.sample = next(row for row in cls.rows if 'depth_preview' in row)

    def test_invalid_optional_native_preview_is_rejected_before_publication(self):
        mutations = [dict(width=1000000), dict(height=True), dict(data='aa' * 100000),
                     dict(data='<script>' * 192), dict(data='00' * 768), dict(data='ff'),
                     dict(source='<img src=x onerror=alert(1)>'), dict(source_seq=-1),
                     dict(source_seq=2**53), dict(source_seq=True), dict(invalid_u8=1),
                     dict(range_m=[0, 100]), dict(encoding='base64'),
                     dict(sample_wall_time_s=self.sample['wall_time_s'] + 1),
                     dict(sample_sim_time_s=-1), dict(source_units='metres')]
        for changes in mutations:
            bad = copy.deepcopy(self.sample)
            bad['depth_preview'].update(changes)
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                validate_frame(json.dumps(bad).encode())

    def test_real_native_preview_roundtrips_live_and_completed_without_adding_timestamp(self):
        state = StateStore()
        state.begin(RUN)
        for row in self.rows:
            state.publish(validate_frame(json.dumps(row).encode()))
        self.assertEqual(state.snapshot()['frame']['depth_preview'], self.rows[-1]['depth_preview'])
        self.assertIsNone(state.snapshot()['frame']['inference_count'])
        self.assertNotIn('depth_preview', normalize_frame(self.rows[0]))
        with tempfile.TemporaryDirectory() as tmp:
            store = RecordingStore(Path(tmp).resolve() / 'runs')
            run = store.begin(RUN)
            (run / 'telemetry.jsonl').write_bytes(TRACE.read_bytes())
            store.complete(RUN)
            result = completed_telemetry(store, RUN)
            self.assertEqual([r.get('depth_preview') for r in result['frames']],
                             [r.get('depth_preview') for r in self.rows])
            self.assertFalse(result['native_replay_verified'])

    def test_normalizer_allowlists_preview_and_does_not_forward_unknown_native_fields(self):
        row = copy.deepcopy(self.sample)
        row['depth_preview']['acquisition_timestamp'] = '<script>bad</script>'
        self.assertNotIn('acquisition_timestamp', normalize_frame(row)['depth_preview'])
        row['depth_preview']['width'] = 1000000
        self.assertNotIn('depth_preview', normalize_frame(row))
