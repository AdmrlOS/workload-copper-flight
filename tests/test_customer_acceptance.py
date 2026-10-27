"""Synthetic fixtures for the customer release evidence gate, never demo data."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location('customer_check', ROOT / 'scripts/check_customer_readiness.py')
    assert spec is not None and spec.loader is not None
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def frames(rate=1.1):
    return [dict(seq=n, sim_time_s=n / 64, wall_time_s=n / 64 / rate,
                 inference_backend='cuda', policy_observation_seq=n + 1,
                 position_m=dict(x=n / 64, y=2, z=0),
                 depth_preview=dict(source_seq=n // 32, data=('01' if n < 32 else '02') * 768))
            for n in range(129)]


class CustomerAcceptanceTests(unittest.TestCase):
    def test_actual_source_clock_not_receipt_or_render_clock_sets_rate(self):
        report = module().analyze_frames({'mission': frames()})
        self.assertTrue(report['passed'])
        self.assertAlmostEqual(report['simulation_realtime_factor'], 1.1)
        self.assertAlmostEqual(report['observed_source_hz'], 70.4)
        self.assertFalse(report['native_replay_verified'])

    def test_subrealtime_does_not_become_customer_ready(self):
        report = module().analyze_frames({'mission': frames(.8)})
        self.assertFalse(report['passed'])
        self.assertIn('simulation_realtime_factor', report['failed_gates'])

    def test_reset_episodes_never_make_a_cross_episode_rate(self):
        report = module().analyze_frames({'first': frames(), 'second': frames()})
        self.assertEqual(report['episodes'], 2)
        self.assertAlmostEqual(report['simulation_realtime_factor'], 1.1)
        self.assertEqual(report['actual_unique_samples'], 258)

    def test_missing_depth_or_policy_and_nonfinite_time_fail_closed(self):
        check = module()
        for field in ['depth_preview', 'policy_observation_seq']:
            rows = frames()
            for row in rows:
                row.pop(field)
            self.assertFalse(check.analyze_frames({'mission': rows})['passed'])
        rows = frames()
        rows[50]['wall_time_s'] = float('nan')
        self.assertFalse(check.analyze_frames({'mission': rows})['passed'])


if __name__ == '__main__':
    unittest.main()
