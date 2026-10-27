"""Test-only synthetic hardware/clock fixtures; never runtime demo data."""
import copy
import unittest
from unittest.mock import patch

from test_customer_acceptance import module
from test_acceptance import state

REVISION = 'a' * 40


class Clock:
    now = 0.0

    def sleep(self, seconds):
        self.now += seconds


def observe_fixture(mode):
    check, clock = module(), Clock()

    def read(origin, path):
        tick = round(clock.now * 64)
        s = state()
        s['engine'].update(native=True, revision=REVISION)
        s['configuration']['inference'] = 'cuda'
        s['frame'].update(seq=tick, sim_time_s=5 + tick / 64,
                          policy_observation_seq=tick + 1, inference_backend='cuda',
                          graphics=dict(backend='Vulkan', adapter_name='NVIDIA test fixture',
                                        vendor_id=0x10de, device_type='DiscreteGpu'))
        if mode == 'churn':
            s['episode']['id'] = str(int(clock.now / 2))
        if mode == 'transition' and 1 <= clock.now < 1.4:
            s['status'] = 'between_episodes'
        if mode == 'transition' and clock.now >= 1.4:
            s['episode']['id'] = 'next'
        if clock.now >= 6.2:
            if mode in ('failed', 'stopped', 'starting', 'between_episodes'):
                s['status'] = mode
            if mode == 'manual':
                s['frame']['auto_enabled'] = False
            if mode == 'stale':
                s['frame_age_s'] = 10
            if mode == 'policy_frozen':
                s['frame']['policy_observation_seq'] = 390
        if path.startswith('/api/state'):
            return s
        rows = []
        for seq in range(max(0, tick - 12), tick + 1):
            row = copy.deepcopy(s['frame'])
            row.update(seq=seq, sim_time_s=5 + seq / 64, wall_time_s=seq / 64,
                       depth_preview=dict(source_seq=seq, data=('01' if seq % 2 else '02') * 768))
            rows.append(row)
        if clock.now >= 6.2 and mode in ('failed', 'stopped', 'empty'):
            rows = []
        return dict(engine=s['engine'], episode=s['episode'], status=s['status'],
                    frames=rows, frame_age_s=s['frame_age_s'])

    with patch.object(check.time, 'monotonic', side_effect=lambda: clock.now), \
            patch.object(check.time, 'sleep', side_effect=clock.sleep), \
            patch.object(check, 'read_json', side_effect=read):
        return check.observe('http://localhost', REVISION, seconds=10)


def observe_lifecycle(seconds=10, episode_sim_seconds=45.0, mode='healthy',
                      cold_delay_s=0.0, **observe_kwargs):
    """Exercise actual observe with test-only 1.1x, 64 samples/sim-second frames."""
    check, clock = module(), Clock()
    cursors = {}

    def read(origin, path):
        if mode == 'initial_http_error' and clock.now < 4:
            raise OSError('test-only initial transport failure')
        simulation = max(0.0, clock.now - cold_delay_s) * 1.1
        episode = str(int(simulation / episode_sim_seconds))
        phase = simulation % episode_sim_seconds
        tick = int(phase * 64)
        s = state()
        s['engine'].update(native=True, revision=REVISION)
        s['episode']['id'] = episode
        s['configuration']['inference'] = 'cuda'
        armed = phase >= 4 and mode != 'never_arms'
        if mode == 'late_arms':
            armed = phase >= 7
        if mode == 'manual' and clock.now >= 6.2:
            armed = False
        s['frame'].update(seq=tick, sim_time_s=tick / 64,
                          armed=armed, auto_enabled=armed,
                          inference_count=None, policy_observation_seq=tick + 1,
                          inference_backend='cuda',
                          graphics=dict(backend='Vulkan', adapter_name='NVIDIA test fixture',
                                        vendor_id=0x10de, device_type='DiscreteGpu'))
        if mode == 'startup_frozen' and clock.now < 7:
            s['frame'].update(sim_time_s=min(phase, 3), armed=False, auto_enabled=False)
        if mode == 'never_advances' or (mode == 'terminal_unarmed' and clock.now >= seconds - 1):
            s['frame'].update(sim_time_s=0, armed=False, auto_enabled=False)
        if path.startswith('/api/state'):
            return s
        rows = []
        for seq in range(cursors.get(episode, -1) + 1, tick + 1):
            row = copy.deepcopy(s['frame'])
            row.update(seq=seq, sim_time_s=seq / 64, wall_time_s=seq / 70.4,
                       depth_preview=dict(source_seq=seq, data=('01' if seq % 2 else '02') * 768))
            rows.append(row)
        cursors[episode] = tick
        return dict(engine=s['engine'], episode=s['episode'], status=s['status'],
                    frames=rows, frame_age_s=s['frame_age_s'])

    with patch.object(check.time, 'monotonic', side_effect=lambda: clock.now), \
            patch.object(check.time, 'sleep', side_effect=clock.sleep), \
            patch.object(check, 'read_json', side_effect=read):
        return check.observe('http://localhost', REVISION, seconds=seconds, **observe_kwargs)


class CustomerObservationTests(unittest.TestCase):
    def test_startup_budget_rejects_nonfinite_non_numeric_and_out_of_bounds_before_http(self):
        check = module()
        for invalid in (None, True, False, '10', 0, .99, 60.01, float('nan'),
                        float('inf'), -float('inf'), 10 ** 1000):
            clock = Clock()
            with self.subTest(value=repr(invalid)), patch.object(check, 'read_json') as read, \
                    patch.object(check.time, 'monotonic', side_effect=lambda: clock.now), \
                    patch.object(check.time, 'sleep', side_effect=clock.sleep):
                with self.assertRaisesRegex(ValueError, 'startup.*1.*60'):
                    check.observe('http://localhost', REVISION, seconds=10, startup_timeout=invalid)
                read.assert_not_called()
        for budget in (1.0, 60.0):
            self.assertEqual(observe_lifecycle(startup_timeout=budget)['required_startup_timeout_s'], budget)

    def test_expired_startup_retains_failure_but_observes_subsequent_actual_progress(self):
        for mode in ('healthy', 'initial_http_error'):
            with self.subTest(mode=mode):
                report = observe_lifecycle(seconds=90, cold_delay_s=6.5 - 4 / 1.1,
                                           startup_timeout=6.0, mode=mode)
                self.assertFalse(report['passed'])
                deadlines = [error for error in report['errors'] if 'deadline' in error['error']]
                self.assertEqual(len(deadlines), 1)
                self.assertLessEqual(deadlines[0]['wall_s'], 6.2)
                self.assertIn('6', deadlines[0]['error'])
                self.assertIn('error_free_http_observation', report['failed_gates'])
                self.assertNotIn('observed_cuda_nvidia_auto', report['failed_gates'])
                self.assertNotIn('terminal_fresh_native_observation', report['failed_gates'])
                self.assertGreater(report['hardware_observations'], 300)
                self.assertGreater(report['healthy_wall_s'], 70)

    def test_overbudget_never_armed_and_terminal_unarmed_remain_failed(self):
        report = observe_lifecycle(seconds=90, cold_delay_s=10.5 - 4 / 1.1)
        self.assertFalse(report['passed'])
        self.assertTrue(any('deadline' in error['error'] for error in report['errors']))
        for mode in ('never_advances', 'never_arms', 'terminal_unarmed', 'manual'):
            with self.subTest(mode=mode):
                failed = observe_lifecycle(seconds=20, mode=mode)
                self.assertFalse(failed['passed'])
                if mode == 'never_advances':
                    self.assertEqual(failed['healthy_wall_s'], 0)
                    self.assertEqual(failed['hardware_observations'], 0)

    def test_cold_start_budget_is_explicit_and_preserves_episode_clock_boundaries(self):
        for startup_wall_s in (6.2, 6.5):
            with self.subTest(startup_wall_s=startup_wall_s):
                report = observe_lifecycle(seconds=90, cold_delay_s=startup_wall_s - 4 / 1.1)
                self.assertTrue(report['passed'], report)
                self.assertEqual(report['errors'], [])
                self.assertEqual(report['required_startup_timeout_s'], 10.0)
                self.assertEqual(report['episodes'], 3)
                self.assertEqual(set(report['episode_healthy_wall_s']), {'0', '1', '2'})
                self.assertGreaterEqual(report['healthy_wall_s'], 45)
                self.assertLessEqual(report['healthy_wall_s'], 90 - startup_wall_s - 2 * 4 / 1.1)
                self.assertTrue(all(0 < span < 45 / 1.1
                                    for span in report['episode_healthy_progress_window_s'].values()))
                self.assertAlmostEqual(report['simulation_realtime_factor'], 1.1)
                self.assertAlmostEqual(report['observed_source_hz'], 70.4)
                self.assertEqual(report['required_min_sim_rate'], 1.0)
                self.assertEqual(report['required_min_source_hz'], 30.0)
                failed = observe_lifecycle(seconds=90, cold_delay_s=startup_wall_s - 4 / 1.1,
                                           startup_timeout=6.0)
                self.assertFalse(failed['passed'])
                self.assertEqual(failed['required_startup_timeout_s'], 6.0)
                self.assertTrue(any('deadline' in error['error'] for error in failed['errors']))

    def test_initial_live_autostart_is_bounded_and_never_masks_manual_regression(self):
        report = observe_lifecycle()
        self.assertEqual(report['errors'], [])
        self.assertTrue(report['passed'], report)
        self.assertAlmostEqual(report['simulation_realtime_factor'], 1.1)
        self.assertAlmostEqual(report['observed_source_hz'], 70.4)
        self.assertEqual(report['required_min_sim_rate'], 1.0)
        self.assertEqual(report['required_min_source_hz'], 30.0)
        self.assertGreaterEqual(report['healthy_wall_s'], 5)
        self.assertLessEqual(report['healthy_wall_s'], 10 - 4 / 1.1)
        for mode in ('manual', 'never_arms', 'late_arms', 'startup_frozen'):
            with self.subTest(mode=mode):
                failed = observe_lifecycle(mode=mode, startup_timeout=6.0)
                self.assertFalse(failed['passed'])
                self.assertTrue(failed['errors'])
                if mode == 'startup_frozen':
                    self.assertTrue(any('deadline' in row['error'] for row in failed['errors']))

    def test_normal_45_sim_second_episodes_sustain_default_90_second_observation(self):
        report = observe_lifecycle(seconds=90)
        self.assertEqual(report['errors'], [])
        self.assertTrue(report['passed'], report)
        self.assertEqual(report['episodes'], 3)
        self.assertEqual(set(report['episode_healthy_wall_s']), {'0', '1', '2'})
        self.assertAlmostEqual(report['healthy_wall_s'], sum(report['episode_healthy_wall_s'].values()))
        self.assertGreaterEqual(report['healthy_wall_s'], 45)
        self.assertLessEqual(report['healthy_wall_s'], 90 - 3 * 4 / 1.1)
        self.assertEqual(report['required_same_episode_progress_s'], 5)
        self.assertGreaterEqual(max(report['episode_healthy_progress_window_s'].values()), 5)
        self.assertTrue(all(0 < value < 45 / 1.1
                            for value in report['episode_healthy_progress_window_s'].values()))
        self.assertAlmostEqual(report['simulation_realtime_factor'], 1.1)
        self.assertAlmostEqual(report['observed_source_hz'], 70.4)
        self.assertEqual(report['required_min_sim_rate'], 1.0)
        self.assertEqual(report['required_min_source_hz'], 30.0)
        self.assertFalse(observe_lifecycle(seconds=90, episode_sim_seconds=2.2)['passed'])

    def test_terminal_failure_manual_stale_or_empty_cannot_reuse_healthy_history(self):
        for mode in ('failed', 'stopped', 'manual', 'stale', 'empty', 'starting', 'between_episodes'):
            with self.subTest(mode=mode):
                self.assertFalse(observe_fixture(mode)['passed'])

    def test_policy_freeze_cannot_reuse_initial_publication_progress(self):
        self.assertFalse(observe_fixture('policy_frozen')['passed'])

    def test_short_episodes_cannot_join_hardware_progress(self):
        self.assertFalse(observe_fixture('churn')['passed'])

    def test_healthy_and_brief_transition_followed_by_sustained_episode_pass(self):
        self.assertTrue(observe_fixture('healthy')['passed'])
        self.assertTrue(observe_fixture('transition')['passed'])
