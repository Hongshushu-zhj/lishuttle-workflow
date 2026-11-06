import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core
from server import Api, Handler


class RuntimeApiTests(unittest.TestCase):
    def setUp(self):
        with core.RUNTIME.operation('fixture prediction', {'project': 'fixture', 'bin_dir': 'fixture/Bin'}) as token:
            core.RUNTIME.bind(token, 123)
        self.token = token
        self.addCleanup(lambda: core.RUNTIME.release(token))

    def test_all_input_and_config_writers_refuse_before_any_work(self):
        names = ('select_project', 'add_project', 'save_project_config', 'save_machine_config',
                 'detect_machine_config', 'set_map_root', 'set_gongcan_root', 'save_task_binding',
                 'render', 'param_write', 'param_default', 'csv_save', 'csv_column', 'run', 'toolkit')
        with patch.object(core, 'load_env', side_effect=AssertionError('must reject before reading/mutating config')):
            for name in names:
                with self.subTest(name=name):
                    response = getattr(Api, name)({})
                    self.assertEqual(response['code'], 'RUNTIME_BUSY')
                    self.assertEqual(response['runtime']['sid'], 123)
                    self.assertNotIn('token', response['runtime'])

    def test_build_status_query_does_not_sync_executable_while_busy(self):
        env = dict.fromkeys(core.FIELDS, '')
        env.update(PROJECT_DIR='', PROJECT_PROFILE_REVISION='1')
        with patch.object(core, 'load_env', return_value=env), \
                patch.object(core, 'sync_executable', side_effect=AssertionError('query must not write')):
            response = Api.build_status({})
        self.assertNotIn('error', response)

    def test_busy_config_reads_do_not_create_or_migrate_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / 'local-win.env'
            legacy.write_text('PROJECT_DIR=D:/fixture\nCASE_ROOT=D:/retired\n', encoding='utf-8')
            with patch.object(core, 'ENV_FILE', str(legacy)), \
                    patch.object(core, 'PROJECTS_FILE', str(root / 'projects.json')):
                env = core.load_env()
                core.scan_projects()
                with patch.object(Api, '_binding_task', return_value=({}, 'fixture', '', '')):
                    self.assertEqual(Api.task_binding({}), {'binding':None})
            self.assertEqual(env['PROJECT_DIR'], 'D:/fixture')
            self.assertEqual([path.name for path in root.iterdir()], ['local-win.env'],
                             '占用期间只读查询不得创建档案、锁或迁移备份')

    def test_busy_post_is_http409_and_runtime_query_is_available(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}/api/'
        request = Request(base + 'csv_save', data=b'{}', headers={'Content-Type': 'application/json'})
        with self.assertRaises(HTTPError) as raised:
            urlopen(request, timeout=3)
        self.assertEqual(raised.exception.code, 409)
        self.assertEqual(json.loads(raised.exception.read())['code'], 'RUNTIME_BUSY')
        with urlopen(base + 'runtime_state', timeout=3) as response:
            state = json.load(response)
        self.assertTrue(state['busy'])
        self.assertEqual(state['sid'], 123)

    def test_reservation_precedes_preflight_and_concurrent_start_is_rejected(self):
        core.RUNTIME.release(self.token)
        entered, finish = threading.Event(), threading.Event()
        self.addCleanup(finish.set)
        report = {'ok': False, 'issues': [{'severity':'error','message':'fixture missing input'}], 'context':{}}
        def check(*args):
            entered.set()
            finish.wait(5)
            return report
        responses = []
        env = {'PROJECT_DIR':'fixture','BUILD_SUBDIR':'build','EXE_NAME':'fixture.exe'}
        with patch.object(core, 'load_env', return_value=env), patch.object(core, 'check_run', side_effect=check):
            worker = threading.Thread(target=lambda: responses.append(Api.run({'schema':'fixture.xml','func':'pred'})))
            worker.start()
            self.assertTrue(entered.wait(3))
            blocked = Api.run({'schema':'fixture.xml','func':'pred'})
            self.assertEqual(blocked['code'], 'RUNTIME_BUSY')
            self.assertEqual(core.RUNTIME.snapshot()['phase'], 'preparing')
            finish.set()
            worker.join(3)
        self.assertEqual(responses[0]['code'], 'PREFLIGHT_FAILED')
        self.assertFalse(core.RUNTIME.snapshot()['busy'])


if __name__ == '__main__':
    unittest.main()
