"""Failure injection for the disposable desktop acceptance harness cleanup."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


spec = importlib.util.spec_from_file_location('packaged_toolkit_acceptance',
    Path(__file__).with_name('desktop_packaged_toolkit.py'))
toolkit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(toolkit)


class AcceptanceCleanupTests(unittest.TestCase):
    def test_cleanup_preserves_evidence_and_attempts_owner_close_after_each_failure(self):
        cleanup = getattr(toolkit, 'cleanup_service', None)
        self.assertTrue(callable(cleanup), 'Acceptance cleanup must survive individual cleanup failures')
        for broken in ('stdin', 'wait', 'terminate', 'owner', 'stdout', 'stderr', None):
            with self.subTest(broken=broken), tempfile.TemporaryDirectory() as temporary:
                events = []

                class Pipe:
                    closed = False

                    def __init__(self, name):
                        self.name = name

                    def close(self):
                        events.append(self.name)
                        if self.name == broken:
                            raise BrokenPipeError(self.name)
                        self.closed = True

                class Process:
                    stdin, stdout, stderr = (Pipe(name) for name in ('stdin', 'stdout', 'stderr'))
                    waits = 0

                    def poll(self):
                        return None

                    def wait(self, timeout):
                        self.waits += 1
                        events.append('wait')
                        if broken in ('wait', 'terminate') and self.waits == 1:
                            raise subprocess.TimeoutExpired('fixture', timeout)
                        return 0

                class Owner:
                    def terminate(self):
                        events.append('terminate')
                        if broken == 'terminate':
                            raise OSError('terminate')

                    def close(self):
                        events.append('owner')
                        if broken == 'owner':
                            raise OSError('owner')

                output = Path(temporary)
                evidence = dict(status='passed')
                issues = cleanup(Owner(), Process(), evidence, output, ['service evidence\n'])
                saved = json.loads((output / 'packaged-toolkit.json').read_text(encoding='utf-8'))
                self.assertIn('owner', events)
                self.assertIn('stdout', events)
                self.assertIn('stderr', events)
                self.assertEqual((output / 'toolkit-service.log').read_text(encoding='utf-8'), 'service evidence\n')
                self.assertEqual(saved['status'], 'failed' if broken else 'passed')
                self.assertEqual(bool(issues), bool(broken))
                if broken in ('wait', 'terminate'):
                    self.assertIn('terminate', events)


if __name__ == '__main__':
    unittest.main()
