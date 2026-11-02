from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))


class RuntimeGuardTests(unittest.TestCase):
    def guard(self):
        import run_guard
        self.assertTrue(hasattr(run_guard, 'RuntimeGuard'))
        return run_guard.RuntimeGuard()

    def test_duplicate_and_foreign_thread_edits_are_rejected(self):
        guard = self.guard()
        results = []
        with guard.operation('pred', {'project': 'fixture', 'bin_dir': 'fixture/Bin', 'schema_text':'private input'}) as token:
            def other():
                try:
                    with guard.operation('write'):
                        results.append('incorrectly allowed')
                except Exception as exc:
                    results.append(exc.code)
            worker = threading.Thread(target=other)
            worker.start()
            worker.join()
            self.assertEqual(results, ['RUNTIME_BUSY'])
            self.assertTrue(guard.snapshot()['busy'])
            self.assertEqual(guard.snapshot()['label'], 'pred')
            self.assertNotIn('schema_text', guard.snapshot())
            with guard.operation('nested') as nested:
                self.assertEqual(nested, token)
        self.assertFalse(guard.snapshot()['busy'])

    def test_handoff_retains_until_token_owner_releases(self):
        guard = self.guard()
        with guard.operation('pred') as token:
            guard.bind(token, 4)
        self.assertTrue(guard.snapshot()['busy'])
        self.assertEqual(guard.snapshot()['sid'], 4)
        self.assertFalse(guard.release('stale'))
        guard.set_phase(token, 'finalizing')
        self.assertEqual(guard.snapshot()['phase'], 'finalizing')
        self.assertTrue(guard.release(token))
        self.assertFalse(guard.snapshot()['busy'])

    def test_preparation_exception_releases_occupancy(self):
        guard = self.guard()
        with self.assertRaisesRegex(ValueError, 'bad input'):
            with guard.operation('preparing'):
                raise ValueError('bad input')
        self.assertFalse(guard.snapshot()['busy'])


if __name__ == '__main__':
    unittest.main()
