from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core
from run_guard import RuntimeGuard, RuntimeBusy


class RunPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def runner(self):
        from run_history import RunHistory
        return core.Runner(guard=RuntimeGuard(), history=RunHistory(self.root / 'runs'))

    def done(self, runner, sid):
        self.assertTrue(runner.sessions[sid]['done_event'].wait(10))

    def test_restart_keeps_logs_result_and_current_file_identity(self):
        runner = self.runner()
        product = self.root / 'result.txt'
        product.write_text('first', encoding='utf-8')
        import hashlib
        result = {'verdict': 'success', 'files': [{'path': str(product), 'rel': product.name}],
                  'artifacts': {'checked': [{'path': str(product), 'size': 5,
                    'sha256': hashlib.sha256(b'first').hexdigest()}]}}
        sid = runner.start([sys.executable, '-u', '-c', 'print("one");print("two");print("three")'],
                           str(self.root), 'fixture', context={'project': str(self.root), 'func': 'pred'},
                           finalize=lambda *a, **k: result)
        self.done(runner, sid)
        restarted = self.runner()
        page = restarted.output(sid, 1, limit=1)
        self.assertEqual(page['lines'], ['two'])
        self.assertEqual(page['next_since'], 2)
        self.assertTrue(page['has_more'])
        with patch.object(core, 'RUNNER', restarted):
            report = core.session_results(sid)
        self.assertEqual(report['historical_verdict'], 'success')
        self.assertEqual(report['current_files']['status'], 'matched')
        product.write_text('overwritten', encoding='utf-8')
        with patch.object(core, 'RUNNER', restarted):
            report = core.session_results(sid)
        self.assertEqual(report['historical_verdict'], 'success')
        self.assertEqual(report['current_files']['status'], 'changed')

    def test_removed_current_output_does_not_inherit_historical_exists(self):
        runner = self.runner()
        output = self.root / 'output'
        output.mkdir()
        self.assertTrue(output.is_dir())
        runner.history.create(91, 'fixture', {'out_dir': str(output)}, [], str(self.root))
        runner.history.finish(91, 'done', 0, {'verdict': 'success', 'exists': True})
        output.rmdir()
        with patch.object(core, 'RUNNER', runner):
            report = core.session_results(91)
        self.assertEqual(report['historical_verdict'], 'success')
        self.assertFalse(report['exists'])

    def test_history_creation_failure_prevents_process_start(self):
        runner = self.runner()
        with patch.object(runner.history, 'create', side_effect=OSError('disk full')), \
                patch.object(core, 'ManagedProcess') as process:
            with self.assertRaises(OSError):
                runner.start(['unused'], str(self.root), 'fixture')
        process.assert_not_called()
        self.assertFalse(runner.guard.snapshot()['busy'])

    def test_only_build_passes_selected_toolchain_for_helper_cleanup(self):
        for operation in ('build', 'doctor', 'run'):
            runner = core.Runner(guard=RuntimeGuard())
            context = {'operation': operation, 'project_config': {'VS_ROOT': 'selected-vs'}}
            with patch.object(core, 'ManagedProcess', side_effect=OSError('fixture no spawn')) as process:
                with self.assertRaises(OSError):
                    runner.start(['unused'], str(self.root), 'fixture', context=context)
            if operation == 'build':
                self.assertEqual(process.call_args.kwargs.get('build_toolchain_root'), 'selected-vs')
            else:
                self.assertNotIn('build_toolchain_root', process.call_args.kwargs)

    def test_required_xml_snapshot_failure_prevents_process_start(self):
        runner = self.runner()
        with patch.object(core, 'ManagedProcess') as process:
            with self.assertRaisesRegex(OSError, '快照'):
                runner.start(['unused'], str(self.root), 'fixture',
                             context={'schema_path': str(self.root / 'missing.xml')})
        process.assert_not_called()
        record = runner.history.list()[0]
        self.assertEqual(record['result']['verdict'], 'failed')
        self.assertFalse(runner.guard.snapshot()['busy'])

    def test_xml_changed_after_preflight_is_not_started_as_verified_input(self):
        runner = self.runner()
        schema = self.root / 'task.xml'
        schema.write_bytes(b'<new-input/>')
        import hashlib
        digest = hashlib.sha256(b'<checked-input/>').hexdigest()
        with patch.object(core, 'ManagedProcess') as process:
            with self.assertRaisesRegex(OSError, '快照'):
                runner.start(['unused'], str(self.root), 'fixture',
                             context={'schema_path': str(schema), 'schema_digest': digest})
        process.assert_not_called()
        self.assertEqual(runner.history.list()[0]['result']['verdict'], 'failed')

    def test_spawn_failure_is_recorded_and_releases_guard(self):
        runner = self.runner()
        with self.assertRaises(OSError):
            runner.start(['missing-p2-fixture-executable'], str(self.root), 'fixture')
        records = runner.history.list()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['status'], 'done')
        self.assertEqual(records[0]['result']['verdict'], 'failed')
        self.assertFalse(runner.guard.snapshot()['busy'])

    def test_archive_finalization_keeps_resource_lease(self):
        runner = self.runner()
        entered, finish = threading.Event(), threading.Event()
        self.addCleanup(finish.set)
        real_finish = runner.history.finish
        def archive(*args, **kwargs):
            entered.set()
            finish.wait(5)
            return real_finish(*args, **kwargs)
        with patch.object(runner.history, 'finish', side_effect=archive):
            sid = runner.start([sys.executable, '-c', 'pass'], str(self.root), 'fixture')
            self.assertTrue(entered.wait(5))
            self.assertEqual(runner.guard.snapshot()['phase'], 'finalizing')
            self.assertFalse(runner.sessions[sid]['done_event'].is_set())
            finish.set()
            self.done(runner, sid)
        self.assertFalse(runner.guard.snapshot()['busy'])

    def test_failed_log_persistence_never_reports_success(self):
        runner = self.runner()
        with patch.object(runner.history, 'append', side_effect=OSError('disk full')):
            sid = runner.start([sys.executable, '-u', '-c', 'print("line")'], str(self.root), 'fixture')
            self.done(runner, sid)
        output = runner.output(sid, 0)
        self.assertNotEqual(output['result']['verdict'], 'success')
        self.assertIn('disk full', output['internal_error'])
        self.assertFalse(runner.guard.snapshot()['busy'])

    def test_failed_history_finish_releases_but_reports_failure(self):
        runner = self.runner()
        with patch.object(runner.history, 'finish', side_effect=OSError('archive full')):
            sid = runner.start([sys.executable, '-c', 'pass'], str(self.root), 'fixture')
            self.done(runner, sid)
        output = runner.output(sid, 0)
        self.assertNotEqual(output['result']['verdict'], 'success')
        self.assertIn('archive full', output['internal_error'])
        self.assertFalse(runner.guard.snapshot()['busy'])


class CrossInstanceGuardTests(unittest.TestCase):
    def test_same_bin_and_output_are_reserved_until_final_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = {'bin_dir': str(Path(tmp) / 'Bin'), 'out_dir': str(Path(tmp) / 'out')}
            first, second = RuntimeGuard(), RuntimeGuard()
            with first.operation('first') as token:
                first.acquire_resources(token, ctx)
                first.bind(token, 77, ctx)
            self.addCleanup(lambda: first.release(token))
            with self.assertRaises(RuntimeBusy) as raised:
                with second.operation('second') as other:
                    second.acquire_resources(other, ctx)
            self.assertTrue(raised.exception.owner['external'])
            self.assertTrue(second.external_snapshot(ctx)['busy'])
            first.release(token)
            self.assertFalse(second.external_snapshot(ctx)['busy'])
            with second.operation('allowed') as other:
                second.acquire_resources(other, ctx)

    def test_shared_output_blocks_different_bin_and_acquire_failure_releases(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = RuntimeGuard(), RuntimeGuard()
            ctx = {'bin_dir': str(Path(tmp) / 'Bin1'), 'out_dir': str(Path(tmp) / 'out')}
            with first.operation('first') as token:
                first.acquire_resources(token, ctx)
                with self.assertRaises(RuntimeBusy):
                    with second.operation('second') as other:
                        second.acquire_resources(other, dict(ctx, bin_dir=str(Path(tmp) / 'Bin2')))
                self.assertFalse(second.snapshot()['busy'])
            self.assertFalse(first.snapshot()['busy'])


if __name__ == '__main__':
    unittest.main()
