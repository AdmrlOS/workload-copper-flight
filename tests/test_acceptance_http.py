"""HTTP fixtures exercise the acceptance client, not native Copper execution."""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

import check_image
from test_acceptance import state


@contextlib.contextmanager
def fixture_server(response, raw=False):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            body = response(self.path)
            if raw:
                # Explicit malformed transport fixture, not native runtime evidence.
                self.wfile.write(body)
                self.close_connection = True
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class AcceptanceHttpTests(unittest.TestCase):
    def assert_malformed_cli_replaces_old_passed_report(self, malformed, error_text, raw=False):
        script = str(Path(check_image.__file__).resolve())
        old = {'passed': True, 'fixture': 'old report; not runtime evidence'}
        body = malformed if raw else json.dumps(malformed).encode()
        with tempfile.TemporaryDirectory() as directory, \
                fixture_server(lambda _: body, raw=raw) as url:
            report = Path(directory) / 'fixture-report.json'
            report.write_text(json.dumps(old))
            with report.open() as old_report:
                result = subprocess.run(
                    [sys.executable, script, '--url', url, '--backend', 'cpu', '--allow-software',
                     '--timeout', '.2', '--observe-seconds', '.05', '--interval', '.02',
                     '--report', str(report)], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertTrue(result.stdout.strip(), result.stderr)
                self.assertEqual(result.stderr, '')
                proof = json.loads(result.stdout)
                self.assertFalse(proof['passed'])
                self.assertIn(error_text, proof['error'])
                self.assertEqual(json.loads(report.read_text()), proof)
                # An already-open handle still sees the old inode: replacement was atomic.
                self.assertEqual(json.load(old_report), old)
            self.assertEqual(list(Path(directory).iterdir()), [report])

    def test_cli_invalid_chunk_replaces_old_passed_report(self):
        malformed = b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nINVALID-CHUNK\r\n'
        self.assert_malformed_cli_replaces_old_passed_report(malformed, 'IncompleteRead', raw=True)

    def test_cli_overlong_header_replaces_old_passed_report(self):
        malformed = b'HTTP/1.1 200 OK\r\nX-Test-Fixture: ' + b'x' * 65537 + b'\r\n\r\n'
        self.assert_malformed_cli_replaces_old_passed_report(malformed, 'header line', raw=True)

    def test_cli_missing_nullable_inference_count_replaces_old_passed_report(self):
        malformed = state()
        del malformed['frame']['inference_count']
        self.assert_malformed_cli_replaces_old_passed_report(malformed, 'inference count')

    def test_cli_oversized_frame_age_integer_replaces_old_passed_report(self):
        malformed = state()
        malformed['frame_age_s'] = 10 ** 400
        self.assert_malformed_cli_replaces_old_passed_report(malformed, 'stale or missing')

    def test_observer_rejects_missing_invalid_and_churning_episode_ids(self):
        for episode in [{}, {'id': None}, {'id': []}, {'id': 1}, {'id': ''},
                        {'id': '   '}, 'missing', 'churn']:
            request_count = 0
            def advancing(_):
                nonlocal request_count
                request_count += 1
                s = state()
                for key in ('seq', 'sim_time_s', 'policy_observation_seq'):
                    s['frame'][key] += request_count
                if episode == 'missing':
                    del s['episode']
                elif episode == 'churn':
                    s['episode']['id'] = 'run-' + str(request_count)
                else:
                    s['episode'] = episode
                return json.dumps(s).encode()
            with self.subTest(episode=episode), fixture_server(advancing) as url:
                with self.assertRaises(TimeoutError):
                    check_image.observe_live(url, 'cpu', allow_software=True,
                                             timeout=.18, observe_seconds=.05, interval=.02)

    def test_command_emits_a_scoped_report_and_nonzero_on_a_frozen_fixture(self):
        request_count = 0
        def advancing(_):
            nonlocal request_count
            request_count += 1
            s = state()
            for key in ('seq', 'sim_time_s', 'policy_observation_seq'):
                s['frame'][key] += request_count
            return json.dumps(s).encode()
        script = str(Path(check_image.__file__).resolve())
        with tempfile.TemporaryDirectory() as directory, fixture_server(advancing) as url:
            report = Path(directory) / 'test-fixture-evidence.json'
            command = [sys.executable, script, '--url', url, '--backend', 'cpu',
                       '--allow-software', '--timeout', '2', '--observe-seconds', '.05',
                       '--interval', '.02', '--report', str(report)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.strip(), 'the acceptance CLI produced no evidence')
            proof = json.loads(result.stdout)
            self.assertEqual(json.loads(report.read_text()), proof)
            self.assertTrue(proof['passed'])
            self.assertFalse(proof['native_replay_verified'])
            self.assertFalse(proof['hardware_graphics_required'])
        with fixture_server(lambda _: json.dumps(state()).encode()) as url:
            command = [sys.executable, script, '--url', url, '--backend', 'cpu',
                       '--allow-software', '--timeout', '.2', '--observe-seconds', '.05',
                       '--interval', '.02']
            result = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            proof = json.loads(result.stdout)
            self.assertFalse(proof['passed'])
            self.assertFalse(proof['native_replay_verified'])

    def test_observer_reports_only_advancing_native_and_policy_observations(self):
        self.assertTrue(callable(getattr(check_image, 'observe_live', None)),
                        'the native-progress observer is missing')
        request_count = 0
        def response(_):
            nonlocal request_count
            request_count += 1
            s = state()
            s['frame']['seq'] += request_count
            s['frame']['sim_time_s'] += request_count
            s['frame']['policy_observation_seq'] += request_count
            s['frame']['inference_count'] = None
            return json.dumps(s).encode()
        with fixture_server(response) as url:
            proof = check_image.observe_live(url, 'cpu', allow_software=True,
                                             timeout=2, observe_seconds=.05, interval=.02)
        self.assertTrue(proof['passed'])
        self.assertEqual(proof['scope'], 'native-simulation-and-observed-policy-progress')
        self.assertFalse(proof['native_replay_verified'])
        self.assertIsNone(proof['last']['inference_count'])
        self.assertGreater(proof['last']['policy_observation_seq'],
                           proof['first']['policy_observation_seq'])

    def test_hardware_observer_rejects_noop_unknown_even_with_advancing_cuda(self):
        request_count = 0
        def response(_):
            nonlocal request_count
            request_count += 1
            s = state()
            for key in ('seq', 'sim_time_s', 'policy_observation_seq'):
                s['frame'][key] += request_count
            s['configuration']['inference'] = 'cuda'
            s['frame']['inference_backend'] = 'cuda'
            s['frame']['graphics'] = {'backend': 'Noop', 'adapter_name': 'Unknown'}
            return json.dumps(s).encode()
        with fixture_server(response) as url:
            with self.assertRaises(TimeoutError):
                check_image.observe_live(url, 'cuda', timeout=.18,
                                         observe_seconds=.05, interval=.02)

    def test_client_rejects_duplicate_keys_nonfinite_and_oversize_json(self):
        payloads = [b'{"status":"live","status":"failed"}', b'{"x":NaN}',
                    b'{"x":1e9999}', b'[]', b'[' * 3000 + b']' * 3000,
                    b'{"x":"' + b'a' * (1024 * 1024) + b'"}']
        for payload in payloads:
            with self.subTest(prefix=payload[:30]), fixture_server(lambda _: payload) as url:
                with self.assertRaises(ValueError):
                    check_image.read_state(url)

    def test_client_reads_only_the_state_endpoint_and_rejects_credential_urls(self):
        self.assertTrue(callable(getattr(check_image, 'read_state', None)),
                        'the bounded acceptance HTTP client is missing')
        paths = []
        def response(path):
            paths.append(path)
            return json.dumps(state()).encode()
        with fixture_server(response) as url:
            self.assertEqual(check_image.read_state(url)['frame']['seq'], 10)
        self.assertEqual(paths, ['/api/state'])
        for url in ['http://name:secret@localhost', 'file:///data/state',
                    'https://localhost/other', 'http://localhost?key=value']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                check_image.read_state(url)


if __name__ == '__main__':
    unittest.main()
