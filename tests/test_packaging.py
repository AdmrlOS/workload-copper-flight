"""Final-image contract checks; set FLIGHT_IMAGE to the exact tested image."""
import json
import os
import subprocess
import unittest


@unittest.skipUnless(os.environ.get('FLIGHT_IMAGE'), 'set FLIGHT_IMAGE for actual image-contract acceptance')
class PackagedImageTests(unittest.TestCase):
    def test_default_log_budget_has_headroom_for_the_upstream_45_second_episode(self):
        image = os.environ['FLIGHT_IMAGE']
        result = subprocess.run(['docker', 'image', 'inspect', image], check=True,
                                capture_output=True, text=True, timeout=30)
        metadata = json.loads(result.stdout)[0]
        environment = dict(item.split('=', 1) for item in metadata['Config'].get('Env', []))
        self.assertEqual(metadata['Os'], 'linux')
        self.assertEqual(metadata['Architecture'], 'arm64')
        self.assertEqual(environment.get('FLIGHT_EPISODE_SECONDS'), '45')
        self.assertEqual(environment.get('FLIGHT_MAX_BYTES'), '8589934592',
                         'the measured 12-second log footprint does not establish that 45 seconds fit 4 GiB')


    def test_unprivileged_service_can_read_every_declared_static_asset(self):
        script = '''import json,pathlib
root=pathlib.Path('/opt/copper-flight/www')
routes=json.loads((root/'static-routes.json').read_text())['static_routes']
for route in routes:
 with (root/route.lstrip('/')).open('rb') as stream:
  assert stream.read(1), route
print(json.dumps({'readable_static_routes':len(routes)}))
'''
        result = subprocess.run(
            ['docker', 'run', '--rm', '--network', 'none', '--user', '10001:10001',
             '--entrypoint', 'python3', os.environ['FLIGHT_IMAGE'], '-c', script],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater(json.loads(result.stdout)['readable_static_routes'], 0)

    def test_nvidia_surface_free_driver_has_its_runtime_egl_vendor_closure(self):
        metadata = json.loads(subprocess.check_output(
            ['docker', 'image', 'inspect', os.environ['FLIGHT_IMAGE']], text=True))[0]
        environment = dict(item.split('=', 1) for item in metadata['Config'].get('Env', []))
        self.assertEqual(environment.get('__EGL_VENDOR_LIBRARY_FILENAMES'),
                         '/usr/lib/aarch64-linux-gnu/tegra-egl/nvidia.json')
        self.assertIn('/usr/lib/aarch64-linux-gnu/tegra-egl',
                      environment.get('LD_LIBRARY_PATH', '').split(':'))
        script = '''import json,pathlib
lock=json.loads(pathlib.Path('/opt/copper-flight/provenance/payload.lock.json').read_text())
paths={entry['path'] for entry in lock['files']}
assert {'usr/lib/aarch64-linux-gnu/tegra-egl/libEGL_nvidia.so.0',
        'usr/lib/aarch64-linux-gnu/nvidia/libnvidia-eglcore.so.595.78',
        'usr/lib/aarch64-linux-gnu/tegra-egl/nvidia.json'} <= paths
assert json.loads(pathlib.Path('/usr/lib/aarch64-linux-gnu/tegra-egl/nvidia.json').read_text())['ICD']['library_path']=='libEGL_nvidia.so.0'
'''
        result = subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--entrypoint',
                                 'python3', os.environ['FLIGHT_IMAGE'], '-c', script],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_final_contains_locked_graphics_probe_and_observed_adapter_binary(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        evidence_path = Path(os.environ.get('FLIGHT_NATIVE_EVIDENCE', root / 'vendor-assets/adapter-proof/evidence.json'))
        evidence = json.loads(evidence_path.read_text())
        script = '''import hashlib,json,pathlib
root=pathlib.Path('/')
lock=json.loads(pathlib.Path('/opt/copper-flight/provenance/payload.lock.json').read_text())
for entry in lock['files']:
 p=root/entry['path']
 if entry['type']=='file':
  assert not p.is_symlink() and p.stat().st_size==entry['bytes'], str(p)
  with p.open('rb') as f: assert hashlib.file_digest(f,'sha256').hexdigest()==entry['sha256'], str(p)
 else: assert p.is_symlink() and p.readlink().as_posix()==entry['target'], str(p)
assert not any(p.name in lock['injected_library_exclusions'] for p in pathlib.Path('/usr/lib/aarch64-linux-gnu/nvidia').iterdir())
assert pathlib.Path('/usr/local/bin/copper-vulkan-depth-probe').is_file()
p=pathlib.Path('/opt/copper-flight/bin/quad-sim')
print(json.dumps({'native_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'entries':len(lock['files'])}))
'''
        result = subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python3',
                                 os.environ['FLIGHT_IMAGE'], '-c', script], capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = json.loads(result.stdout)
        self.assertEqual(actual['native_sha256'], evidence['binaries']['quad-sim-cuda']['sha256'])
        metadata = json.loads(subprocess.check_output(['docker', 'image', 'inspect', os.environ['FLIGHT_IMAGE']], text=True))[0]
        environment = dict(item.split('=', 1) for item in metadata['Config'].get('Env', []))
        self.assertEqual(environment.get('VK_DRIVER_FILES'), '/etc/vulkan/icd.d/nvidia_icd.json')
        self.assertTrue(environment.get('LD_LIBRARY_PATH', '').startswith('/run/admiral/nvidia/lib:'))


if __name__ == '__main__':
    unittest.main()
