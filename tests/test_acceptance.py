import copy
import io
import tarfile
import unittest
from check_image import number, validate_archive, validate_live_state, verify_progress


def state():
    return {'status': 'live', 'engine': {'native': True}, 'episode': {'id': 'run-one'},
            'frame_age_s': 0.1, 'configuration': {'inference': 'cpu'},
            'frame': {'schema_version': 1, 'seq': 10, 'sim_time_s': 5.0,
                      'position_m': {'x': 1.0, 'y': 2.0, 'z': 3.0},
                      'velocity_m_s': {'x': 0.1, 'y': 0.2, 'z': 0.3},
                      'policy_prediction_m_s': {'x': 0.1, 'y': 0.2, 'z': 0.3},
                      'armed': True, 'auto_enabled': True, 'inference_backend': 'cpu',
                      'inference_count': 20, 'policy_observation_seq': 20,
                      'graphics': {'backend': 'Vulkan', 'adapter_name': 'llvmpipe'}}}


def archive(entries):
    b = io.BytesIO()
    with tarfile.open(fileobj=b, mode='w:gz') as t:
        for name, link in entries:
            m = tarfile.TarInfo(name)
            if link is None:
                m.size = 4
                t.addfile(m, io.BytesIO(b'test'))
            else:
                m.type = tarfile.SYMTYPE
                m.linkname = link
                t.addfile(m)
    b.seek(0)
    return b


class AcceptanceTests(unittest.TestCase):
    def test_live_state_requires_a_bounded_nonempty_string_episode_id(self):
        for episode in [{}, {'id': None}, {'id': []}, {'id': 1}, {'id': ''},
                        {'id': ' \t\n'}, {'id': 'x' * 129}, None, [], 1]:
            s = state()
            s['episode'] = episode
            with self.subTest(episode=episode), self.assertRaisesRegex(ValueError, 'episode'):
                validate_live_state(s, 'cpu', allow_software=True)
        s = state()
        del s['episode']
        with self.assertRaisesRegex(ValueError, 'episode'):
            validate_live_state(s, 'cpu', allow_software=True)
        s['episode'] = {'id': 'x' * 128}
        validate_live_state(s, 'cpu', allow_software=True)

    def test_progress_validates_both_episode_ids_before_comparison(self):
        for episode in [{}, {'id': None}, {'id': []}, {'id': 1}, {'id': ''},
                        {'id': '   '}, {'id': 'x' * 129}, None, [], 1]:
            for invalid_sides in [('before',), ('after',), ('before', 'after')]:
                before, after = state(), state()
                for key in ('seq', 'sim_time_s', 'policy_observation_seq'):
                    after['frame'][key] += 1
                for side in invalid_sides:
                    (before if side == 'before' else after)['episode'] = episode
                with self.subTest(episode=episode, sides=invalid_sides), self.assertRaisesRegex(ValueError, 'episode'):
                    verify_progress(before, after)
        before, after = state(), state()
        del before['episode']
        del after['episode']
        for key in ('seq', 'sim_time_s', 'policy_observation_seq'):
            after['frame'][key] += 1
        with self.assertRaisesRegex(ValueError, 'episode'):
            verify_progress(before, after)

    def test_observed_policy_sequence_is_not_misreported_as_exact_inference_count(self):
        s = state()
        s['frame']['inference_count'] = None
        s['frame']['policy_observation_seq'] = 12
        evidence = validate_live_state(s, 'cpu', allow_software=True)
        self.assertIsNone(evidence['inference_count'])
        self.assertEqual(evidence['policy_observation_seq'], 12)

    def test_required_evidence_fields_cannot_be_missing_including_nullable_count(self):
        for key in ('seq', 'sim_time_s', 'position_m', 'velocity_m_s', 'policy_prediction_m_s',
                    'inference_backend', 'inference_count', 'policy_observation_seq', 'graphics'):
            s = state()
            del s['frame'][key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_live_state(s, 'cpu', allow_software=True)

    def test_number_fails_closed_on_integers_too_large_for_finite_float_checks(self):
        for value in (10 ** 400, -(10 ** 400)):
            with self.subTest(value=value):
                self.assertFalse(number(value))
        self.assertTrue(number(1))
        self.assertFalse(number(True))

    def test_native_cpu_proof_requires_observed_policy_and_explicit_software_permission(self):
        s = state()
        evidence = validate_live_state(s, 'cpu', allow_software=True)
        self.assertEqual(evidence['inference_count'], 20)
        with self.assertRaises(ValueError):
            validate_live_state(s, 'cpu', allow_software=False)

    def test_cuda_configuration_or_graph_label_is_not_cuda_execution(self):
        s = state()
        s['configuration']['inference'] = 'cuda'
        with self.assertRaises(ValueError):
            validate_live_state(s, 'cuda', allow_software=True)
        s['frame']['inference_backend'] = 'cuda'
        s['frame']['policy_observation_seq'] = 0
        with self.assertRaises(ValueError):
            validate_live_state(s, 'cuda', allow_software=True)

    def test_stale_manual_or_nonfinite_frames_cannot_pass(self):
        changes = [('frame_age_s', 20), ('status', 'starting'), ('armed', False),
                   ('auto_enabled', False), ('seq', True), ('policy_observation_seq', None),
                   ('position_m', {'x': float('nan'), 'y': 0, 'z': 0}),
                   ('policy_prediction_m_s', None)]
        for key, value in changes:
            s = state()
            (s if key in ('status', 'frame_age_s') else s['frame'])[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_live_state(s, 'cpu', allow_software=True)

    def test_confirmed_native_cuda_with_hardware_graphics_is_accepted(self):
        s = state()
        s['configuration']['inference'] = 'cuda'
        s['frame']['inference_backend'] = 'cuda'
        for device_type in ('IntegratedGpu', 'DiscreteGpu'):
            s['frame']['graphics'] = {'backend': 'Vulkan', 'adapter_name': 'NVIDIA Orin',
                                      'vendor_id': 0x10de, 'device_type': device_type}
            with self.subTest(device_type=device_type):
                self.assertEqual(validate_live_state(s, 'cuda')['inference_backend'], 'cuda')

    def test_hardware_graphics_requires_positive_typed_nvidia_vulkan_adapter_evidence(self):
        valid = {'backend': 'Vulkan', 'adapter_name': 'NVIDIA Orin',
                 'vendor_id': 0x10de, 'device_type': 'IntegratedGpu'}
        invalid = [{'backend': 'Noop', 'adapter_name': 'Unknown'},
                   {'backend': 'Vulkan', 'adapter_name': 'NVIDIA Orin'},
                   {key: value for key, value in valid.items() if key != 'vendor_id'},
                   {key: value for key, value in valid.items() if key != 'device_type'}]
        for key, values in [('backend', ['Noop', 'Unknown', 'OpenGL', 'vulkan']),
                            ('adapter_name', ['Unknown', '   ', 'NVIDIA llvmpipe',
                                              'NVIDIA lavapipe', 'SwiftShader', 'software', 'CPU']),
                            ('vendor_id', ['0x10de', '4318', float(0x10de), True, 0x8086, None]),
                            ('device_type', ['Cpu', 'CPU', 'Other', 'Unknown', None, 1])]:
            invalid.extend({**valid, key: value} for value in values)
        for graphics in invalid:
            s = state()
            s['configuration']['inference'] = 'cuda'
            s['frame']['inference_backend'] = 'cuda'
            s['frame']['graphics'] = graphics
            with self.subTest(graphics=graphics), self.assertRaises(ValueError):
                validate_live_state(s, 'cuda')

    def test_progress_requires_new_observations_same_episode_and_policy_calls(self):
        first = state()
        after = copy.deepcopy(first)
        with self.assertRaises(ValueError):
            verify_progress(first, after)
        after['frame']['seq'] += 1
        after['frame']['sim_time_s'] += 0.5
        with self.assertRaises(ValueError):
            verify_progress(first, after)
        after['frame']['policy_observation_seq'] += 1
        verify_progress(first, after)
        after['episode']['id'] = 'different-run'
        with self.assertRaises(ValueError):
            verify_progress(first, after)

    def test_archive_preserves_both_native_log_families_and_safe_aliases(self):
        b = archive([('flight_controller_sim_0.copper', None),
                     ('flight_controller_sim.copper', 'flight_controller_sim_0.copper'),
                     ('flight_compute_sim_0.copper', None),
                     ('flight_compute_sim.copper', 'flight_compute_sim_0.copper')])
        proof = validate_archive(b)
        self.assertEqual(proof['native_first_slabs'], 2)
        self.assertEqual(proof['safe_aliases'], 2)

    def test_archive_rejects_canonical_file_and_symlink_collisions(self):
        for root in ('', 'logs/'):
            controller = root + 'flight_controller_sim_0.copper'
            compute = root + 'flight_compute_sim_0.copper'
            for collision in ('./' + controller, '././' + controller,
                              root + './flight_controller_sim_0.copper',
                              controller.replace('/', '//')):
                for link in (None, 'flight_compute_sim_0.copper'):
                    entries = [(controller, None), (compute, None), (collision, link)]
                    for ordered in (entries, list(reversed(entries))):
                        with self.subTest(entries=ordered), self.assertRaisesRegex(ValueError, 'duplicate'):
                            validate_archive(archive(ordered))

    def test_archive_alias_lookup_uses_canonical_names_without_weakening_confinement(self):
        entries = [('./logs//flight_controller_sim_0.copper', None),
                   ('logs/./flight_compute_sim_0.copper', None),
                   ('logs//flight_controller_sim.copper', './flight_controller_sim_0.copper')]
        proof = validate_archive(archive(entries))
        self.assertEqual(proof['native_first_slabs'], 2)
        self.assertEqual(proof['safe_aliases'], 1)
        for name, target in [('/logs/escape', None), ('logs/../escape', None),
                             ('logs/escape', '../flight_compute_sim_0.copper'),
                             ('logs/escape', '/flight_compute_sim_0.copper'),
                             ('logs/escape', 'sub/flight_compute_sim_0.copper')]:
            with self.subTest(name=name, target=target), self.assertRaises(ValueError):
                validate_archive(archive(entries + [(name, target)]))

    def test_archive_inventory_does_not_claim_complete_native_logs_or_replay(self):
        with self.assertRaisesRegex(ValueError, 'required first.slab inventory'):
            validate_archive(archive([('flight_controller_sim_0.copper', None)]))

    def test_archive_rejects_unrelated_families_or_mixed_run_roots(self):
        for entries in [[('unrelated_0.copper', None), ('other_0.copper', None)],
                        [('a/flight_controller_sim_0.copper', None),
                         ('b/flight_compute_sim_0.copper', None)]]:
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                validate_archive(archive(entries))

    def test_archive_rejects_escape_and_missing_native_families(self):
        for entries in [[('../escape', None)], [('/escape', None)],
                        [('mcu_0.copper', None)], [('mcu.copper', '../outside')]]:
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                validate_archive(archive(entries))


if __name__ == '__main__':
    unittest.main()
