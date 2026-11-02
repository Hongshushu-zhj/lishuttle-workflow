from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core
from run_guard import RuntimeBusy, RuntimeGuard


class RuntimeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.guard = RuntimeGuard()
        self.runner = core.Runner(guard=self.guard)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def start(self, code, **kwargs):
        return self.runner.start([sys.executable, '-u', '-c', code], self.temp.name, 'fixture', **kwargs)

    def until(self, predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            threading.Event().wait(.02)
        self.fail('managed fixture did not reach expected state')

    def test_exit_code_is_preserved_and_lease_released(self):
        sid = self.start('print("fixture"); raise SystemExit(7)')
        self.until(lambda: self.runner.output(sid, 0)['status'] == 'done')
        report = self.runner.output(sid, 0)
        self.assertEqual(report['exit'], 7)
        self.assertIn('fixture', report['lines'])
        self.assertEqual(report['result']['verdict'], 'failed')
        self.assertFalse(self.guard.snapshot()['busy'])

    def test_result_finalization_retains_lease_and_duplicate_start_fails(self):
        entered, finish = threading.Event(), threading.Event()
        self.addCleanup(finish.set)
        def finalize(*args, **kwargs):
            entered.set()
            finish.wait(5)
            return {'verdict': 'unconfirmed'}
        sid = self.start('print("done")', finalize=finalize, context={'func': 'pred'})
        self.assertTrue(entered.wait(5))
        self.assertEqual(self.guard.snapshot()['phase'], 'finalizing')
        with self.assertRaises(RuntimeBusy):
            self.start('print("must not execute")')
        finish.set()
        self.until(lambda: self.runner.output(sid, 0)['status'] == 'done')
        self.assertFalse(self.guard.snapshot()['busy'])

    def test_spawn_failure_and_validator_exception_release_lease(self):
        with self.assertRaises(OSError):
            self.runner.start(['nonexistent-p0-fixture-executable'], self.temp.name, 'bad')
        self.assertFalse(self.guard.snapshot()['busy'])
        def fail(*args, **kwargs):
            raise ValueError('fixture validation failure')
        sid = self.start('pass', finalize=fail, context={'func': 'pred'})
        self.until(lambda: self.runner.output(sid, 0)['status'] == 'done')
        report = self.runner.output(sid, 0)
        self.assertEqual(report['exit'], 0)
        self.assertNotEqual(report['result']['verdict'], 'success')
        self.assertIn('fixture validation failure', report['internal_error'])
        self.assertFalse(self.guard.snapshot()['busy'])

    def test_cancel_manages_child_even_after_parent_exits(self):
        code = ('import subprocess,sys; '
                'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"], '
                'stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); '
                'print("CHILD",p.pid,flush=True)')
        sid = self.start(code)
        self.addCleanup(lambda: self.runner.stop(sid))
        self.until(lambda: any(line.startswith('CHILD ') for line in self.runner.output(sid, 0)['lines']))
        threading.Event().wait(.1)
        self.assertTrue(self.guard.snapshot()['busy'])
        self.assertTrue(self.runner.stop(sid))
        self.until(lambda: self.runner.output(sid, 0)['status'] == 'done')
        self.assertEqual(self.runner.output(sid, 0)['result']['verdict'], 'cancelled')
        self.assertFalse(self.guard.snapshot()['busy'])
        self.assertFalse(self.runner.stop(sid))

    def test_session_ids_do_not_alias_after_runner_restart(self):
        first = self.start('pass')
        self.until(lambda: self.runner.output(first, 0)['status'] == 'done')
        other = core.Runner(guard=self.guard)
        second = other.start([sys.executable, '-c', 'pass'], self.temp.name, 'fixture')
        self.until(lambda: other.output(second, 0)['status'] == 'done')
        self.assertNotEqual(first, second, '旧页面不能把重启后的其他运行当作原会话')

    def test_failed_termination_can_be_retried_without_early_release(self):
        sid = self.start('import time; time.sleep(30)')
        self.addCleanup(lambda: self.runner.stop(sid))
        tree = self.runner.sessions[sid]['tree']
        with patch.object(tree, 'terminate', side_effect=OSError('fixture stop failed')):
            with self.assertRaises(OSError):
                self.runner.stop(sid)
        self.assertTrue(self.guard.snapshot()['busy'])
        self.assertFalse(self.runner.output(sid, 0)['cancelled'])
        self.assertTrue(self.runner.stop(sid))
        self.until(lambda: self.runner.output(sid, 0)['status'] == 'done')

    def test_log_read_error_terminates_tree_and_reports_diagnostic(self):
        real_tree = core.ManagedProcess
        def broken_log(*args, **kwargs):
            tree = real_tree(*args, **kwargs)
            stream = tree.proc.stdout
            class BadStream:
                def __iter__(self):
                    raise OSError('fixture log broken')
                def close(self):
                    stream.close()
            tree.proc.stdout = BadStream()
            return tree
        with patch.object(core, 'ManagedProcess', side_effect=broken_log):
            sid = self.start('import time; time.sleep(30)')
        self.until(lambda: self.runner.output(sid, 0)['status'] == 'done')
        report = self.runner.output(sid, 0)
        self.assertIn('fixture log broken', report['internal_error'])
        self.assertNotEqual(report['result']['verdict'], 'success')
        self.assertFalse(self.guard.snapshot()['busy'])

    def test_handle_close_error_after_confirmed_exit_still_releases(self):
        real_tree = core.ManagedProcess
        def broken_close(*args, **kwargs):
            tree = real_tree(*args, **kwargs)
            close = tree.close
            def fail():
                close()
                raise OSError('fixture handle close failed')
            tree.close = fail
            return tree
        with patch.object(core, 'ManagedProcess', side_effect=broken_close):
            sid = self.start('pass')
        self.until(lambda: self.runner.output(sid, 0)['status'] == 'done')
        report = self.runner.output(sid, 0)
        self.assertIn('fixture handle close failed', report['internal_error'])
        self.assertNotEqual(report['result']['verdict'], 'success')
        self.assertFalse(self.guard.snapshot()['busy'])

    def test_shutdown_waits_for_finalization_before_returning(self):
        entered, finish, returned = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(finish.set)
        def finalize(*args, **kwargs):
            entered.set()
            finish.wait(5)
            return {'verdict':'unconfirmed'}
        sid = self.start('pass', finalize=finalize)
        self.assertTrue(entered.wait(5))
        worker = threading.Thread(target=lambda: (self.runner.shutdown(), returned.set()))
        worker.start()
        try:
            self.assertFalse(returned.wait(.1), '服务关闭须等待收尾线程释放占用')
        finally:
            finish.set()
            worker.join(5)
        self.assertTrue(returned.is_set())
        self.assertEqual(self.runner.output(sid, 0)['status'], 'done')
        self.assertFalse(self.guard.snapshot()['busy'])

    def test_monitor_start_failure_with_termination_retry_can_be_recovered(self):
        real_tree = core.ManagedProcess
        def fail_once(*args, **kwargs):
            tree = real_tree(*args, **kwargs)
            terminate = tree.terminate
            attempts = []
            def stop():
                attempts.append(1)
                if len(attempts) == 1:
                    raise OSError('fixture initial termination failed')
                terminate()
            tree.terminate = stop
            return tree
        with patch.object(core, 'ManagedProcess', side_effect=fail_once), \
                patch.object(threading.Thread, 'start', side_effect=RuntimeError('fixture monitor unavailable')):
            with self.assertRaises(Exception):
                self.start('import time; time.sleep(30)')
        self.assertTrue(self.guard.snapshot()['busy'])
        sid = self.guard.snapshot()['sid']
        self.addCleanup(lambda: self.runner.stop(sid))
        self.assertTrue(self.runner.stop(sid))
        self.until(lambda: self.runner.output(sid, 0)['status'] == 'done')
        self.assertFalse(self.guard.snapshot()['busy'])


if __name__ == '__main__':
    unittest.main()
