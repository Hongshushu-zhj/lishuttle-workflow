import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core
from server import Api, ROUTES
from run_guard import RuntimeGuard
from run_history import RunHistory


class HistoryApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.history = RunHistory(self.root / 'runs')
        self.runner = core.Runner(guard=RuntimeGuard(), history=self.history)
        patcher = patch.object(core, 'RUNNER', self.runner)
        patcher.start()
        self.addCleanup(patcher.stop)

    def record(self, sid, project='project-a', verdict='success'):
        self.history.create(sid, 'fixture', {'project': project, 'task_name': 'task'}, [], str(self.root))
        self.history.append(sid, 'first')
        self.history.append(sid, 'second')
        self.history.finish(sid, 'done', 0, {'verdict': verdict, 'files': []})

    def test_recent_runs_are_project_filtered_before_paging(self):
        for sid in range(1, 5):
            self.record(sid, project='project-a' if sid % 2 else 'project-b')
        with patch.object(core, 'load_env', return_value={'PROJECT_DIR': 'project-a'}):
            page = Api.history({'limit': ['1'], 'offset': ['1']})
        self.assertEqual(page['total'], 2)
        self.assertEqual([run['sid'] for run in page['runs']], [1])
        self.assertIs(ROUTES[('GET', 'history')], Api.history)
        self.assertTrue(page['runs'][0]['historical'])

    def test_logs_page_after_service_restart_and_unknown_session_is_explicit(self):
        self.record(10)
        page = Api.output({'sid': ['10'], 'since': ['0'], 'limit': ['1']})
        self.assertEqual(page['lines'], ['first'])
        self.assertEqual(page['next_since'], 1)
        self.assertTrue(page['has_more'])
        self.assertEqual(Api.output({'sid': ['999']})['code'], 'SESSION_NOT_FOUND')

    def test_failed_final_save_shows_live_diagnostic_in_recent_runs(self):
        self.record(10)
        self.runner.sessions[10] = {'status': 'done', 'exit': 0, 'context': {'project': 'project-a'},
            'result': {'verdict': 'unconfirmed'}, 'internal_error': 'history save failed',
            'archive': {'status': 'incomplete'}, 'label': 'fixture'}
        page = core.recent_runs('project-a')
        self.assertEqual(page['runs'][0]['result']['verdict'], 'unconfirmed')
        self.assertEqual(page['runs'][0]['archive']['status'], 'incomplete')

    def test_history_results_never_resolve_current_project(self):
        self.record(10)
        with patch.object(core, 'load_env', side_effect=AssertionError('must use pinned context')):
            report = Api.results({'sid': ['10']})
        self.assertEqual(report['historical_verdict'], 'success')
        self.assertEqual(report['context']['project'], 'project-a')
        self.assertEqual(report['current_files']['status'], 'unconfirmed')

    def test_external_instance_is_visible_and_its_session_cannot_be_stopped(self):
        from resource_lock import ResourceLease
        env = {'PROJECT_DIR': str(self.root), 'BUILD_SUBDIR': 'build', 'OUT_ROOT': str(self.root / 'out')}
        ctx = core.runtime_resources(env)
        with ResourceLease([ctx['bin_dir']], owner={'sid': 444, 'label': 'other service'}), \
                patch.object(core, 'load_env', return_value=env):
            state = Api.runtime_state({})
            self.assertTrue(state['busy'])
            self.assertTrue(state['external'])
            self.assertEqual(state['sid'], 444)
            self.assertFalse(Api.stop({'sid': 444})['stopped'])
            blocked = Api.csv_save({})
            self.assertEqual(blocked['code'], 'RUNTIME_BUSY')
            self.assertTrue(blocked['runtime']['external'])


if __name__ == '__main__':
    unittest.main()
