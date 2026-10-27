"""Malformed local HTTP fixtures exercise report replacement, not native execution."""
import contextlib
import http.client
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_acceptance_http import fixture_server
from test_customer_acceptance import module
from test_customer_observation import Clock, REVISION


class CustomerHttpTests(unittest.TestCase):
    def run_main(self, check, url, directory):
        target = Path(directory) / 'report.json'
        old = {'passed': True, 'old': 'test fixture'}
        target.write_text(json.dumps(old))
        clock = Clock()
        def sleep(_):
            clock.now += 10
        args = ['check', '--url', url, '--expected-revision', REVISION,
                '--seconds', '10', '--report', str(target)]
        with target.open() as old_handle, patch('sys.argv', args), \
                patch.object(check.time, 'monotonic', side_effect=lambda: clock.now), \
                patch.object(check.time, 'sleep', side_effect=sleep), \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = check.main()
            self.assertNotEqual(code, 0)
            report = json.loads(target.read_text())
            self.assertFalse(report['passed'])
            self.assertEqual(json.loads(stdout.getvalue()), report)
            self.assertEqual(json.load(old_handle), old, 'report must be atomically replaced')
        self.assertEqual(list(Path(directory).iterdir()), [target])
        return report

    def test_cli_transport_errors_replace_previous_pass_atomically(self):
        payloads = [
            b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nINVALID\r\n',
            b'HTTP/1.1 200 OK\r\nX-Test: ' + b'x' * 65537 + b'\r\n\r\n',
            b'HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n{}',
        ]
        for payload in payloads:
            with self.subTest(prefix=payload[:65]), tempfile.TemporaryDirectory() as directory, \
                    fixture_server(lambda _: payload, raw=True) as url:
                report = self.run_main(module(), url, directory)
                self.assertTrue(report.get('error') or report.get('errors'))

    def test_main_numeric_recursion_and_protocol_failures_replace_previous_pass(self):
        for error in (OverflowError('huge number'), RecursionError('deep input'),
                      http.client.IncompleteRead(b'{}', 100), http.client.HTTPException('bad HTTP')):
            check = module()
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as directory, \
                    patch.object(check, 'observe', side_effect=error):
                self.run_main(check, 'http://localhost', directory)

    def test_reader_and_cli_reject_duplicate_nonfinite_deep_and_oversized_json(self):
        payloads = [b'{"status":"live","status":"failed"}', b'{"x":NaN}',
                    b'{"x":' + b'9' * 1000 + b'}',
                    b'{"x":1e9999}', b'{"x":' + b'[' * 3000 + b']' * 3000 + b'}',
                    b'{"x":"' + b'x' * (8 * 1024 * 1024) + b'"}']
        for payload in payloads:
            with self.subTest(prefix=payload[:40]), tempfile.TemporaryDirectory() as directory, \
                    fixture_server(lambda _: payload) as url:
                check = module()
                with self.assertRaises(ValueError):
                    check.read_json(url, '/api/telemetry')
                report = self.run_main(check, url, directory)
                self.assertTrue(report.get('error') or report.get('errors'))

    def test_reader_rejects_truncated_body_even_if_json_is_complete(self):
        payload = b'HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n{}'
        with fixture_server(lambda _: payload, raw=True) as url:
            with self.assertRaises(http.client.IncompleteRead):
                module().read_json(url, '/api/telemetry')

    def test_huge_integer_finite_check_fails_closed(self):
        self.assertFalse(module().finite(10 ** 1000))
