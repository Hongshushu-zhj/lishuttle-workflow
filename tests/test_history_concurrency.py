from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core
from run_guard import RuntimeGuard
from run_history import RunHistory


class HistoryConcurrencyTests(unittest.TestCase):
    def test_historical_file_scan_does_not_block_current_run_cancellation(self):
        self.assert_io_does_not_block_cancel('results')

    def test_historical_log_page_does_not_block_current_run_cancellation(self):
        self.assert_io_does_not_block_cancel('output')

    def assert_io_does_not_block_cancel(self, operation):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            history = RunHistory(root / 'runs')
            history.create(1, 'old run', {'project': str(root)}, [], str(root))
            history.finish(1, 'done', 0, {'verdict': 'success'})
            guard = RuntimeGuard()
            runner = core.Runner(guard=guard, history=history)
            stopped, scanning, release_scan = threading.Event(), threading.Event(), threading.Event()

            class Tree:
                def terminate(self):
                    stopped.set()

            with guard.operation('current run') as token:
                guard.bind(token, 2)
            self.addCleanup(lambda: guard.release(token))
            runner.sessions[2] = {'status': 'running', 'exit': None, 'context': {'project': str(root)},
                                  'label': 'current run', 'lines': [], 'result': None,
                                  'cancelled': False, 'token': token, 'tree': Tree(), 'internal_error': ''}

            def scan(*args, **kwargs):
                scanning.set()
                release_scan.wait(5)
                return {'status': 'unconfirmed', 'files': []}

            errors = []
            def read_results():
                try:
                    if operation == 'results':
                        core.session_results(1)
                    else:
                        runner.output(1, limit=500)
                except BaseException as error:
                    errors.append(error)

            scan_method = 'current' if operation == 'results' else 'output'
            with patch.object(core, 'RUNNER', runner), patch.object(history, scan_method, side_effect=scan):
                reader = threading.Thread(target=read_results)
                reader.start()
                self.assertTrue(scanning.wait(3), '历史摘要扫描没有开始')
                cancel = threading.Thread(target=lambda: runner.stop(2))
                cancel.start()
                try:
                    self.assertTrue(stopped.wait(1), '历史文件扫描期间，当前任务仍须可以取消')
                finally:
                    release_scan.set()
                    reader.join(5)
                    cancel.join(5)
            self.assertFalse(reader.is_alive())
            self.assertFalse(cancel.is_alive())
            self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
