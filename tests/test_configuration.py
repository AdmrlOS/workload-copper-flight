import copy
import unittest

from scripts import configure_admiral
from scripts.configure_admiral import (
    CREDENTIAL, DEVICE, FLEET, build_configuration, build_fleet_patch,
    normalized_spec, verify_configuration, verify_fleet_selection,
)

IMAGE = 'ghcr.io/admrlos/workload-copper-flight@sha256:' + 'a' * 64
OLD = {'id': '9e598960-1a24-4275-956d-f1f06e3eb8e4', 'version': 'latest'}
NEW = {'id': '4d8886d1-fc65-4b64-8faa-7a4b695f0936', 'version': '1'}


class ConfigurationTests(unittest.TestCase):
    def document(self):
        p = build_configuration(IMAGE)
        return p, {'metadata': {'name': p['name']}, 'spec': copy.deepcopy(p['spec']),
                   'status': {'fleetUsage': [], 'fleets': []}}

    def test_native_graphics_configuration_is_private_explicit_and_persistent(self):
        p = build_configuration(IMAGE)
        self.assertEqual(p['name'], 'copper-flight')
        self.assertEqual(p['spec']['image'], IMAGE)
        self.assertEqual(p['spec']['registry_credential_id'], CREDENTIAL)
        self.assertFalse(p['spec']['options']['tty'])
        self.assertTrue(p['spec']['options']['all_devices_allowed'])
        self.assertFalse(p['spec']['options']['privileged'])
        self.assertEqual(p['spec']['options']['host_namespaces'], [])
        self.assertEqual(p['spec']['ports'], [{'port': 8080, 'protocol': 'tcp'}])
        self.assertEqual(p['spec']['environment']['FLIGHT_INFERENCE'], 'cuda')
        self.assertEqual(p['spec']['environment']['FLIGHT_DISPLAY_MODE'], 'headless')
        self.assertEqual(p['spec']['environment']['FLIGHT_DATA_DIR'], '/data/copper-flight')
        self.assertEqual(p['spec']['volumes']['data']['destination'], '/data')

    def test_production_budget_is_8gib_without_shortening_the_45_second_mission(self):
        environment = build_configuration(IMAGE)['spec']['environment']
        self.assertEqual(environment['FLIGHT_MAX_BYTES'], '8589934592')
        self.assertEqual(environment['FLIGHT_EPISODE_SECONDS'], '45')
        self.assertEqual(environment['FLIGHT_KEEP_RUNS'], '2')

    def test_only_exact_immutable_image_references_are_accepted(self):
        for image in [IMAGE + ':latest', IMAGE.upper(), IMAGE[:-1], IMAGE + '0',
                      'ghcr.io/admrlos/workload-copper-flight:latest',
                      IMAGE.replace('workload-copper-flight', 'workload-copper'), '\n' + IMAGE]:
            with self.subTest(image=image), self.assertRaises(ValueError):
                build_configuration(image)

    def test_known_empty_serialization_is_the_only_normalization(self):
        p, d = self.document()
        d['spec']['command'] = None
        d['spec']['mounts'] = None
        del d['spec']['options']['host_namespaces']
        verify_configuration(d, p)
        self.assertNotEqual(normalized_spec({'a': False}), normalized_spec({}))
        self.assertNotEqual(normalized_spec({'a': None}), normalized_spec({}))

    def test_readback_rejects_environment_credential_device_and_volume_drift(self):
        for field in ['environment', 'registry_credential_id', 'options', 'volumes']:
            p, d = self.document()
            del d['spec'][field]
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                verify_configuration(d, p)
        p, d = self.document()
        d['spec']['environment']['UNREQUESTED'] = 'value'
        with self.assertRaises(RuntimeError):
            verify_configuration(d, p)
        p, d = self.document()
        d['status']['fleetUsage'] = [FLEET]
        with self.assertRaises(RuntimeError):
            verify_configuration(d, p)

    def fleet(self):
        return {'metadata': {'id': FLEET, 'resourceVersion': '1-original'},
                'spec': {'configuration': copy.deepcopy(OLD), 'updates': {'window': None},
                         'features': {'remoteSupport': True}}}

    def test_canary_patch_only_changes_selection_and_uses_current_revision(self):
        live = self.fleet()
        before = copy.deepcopy(live)
        patch, revision = build_fleet_patch(live, OLD, NEW, [DEVICE])
        self.assertEqual(patch, {'spec': {'configuration': NEW}})
        self.assertEqual(revision, '1-original')
        self.assertEqual(live, before)

    def test_canary_rejects_selection_drift_wrong_fleet_and_extra_devices(self):
        for mode in ['selection', 'fleet', 'revision', 'extra', 'missing', 'duplicate']:
            live = self.fleet()
            devices = [DEVICE]
            if mode == 'selection':
                live['spec']['configuration']['id'] = NEW['id']
            elif mode == 'fleet':
                live['metadata']['id'] = NEW['id']
            elif mode == 'revision':
                del live['metadata']['resourceVersion']
            elif mode == 'extra':
                devices.append(NEW['id'])
            elif mode == 'missing':
                devices = []
            elif mode == 'duplicate':
                devices.append(DEVICE)
            with self.subTest(mode=mode), self.assertRaises(RuntimeError):
                build_fleet_patch(live, OLD, NEW, devices)

    def test_canary_rejects_malformed_target_identifiers_and_versions(self):
        for target in [{'id': 'bad', 'version': '1'}, {'id': NEW['id'], 'version': 'latest'},
                       {'id': NEW['id'], 'version': 1}, {'id': NEW['id'], 'version': '0'},
                       {'id': NEW['id'], 'version': '01'}, {'id': NEW['id'], 'version': '1', 'extra': True}]:
            with self.subTest(target=target), self.assertRaises(ValueError):
                build_fleet_patch(self.fleet(), OLD, target, [DEVICE])

    def rollback(self, *args):
        self.assertTrue(callable(getattr(configure_admiral, 'build_fleet_rollback', None)),
                        'the saved-document-only rollback helper is missing')
        return configure_admiral.build_fleet_rollback(*args)

    def test_rollback_restores_exact_saved_selection_using_current_revision_only(self):
        for version in ('latest', '2'):
            prior = self.fleet()
            prior['spec']['configuration']['version'] = version
            current = self.fleet()
            current['spec']['configuration'] = copy.deepcopy(NEW)
            current['metadata']['resourceVersion'] = '2-current'
            before = copy.deepcopy((current, prior))
            patch, revision = self.rollback(current, NEW, prior, [DEVICE])
            with self.subTest(version=version):
                self.assertEqual(patch, {'spec': {'configuration': prior['spec']['configuration']}})
                self.assertEqual(revision, '2-current')
                self.assertEqual((current, prior), before)
            if version == 'latest':
                with self.assertRaises(ValueError):
                    build_fleet_patch(current, NEW, prior['spec']['configuration'], [DEVICE])

    def test_rollback_rejects_forged_wrong_fleet_or_missing_saved_selection(self):
        current = self.fleet()
        current['spec']['configuration'] = copy.deepcopy(NEW)
        invalid = [None, [], copy.deepcopy(OLD), {},
                   {'metadata': {'id': FLEET, 'resourceVersion': 'saved'}, 'spec': {}}]
        for mode in ('fleet', 'revision', 'metadata', 'spec', 'selection'):
            prior = self.fleet()
            if mode == 'fleet':
                prior['metadata']['id'] = NEW['id']
            elif mode == 'revision':
                del prior['metadata']['resourceVersion']
            elif mode == 'metadata':
                prior['metadata'] = []
            elif mode == 'spec':
                prior['spec'] = []
            else:
                prior['spec']['configuration'] = None
            invalid.append(prior)
        for selection in [{'id': 'forged', 'version': 'latest'},
                          {'id': OLD['id']}, {'id': OLD['id'], 'version': 1},
                          {'id': OLD['id'], 'version': '0'}, {'id': OLD['id'], 'version': '01'},
                          {'id': OLD['id'], 'version': 'LATEST'},
                          {'id': OLD['id'], 'version': 'latest', 'extra': True}, [], 'latest']:
            prior = self.fleet()
            prior['spec']['configuration'] = selection
            invalid.append(prior)
        for prior in invalid:
            with self.subTest(prior=prior), self.assertRaises((RuntimeError, ValueError)):
                self.rollback(current, NEW, prior, [DEVICE])

    def test_rollback_preserves_current_selection_fleet_membership_and_concurrency_guards(self):
        for mode in ('selection', 'fleet', 'revision', 'extra', 'missing', 'duplicate', 'wrong-device'):
            current = self.fleet()
            current['spec']['configuration'] = copy.deepcopy(NEW)
            devices = [DEVICE]
            if mode == 'selection':
                current['spec']['configuration']['version'] = '2'
            elif mode == 'fleet':
                current['metadata']['id'] = NEW['id']
            elif mode == 'revision':
                del current['metadata']['resourceVersion']
            elif mode == 'extra':
                devices.append(NEW['id'])
            elif mode == 'missing':
                devices = []
            elif mode == 'duplicate':
                devices.append(DEVICE)
            else:
                devices = [NEW['id']]
            with self.subTest(mode=mode), self.assertRaises(RuntimeError):
                self.rollback(current, NEW, self.fleet(), devices)
        for expected in [OLD, {'id': NEW['id']}, {'id': NEW['id'], 'version': '0'}]:
            current = self.fleet()
            current['spec']['configuration'] = copy.deepcopy(expected)
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                self.rollback(current, expected, self.fleet(), [DEVICE])

    def test_postwrite_readback_must_match_the_exact_selected_version(self):
        d = self.fleet()
        d['spec']['configuration'] = copy.deepcopy(NEW)
        verify_fleet_selection(d, NEW)
        d['spec']['configuration']['version'] = 'latest'
        with self.assertRaises(RuntimeError):
            verify_fleet_selection(d, NEW)


if __name__ == '__main__':
    unittest.main()
