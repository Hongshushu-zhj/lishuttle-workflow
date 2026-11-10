from contextlib import redirect_stdout
import importlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'platform/backend'))


class LocalRunTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('run_local'), '缺少受管本地运行入口')
        self.cli = importlib.import_module('run_local')
        self.temp = tempfile.TemporaryDirectory(prefix='本地 运行-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.job = self.root / '任务 单.env'
        self.job.write_text('FUNC="pred"\nSCHEMA_NAME="任务.xml"\n', encoding='utf-8')
        self.schema = self.root / '任务.xml'
        self.schema.write_text('old complete schema', encoding='utf-8')
        self.env = {'PROJECT_DIR': str(self.root), 'BUILD_SUBDIR': 'build',
                    'EXE_NAME': 'fixture.exe', 'OUT_ROOT': str(self.root / 'out')}
        self.table = dict(self.env, EXE_DIR=str(self.root / 'build/Bin'),
                          FUNC='pred', TASK_ID='7', SCHEMA_NAME='任务.xml', JOB_NAME='fixture')
        self.lines = []
        self.output = io.StringIO()
        self.patch(self.cli, 'load_local', return_value=self.env)
        self.patch(self.cli, 'build_table', side_effect=lambda *args, **kw: dict(self.table))
        self.start = self.patch(self.cli.core, 'start_lishuttle', return_value=(17, 'fixture.exe'))
        self.render = self.patch(self.cli.core, 'run_render', return_value={
            'generated': True, 'status': 'ready', 'exit_code': 0, 'output': '渲染完成'})
        self.report = self.patch(self.cli.core.RUNNER, 'output', side_effect=lambda *args, **kwargs: {
            'status': 'done', 'exit': 0, 'lines': ['fixture log'], 'total': 1,
            'result': {'verdict': 'success'}})
        self.stop = self.patch(self.cli.core.RUNNER, 'stop', return_value=True)
        self.shutdown = self.patch(self.cli.core.RUNNER, 'shutdown')
        self.patch(self.cli.time, 'sleep')

    def patch(self, target, name, **kwargs):
        patcher = patch.object(target, name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def run_cli(self, *args):
        with redirect_stdout(self.output):
            return self.cli.main([str(self.job), *args])

    def test_success_uses_shared_runner_and_prints_log(self):
        self.assertEqual(self.run_cli('--no-render'), 0)
        self.start.assert_called_once_with('任务.xml', 'pred', '7')
        self.assertIn('fixture log', self.output.getvalue())
        self.assertIn('验证成功', self.output.getvalue())
        self.report.assert_called_once_with(17, 0, limit=500)

    def test_process_exit_code_is_preserved(self):
        self.report.side_effect = None
        self.report.return_value = {'status': 'done', 'exit': 23, 'lines': [], 'total': 0,
                                    'result': {'verdict': 'failed'}}
        self.assertEqual(self.run_cli('--no-render'), 23)

    def test_zero_process_exit_does_not_hide_failed_or_unconfirmed_business(self):
        for verdict in ('failed', 'unconfirmed', 'stale'):
            with self.subTest(verdict=verdict):
                self.report.side_effect = None
                self.report.return_value = {'status': 'done', 'exit': 0, 'lines': [], 'total': 0,
                                            'result': {'verdict': verdict}}
                self.assertEqual(self.run_cli('--no-render'), self.cli.BUSINESS_FAILURE)

    def test_render_failure_rolls_back_and_does_not_run_old_schema(self):
        def fail_render(job, transaction=None):
            transaction.write(self.schema, b'partial new schema')
            return {'generated': False, 'status': 'failed', 'exit_code': 9, 'output': '失败'}
        self.render.side_effect = fail_render
        self.assertEqual(self.run_cli(), 9)
        self.start.assert_not_called()
        self.assertEqual(self.schema.read_text(encoding='utf-8'), 'old complete schema')

    def test_zero_exit_without_generation_receipt_stops(self):
        self.render.return_value = {'generated': False, 'status': 'failed', 'exit_code': 0, 'output': ''}
        self.assertEqual(self.run_cli(), self.cli.CONFIGURATION_FAILURE)
        self.start.assert_not_called()

    def test_no_render_and_job_switch_skip_render(self):
        self.assertEqual(self.run_cli('--no-render'), 0)
        self.table['RENDER_BEFORE_RUN'] = '0'
        self.assertEqual(self.run_cli(), 0)
        self.render.assert_not_called()

    def test_missing_inputs_are_generated_then_rejected_by_shared_preflight(self):
        self.render.return_value = {'generated': True, 'status': 'missing_inputs', 'exit_code': 1,
                                    'output': '输入缺失'}
        self.start.side_effect = self.cli.core.PreflightRejected({
            'ok': False, 'issues': [{'severity': 'error', 'message': '缺少工参'}]})
        self.assertEqual(self.run_cli(), self.cli.CONFIGURATION_FAILURE)
        self.start.assert_called_once()
        self.assertIn('缺少工参', self.output.getvalue())

    def test_configuration_is_frozen_for_shared_core_and_restored_afterwards(self):
        before = self.cli.core.PROJECT_CONTEXT.get()
        def start(*args):
            self.assertEqual(self.cli.core.load_env(), self.env)
            return 17, 'fixture.exe'
        self.start.side_effect = start
        self.assertEqual(self.run_cli('--no-render', '--project', str(self.root)), 0)
        self.assertIs(self.cli.core.PROJECT_CONTEXT.get(), before)
        self.cli.load_local.assert_called_once_with(self.cli.core.ENV_FILE, project=str(self.root))

    def test_cancel_waits_for_finalization_and_drains_all_log_pages(self):
        self.report.side_effect = [KeyboardInterrupt(),
            {'status': 'cancelling', 'exit': None, 'lines': ['stopping'], 'total': 3, 'next': 1},
            {'status': 'done', 'exit': 0, 'lines': ['archive'], 'total': 3, 'next': 2,
             'result': {'verdict': 'cancelled'}},
            {'status': 'done', 'exit': 0, 'lines': ['complete'], 'total': 3, 'next': 3,
             'result': {'verdict': 'cancelled'}}]
        self.assertEqual(self.run_cli('--no-render'), 130)
        self.stop.assert_called_once_with(17)
        self.assertIn('complete', self.output.getvalue())
        self.assertEqual(self.report.call_count, 4)

    def test_multiple_schemas_are_explicitly_rejected_without_side_effects(self):
        self.table['SCHEMA_NAME'] = 'a.xml,b.xml'
        self.assertEqual(self.run_cli(), self.cli.CONFIGURATION_FAILURE)
        self.render.assert_not_called()
        self.start.assert_not_called()

    def test_unknown_session_fails_without_claiming_success(self):
        self.report.side_effect = None
        self.report.return_value = {'error': '会话不存在'}
        self.assertNotEqual(self.run_cli('--no-render'), 0)

    def test_cancel_retries_a_temporary_stop_failure_until_finalization(self):
        self.report.side_effect = [KeyboardInterrupt(),
            {'status': 'running', 'exit': None, 'lines': [], 'total': 0},
            {'status': 'done', 'exit': 0, 'lines': [], 'total': 0,
             'result': {'verdict': 'cancelled'}}]
        self.stop.side_effect = [OSError('temporary stop failure'), True]
        self.assertEqual(self.run_cli('--no-render'), 130)
        self.assertEqual(self.stop.call_count, 2)

    def test_render_cannot_modify_runtime_used_by_another_process(self):
        from resource_lock import ResourceLease
        with ResourceLease([self.table['EXE_DIR']]):
            self.assertEqual(self.run_cli(), self.cli.CONFIGURATION_FAILURE)
        self.render.assert_not_called()
        self.start.assert_not_called()

    def test_all_exception_paths_wait_for_managed_shutdown(self):
        self.report.side_effect = OSError('console unavailable')
        self.assertEqual(self.run_cli('--no-render'), self.cli.CONFIGURATION_FAILURE)
        self.shutdown.assert_called_once()

    def test_archive_path_and_partial_evidence_are_reported(self):
        self.report.side_effect = None
        self.report.return_value = {'status': 'done', 'exit': 0, 'lines': [], 'total': 0,
                                    'result': {'verdict': 'success'},
                                    'archive': {'dir': str(self.root / 'history/17'), 'status': 'partial'}}
        self.assertEqual(self.run_cli('--no-render'), 0)
        self.assertIn(str(self.root / 'history/17'), self.output.getvalue())
        self.assertIn('归档不完整', self.output.getvalue())


@unittest.skipUnless(os.name == 'nt', 'Windows batch entry point')
class LocalRunBatchTests(unittest.TestCase):
    def test_batch_forwards_arguments_and_exit_status(self):
        with tempfile.TemporaryDirectory(prefix='本地 入口-') as directory:
            root = Path(directory)
            (root / 'run_local.bat').write_bytes((ROOT / 'scripts/run_local.bat').read_bytes())
            (root / 'run_local.py').write_text(
                'import sys\nprint(repr(sys.argv[1:]), flush=True)\nraise SystemExit(27)\n',
                encoding='utf-8')
            result = subprocess.run(['cmd', '/d', '/c', 'run_local.bat', '任务 单.env',
                                     '--no-render', '--project', '项目 ! 空间'],
                                    cwd=root, capture_output=True, encoding='utf-8', errors='replace')
            self.assertEqual(result.returncode, 27, result.stdout + result.stderr)
            self.assertIn('任务 单.env', result.stdout)
            self.assertIn('项目 ! 空间', result.stdout)


class LocalRunManagedIntegrationTests(unittest.TestCase):
    def test_controlled_process_logs_exit_and_history_survive_cli_completion(self):
        import run_local
        from managed_process import ManagedProcess
        from run_guard import RuntimeGuard
        from run_history import RunHistory
        with tempfile.TemporaryDirectory(prefix='本地 归档-') as directory:
            root = Path(directory)
            binary = root / 'build/Bin'
            schema = binary / 'runtimelibrary/task.xml'
            schema.parent.mkdir(parents=True)
            schema.write_text('<RuntimeSchema name="task"/>', encoding='utf-8')
            job = root / '任务.env'
            job.write_text('FUNC="fixture"\nSCHEMA_NAME="task.xml"\n', encoding='utf-8')
            env = {'PROJECT_DIR': str(root), 'BUILD_SUBDIR': 'build',
                   'EXE_NAME': 'controlled.exe', 'OUT_ROOT': str(root / 'out')}
            table = dict(env, EXE_DIR=str(binary), FUNC='fixture', SCHEMA_NAME='task.xml')
            history = RunHistory(root / 'history')
            guard = RuntimeGuard()
            runner = run_local.core.Runner(guard=guard, history=history)
            context = {'project': str(root), 'bin_dir': str(binary), 'schema_name': 'task.xml',
                       'out_dir': str(root / 'out/task'), 'exe': str(binary / 'controlled.exe'),
                       'func': 'fixture', 'task_id': '0'}
            child_code = '[print("line-"+str(i)) for i in range(530)];raise SystemExit(19)'
            def controlled_process(cmd, cwd, env=None):
                return ManagedProcess([sys.executable, '-u', '-c', child_code], cwd, env=env)
            output = io.StringIO()
            with patch.object(run_local, 'load_local', return_value=env), \
                    patch.object(run_local, 'build_table', return_value=table), \
                    patch.object(run_local.core, 'RUNTIME', guard), \
                    patch.object(run_local.core, 'RUNNER', runner), \
                    patch.object(run_local.core, 'check_run', return_value={
                        'ok': True, 'issues': [], 'context': context}), \
                    patch.object(run_local.core, 'ManagedProcess', side_effect=controlled_process), \
                    redirect_stdout(output):
                self.assertEqual(run_local.main([str(job), '--no-render']), 19)
            self.assertIn('line-529', output.getvalue())
            self.assertFalse(guard.snapshot()['busy'])
            records = RunHistory(root / 'history').list()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]['status'], 'done')
            self.assertEqual(records[0]['exit'], 19)
            self.assertEqual(records[0]['result']['verdict'], 'failed')
            self.assertEqual(history.output(records[0]['sid'], since=529)['lines'], ['line-529'])
            self.assertEqual(records[0]['context']['project_config'], env)
            self.assertTrue(any(item['kind'] == 'schema' for item in records[0]['snapshots']))


if __name__ == '__main__':
    unittest.main()
