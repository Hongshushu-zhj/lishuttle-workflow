from pathlib import Path
from types import SimpleNamespace
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core
from run_guard import RuntimeGuard


class BuildDiagnosticsTests(unittest.TestCase):
    def runner(self):
        runner = core.Runner(guard=RuntimeGuard())
        tree = SimpleNamespace(cleanup_error='编译辅助进程收尾未完成：fixture query failure')
        runner.sessions[42] = {'tree': tree, 'lines': ['BUILD COMPLETE'], 'status': 'running',
                               'exit': None, 'label': 'build', 'context': {'operation': 'build'},
                               'result': None, 'cancelled': False, 'internal_error': 'persistent warning'}
        return runner, tree

    def test_build_helper_diagnostic_is_visible_while_waiting_for_output_eof(self):
        runner, tree = self.runner()
        report = runner.output(42)
        self.assertIn('fixture query failure', report['internal_error'])
        self.assertIn('persistent warning', report['internal_error'])
        self.assertEqual(report['status'], 'running')

    def test_result_view_exposes_current_build_helper_diagnostic(self):
        runner, tree = self.runner()
        with patch.object(core, 'RUNNER', runner):
            report = core.session_results(42)
        self.assertIn('fixture query failure', report['internal_error'])
        self.assertEqual(report['verdict'], 'pending')

    def test_recovered_helper_query_does_not_permanently_change_session_error(self):
        runner, tree = self.runner()
        self.assertIn('fixture query failure', runner.output(42)['internal_error'])
        tree.cleanup_error = ''
        self.assertEqual(runner.output(42)['internal_error'], 'persistent warning')
        self.assertEqual(runner.sessions[42]['internal_error'], 'persistent warning')

    def test_build_can_derive_selected_toolchain_from_standard_vcvars_without_vs_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            selected = Path(temporary) / 'selected-vs'
            for name in ('vcvars64.bat', 'vcvarsall.bat'):
                with self.subTest(name=name):
                    vcvars = selected / 'VC/Auxiliary/Build' / name
                    vcvars.parent.mkdir(parents=True, exist_ok=True)
                    vcvars.touch()
                    runner = core.Runner(guard=RuntimeGuard())
                    with patch.object(core, 'ManagedProcess', side_effect=OSError('fixture no spawn')) as process:
                        with self.assertRaises(OSError):
                            runner.start(['unused'], temporary, 'build', context={'operation': 'build',
                                'project_config': {'VS_ROOT': '', 'VCVARS': str(vcvars)}})
                    actual = process.call_args.kwargs.get('build_toolchain_root')
                    self.assertEqual(os.path.normcase(os.path.realpath(actual or '.')),
                                     os.path.normcase(os.path.realpath(selected)))

    def test_actual_vcvars_toolchain_takes_precedence_over_different_vs_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            selected = Path(temporary) / 'actual-vs'
            vcvars = selected / 'VC/Auxiliary/Build/vcvars64.bat'
            vcvars.parent.mkdir(parents=True)
            vcvars.touch()
            runner = core.Runner(guard=RuntimeGuard())
            with patch.object(core, 'ManagedProcess', side_effect=OSError('fixture no spawn')) as process:
                with self.assertRaises(OSError):
                    runner.start(['unused'], temporary, 'build', context={'operation': 'build',
                        'project_config': {'VS_ROOT': str(Path(temporary) / 'other-vs'), 'VCVARS': str(vcvars)}})
            actual = process.call_args.kwargs.get('build_toolchain_root')
            self.assertEqual(os.path.normcase(os.path.realpath(actual or '.')),
                             os.path.normcase(os.path.realpath(selected)))

    def test_unknown_toolchain_reports_why_safe_wait_continues(self):
        release = threading.Event()
        class BlockingOutput:
            def __iter__(self):
                release.wait(5)
                return iter(())
            def close(self):
                pass
        tree = SimpleNamespace(proc=SimpleNamespace(stdout=BlockingOutput()), cleanup_error='',
                               wait=lambda: 0, close=lambda: None, terminate=release.set)
        runner = core.Runner(guard=RuntimeGuard())
        with patch.object(core, 'ManagedProcess', return_value=tree):
            sid = runner.start(['unused'], '.', 'build', context={'operation': 'build',
                'project_config': {'VS_ROOT': '', 'VCVARS': 'custom-environment.bat'}})
        try:
            report = runner.output(sid)
            self.assertEqual(report['status'], 'running')
            self.assertTrue(report['internal_error'], '无法确认工具链时，应说明为何继续等待而未自动回收')
        finally:
            release.set()
            self.assertTrue(runner.sessions[sid]['done_event'].wait(5))


if __name__ == '__main__':
    unittest.main()
