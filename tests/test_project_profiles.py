"""Project resources stay isolated; installed tools are shared machine settings."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'platform/backend'))
import core
from server import Api
from server import Handler
import project_config


class ProjectProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = self.root / 'local-win.env'
        self.a = self.root / '项目 A'
        self.b = self.root / '项目 B'
        for path in (self.a, self.b):
            (path / 'LiShuttle').mkdir(parents=True)
            (path / 'SwanUtility/incl').mkdir(parents=True)
            (path / 'CMakeLists.txt').write_text('project(LiShuttle)')
            (path / 'SwanUtility/incl/LiShuttleTypes.h').write_text('')
        self.original = (f'# keep\nPROJECT_DIR="{self.a.as_posix()}"\nPRESET="A"\n'
                         'BUILD_SUBDIR="out/A"\nEXE_NAME="lishuttle.exe"\n'
                         'MAP_ROOT="maps-A"\nOUT_ROOT="outputs-A"\n')
        self.env.write_text(self.original, encoding='utf-8')
        self.file = self.root / 'project-profiles.json'
        self.store = project_config.ProjectStore(self.env, self.file)

    def test_migration_and_a_b_a_restore(self):
        a = self.store.load()
        self.assertEqual(a['PRESET'], 'A')
        self.assertEqual(self.env.read_text(encoding='utf-8'), self.original)
        self.assertEqual(Path(str(self.env) + '.profiles.bak').read_text(encoding='utf-8'), self.original)
        b = self.store.select(str(self.b))
        self.assertEqual(b['PRESET'], '')
        self.assertEqual(b['MAP_ROOT'], '')
        self.store.save({'PRESET': 'B', 'BUILD_SUBDIR': 'out/B', 'OUT_ROOT': 'outputs-B'})
        self.assertEqual(self.store.select(str(self.a))['PRESET'], 'A')
        self.assertEqual(self.store.select(str(self.b))['BUILD_SUBDIR'], 'out/B')
        self.assertNotEqual(a['PROJECT_PROFILE_ID'], b['PROJECT_PROFILE_ID'])

    def test_stale_revision_and_unknown_keys_are_rejected_without_writing(self):
        old = self.store.load()
        self.store.save({'PRESET': 'new'}, old['PROJECT_PROFILE_REVISION'])
        before = self.file.read_bytes()
        with self.assertRaisesRegex(ValueError, '变化'):
            self.store.save({'PRESET': 'stale'}, old['PROJECT_PROFILE_REVISION'])
        with self.assertRaises(ValueError):
            self.store.save({'PROJECT_DIR': str(self.b)})
        self.assertEqual(before, self.file.read_bytes())

    def test_task_binding_is_project_scoped(self):
        self.store.load()
        self.store.binding('task/engineering.csv', {'city': 'guangzhou'})
        self.store.select(str(self.b))
        self.assertIsNone(self.store.binding('task/engineering.csv'))
        self.store.binding('task/engineering.csv', {'city': 'bengbu'})
        self.store.select(str(self.a))
        self.assertEqual(self.store.binding('task/engineering.csv')['city'], 'guangzhou')

    def test_frozen_snapshot_and_cli_ignore_later_switch(self):
        env = self.store.load()
        snapshot = project_config.write_snapshot(env, self.root / 'snapshots')
        self.store.select(str(self.b))
        child = dict(os.environ, LISHUTTLE_CONFIG_SNAPSHOT=snapshot, PYTHONIOENCODING='utf-8')
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/render_schema.py'),
                                 '--print-env', 'local-win'], env=child, capture_output=True,
                                text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PRESET=A', result.stdout)
        self.assertIn('PROJECT_DIR=' + self.a.as_posix(), result.stdout)

    def test_core_and_api_use_profile_and_reject_stale_save(self):
        with patch.object(core, 'ENV_FILE', str(self.env)):
            a = core.load_env()
            core.save_env_keys(PRESET='edited')
            self.assertEqual(self.store.load()['PRESET'], 'edited')
            result = Api.save_project_config({'values': {'PRESET': 'stale'},
                                             '_revision': a['PROJECT_PROFILE_REVISION']})
            self.assertIn('error', result)

    def test_job_cannot_override_project_identity_or_build(self):
        import render_schema
        env = self.store.load()
        with self.assertRaisesRegex((SystemExit, ValueError), '项目'):
            render_schema.build_table(env, {'PROJECT_DIR': str(self.b), 'BUILD_SUBDIR': 'wrong'})

    def test_snapshot_reader_rejects_missing_file_instead_of_fallback(self):
        with patch.dict(os.environ, {'LISHUTTLE_CONFIG_SNAPSHOT': str(self.root / 'missing.json')}):
            with self.assertRaises((ValueError, OSError)):
                project_config.load_local(self.env)

    def test_failed_atomic_save_keeps_previous_profile(self):
        self.store.load()
        before = self.file.read_bytes()
        with patch.object(project_config.os, 'replace', side_effect=OSError('cannot replace')):
            with self.assertRaises(OSError):
                self.store.save({'PRESET': 'lost'})
        self.assertEqual(self.file.read_bytes(), before)

    def test_api_binding_revalidates_map_and_engineering_and_roundtrips(self):
        maps = self.root / 'maps' / 'city'
        (maps / 'heights').mkdir(parents=True)
        (maps / 'heights/index.txt').write_text('map')
        tasks = self.root / 'tasks'
        taskdir = tasks / 'task'
        taskdir.mkdir(parents=True)
        engineering = taskdir / 'engineering.csv'
        engineering.write_text('Cell ID,Longitude,Latitude,Height (m),Azimuth (°),Antenna,Max Power (dBm)\n', encoding='utf-8-sig')
        self.store.load()
        self.store.save({'MAP_ROOT': str(maps.parent), 'GONGCAN_ROOT': str(tasks)})
        with patch.object(core, 'ENV_FILE', str(self.env)):
            task = core.scan_tasks()[0][0]
            body = dict(task=task, city='city', engineering_file=engineering.as_posix(),
                        schema_source='', path_overrides={})
            result = Api.save_task_binding(body)
            self.assertNotIn('error', result)
            loaded = Api.task_binding(dict(body))
            self.assertEqual(loaded['binding']['city'], 'city')
            self.assertIn('error', Api.save_task_binding(dict(body, city='missing')))
            self.assertIn('error', Api.save_task_binding(dict(body, engineering_file='foreign.csv')))

    def test_request_snapshot_stays_fixed_during_external_project_switch(self):
        from server import project_operation
        self.store.load()
        with patch.object(core, 'ENV_FILE', str(self.env)):
            @project_operation
            def operation(_):
                first = core.load_env()
                self.store.select(str(self.b))
                return first, core.load_env()
            first, second = operation({})
        self.assertEqual(first, second)

    @unittest.skipUnless(os.name == 'nt', 'Windows batch entrypoint')
    def test_batch_loader_consumes_snapshot_without_inherited_project_values(self):
        env = self.store.load()
        snapshot = project_config.write_snapshot(env, self.root / 'snapshots')
        child = dict(os.environ, LISHUTTLE_CONFIG_SNAPSHOT=snapshot, PROJECT_DIR='wrong',
                     PRESET='wrong', DT_ROOT='inherited-wrong', PYTHONIOENCODING='utf-8')
        script = self.root / 'check.bat'
        script.write_text('@echo off\ncall scripts\\load_local_env.bat\n'
                          'if errorlevel 1 exit /b 1\n'
                          'python -c "import os,json; print(json.dumps({k:os.environ.get(k) for k in '
                          "['PROJECT_DIR','PRESET','DT_ROOT']},ensure_ascii=True))" + '"\n', encoding='ascii')
        result = subprocess.run(['cmd', '/d', '/c', str(script)], cwd=ROOT, env=child,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(actual['PROJECT_DIR'], env['PROJECT_DIR'])
        self.assertEqual(actual['PRESET'], 'A')
        self.assertIsNone(actual['DT_ROOT'])  # Windows removes empty environment variables.

    def test_generated_jobs_are_project_scoped_and_pinned(self):
        self.store.load()
        task = dict(txts=[], engineering_file='a.csv')
        with patch.object(core, 'ENV_FILE', str(self.env)), patch.object(core, 'JOBS_DIR', str(self.root / 'jobs')), \
                patch.object(core, 'validate_engineering', return_value='a.csv'):
            a = core.build_job_env('same', 'pl', '1', task, 'city', 'outdoor')
            self.store.select(str(self.b))
            b = core.build_job_env('same', 'pl', '1', task, 'city', 'outdoor')
        self.assertNotEqual(a, b)
        self.assertIn('PROJECT_PROFILE_ID=', Path(a).read_text(encoding='utf-8'))

    @unittest.skipUnless(os.name == 'nt', 'Windows batch entrypoint')
    def test_batch_loader_creates_first_snapshot_in_isolated_workspace(self):
        workspace = self.root / '独立 workspace'
        (workspace / 'scripts').mkdir(parents=True)
        (workspace / 'env').mkdir()
        for name in ('load_local_env.bat', 'project_config.py', 'render_schema.py', 'task_schema.py'):
            shutil.copy2(ROOT / 'scripts' / name, workspace / 'scripts' / name)
        (workspace / 'env/local-win.env').write_text(self.original, encoding='utf-8')
        check = workspace / 'check.bat'
        check.write_text('@echo off\ncall scripts\\load_local_env.bat\nif errorlevel 1 exit /b 1\n'
            'python -c "import os,json; print(json.dumps(dict(project=os.environ.get(\'PROJECT_DIR\'),snapshot=os.environ.get(\'LISHUTTLE_CONFIG_SNAPSHOT\')),ensure_ascii=True))"\n', encoding='ascii')
        child = {k: v for k, v in os.environ.items() if k != 'LISHUTTLE_CONFIG_SNAPSHOT'}
        result = subprocess.run(['cmd', '/d', '/c', 'check.bat'], cwd=workspace, env=child, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(actual['project'], self.a.as_posix())
        self.assertTrue(Path(actual['snapshot']).is_file())
        self.assertTrue((workspace / 'env/project-profiles.json').is_file())

    def test_toolkit_passes_captured_profile_to_batch_child(self):
        self.store.load()
        with patch.object(core, 'ENV_FILE', str(self.env)), \
                patch.object(core, 'write_snapshot', side_effect=lambda env: project_config.write_snapshot(env, self.root / 'snapshots')), \
                patch.object(core.RUNNER, 'start', return_value=1) as start:
            core.start_toolkit('doctor')
            child = start.call_args.kwargs['env']
        self.store.select(str(self.b))
        snapshot = json.loads(Path(child['LISHUTTLE_CONFIG_SNAPSHOT']).read_text(encoding='utf-8'))
        self.assertEqual(snapshot['PROJECT_DIR'], self.a.as_posix())

    @unittest.skipUnless(os.name == 'nt', 'Windows batch entrypoint')
    def test_batch_rejects_bang_instead_of_silently_corrupting_path(self):
        env = self.store.load()
        env['PRESET'] = 'release!one'
        snapshot = project_config.write_snapshot(env, self.root / 'snapshots')
        child = dict(os.environ, LISHUTTLE_CONFIG_SNAPSHOT=snapshot)
        result = subprocess.run(['cmd', '/d', '/v:on', '/c', 'call scripts\\load_local_env.bat'],
            cwd=ROOT, env=child, capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_batch_exports_absolute_resource_directories(self):
        import contextlib
        import io
        import render_schema
        env = self.store.load()
        env.update(CONFIG_SRC=(self.root / 'external-config').as_posix(), DLL_SRC='relative-dll')
        snapshot = project_config.write_snapshot(env, self.root / 'snapshots')
        with patch.dict(os.environ, {'LISHUTTLE_CONFIG_SNAPSHOT': snapshot}), \
                patch.object(sys, 'argv', ['render_schema.py', '--print-env', 'local-win', '--batch']), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            render_schema.main()
        values = dict(line.split('=', 1) for line in output.getvalue().splitlines())
        self.assertEqual(values['CONFIG_SOURCE_DIR'], env['CONFIG_SRC'])
        self.assertEqual(Path(values['DLL_SOURCE_DIR']), self.a / 'relative-dll')

    def test_empty_installation_can_add_first_project_from_web(self):
        missing = self.root / 'new-install/local-win.env'
        with patch.object(core, 'ENV_FILE', str(missing)), patch.object(core, 'PROJECTS_FILE', str(self.root / 'new-install/projects.json')):
            state = Api.state({})
            self.assertEqual(state['project'], '')
            self.assertEqual(state['projects'], [])
            state = Api.add_project({'path': str(self.a)})
            self.assertEqual(state['project'], self.a.as_posix())
            self.assertEqual(state['preset'], '')
            self.assertTrue(state['profile_id'])

    def test_unconfigured_project_cannot_start_build_or_stage(self):
        self.store.load()
        self.store.select(str(self.b))
        with patch.object(core, 'ENV_FILE', str(self.env)), patch.object(core.RUNNER, 'start') as start:
            for step in ('build', 'stage'):
                result = Api.toolkit({'step': step})
                self.assertIn('error', result)
            start.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows stage entrypoint')
    def test_real_stage_script_supports_absolute_external_resources(self):
        env = self.store.load()
        config = self.root / '外部 config'
        dll = self.root / '外部 dll'
        (config / 'config').mkdir(parents=True)
        dll.mkdir()
        (config / 'config/cellformat.xml').write_text('<Cell/>')
        (dll / 'sample.dll').write_bytes(b'fixture only, never executed')
        exe_dir = self.a / 'out/A/Bin'
        exe_dir.mkdir(parents=True)
        (exe_dir / 'lishuttle.exe').write_bytes(b'fixture only, never executed')
        env.update(CONFIG_SRC=config.as_posix(), DLL_SRC=dll.as_posix())
        snapshot = project_config.write_snapshot(env, self.root / 'snapshots')
        result = subprocess.run(['cmd', '/d', '/c', 'scripts\\stage_local.bat'], cwd=ROOT,
            env=dict(os.environ, LISHUTTLE_CONFIG_SNAPSHOT=snapshot), capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout.decode('gbk', errors='replace') + result.stderr.decode('gbk', errors='replace'))
        self.assertEqual((exe_dir / 'cellformat.xml').read_text(), '<Cell/>')
        self.assertEqual((exe_dir / 'sample.dll').read_bytes(), b'fixture only, never executed')

    @unittest.skipUnless(os.name == 'nt', 'Windows stage entrypoint')
    def test_direct_stage_script_rejects_empty_configuration(self):
        self.store.load()
        env = self.store.select(str(self.b))
        snapshot = project_config.write_snapshot(env, self.root / 'snapshots')
        result = subprocess.run(['cmd', '/d', '/c', 'scripts\\stage_local.bat'], cwd=ROOT,
            env=dict(os.environ, LISHUTTLE_CONFIG_SNAPSHOT=snapshot), capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.b / 'Bin').exists())

    def test_http_project_switch_save_and_stale_page(self):
        self.store.load()
        with patch.object(core, 'ENV_FILE', str(self.env)), patch.object(core, 'PROJECTS_FILE', str(self.root / 'projects.json')):
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            def call(name, body=None):
                data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None
                request = Request(f'http://127.0.0.1:{server.server_port}/api/{name}', data=data,
                                  headers={'Content-Type': 'application/json'})
                with urlopen(request, timeout=5) as response:
                    return json.load(response)
            try:
                a = call('state')
                changed = call('save_project_config', dict(_project=a['project'], _revision=a['profile_revision'], values={'PRESET': 'A-edited'}))
                b = call('select_project', dict(path=str(self.b), _project=a['project'], _revision=changed['profile_revision']))
                self.assertEqual(b['preset'], '')
                stale = call('save_project_config', dict(_project=a['project'], _revision=changed['profile_revision'], values={'PRESET': 'wrong'}))
                self.assertIn('error', stale)
                restored = call('select_project', dict(path=str(self.a), _project=b['project'], _revision=b['profile_revision']))
                self.assertEqual(restored['preset'], 'A-edited')
                self.assertEqual(restored['profile_id'], a['profile_id'])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
