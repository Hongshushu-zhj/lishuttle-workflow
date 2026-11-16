"""Desktop roots stay writable and never change ordinary CLI defaults."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import shutil
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


class DesktopPathTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime_paths'), 'portable runtime paths are required')
        import runtime_paths
        return runtime_paths

    def test_ordinary_cli_defaults_remain_unchanged(self):
        paths = self.module().resolve_paths({})
        self.assertEqual(paths.resource_root, ROOT)
        self.assertEqual(paths.env_file, ROOT / 'env/local-win.env')
        self.assertEqual(paths.runs_dir, ROOT / '.lishuttle-runs')
        self.assertEqual(paths.maintenance_dir, ROOT / 'docs/runtime-config-archives')

    def test_desktop_paths_are_isolated_from_read_only_resources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            resource, data = root / 'installation', root / 'user data'
            paths = self.module().resolve_paths({'LISHUTTLE_RESOURCE_ROOT':str(resource), 'LISHUTTLE_DATA_DIR':str(data)})
            self.assertEqual(paths.resource_root, resource)
            self.assertEqual(paths.env_file, data / 'env/local-win.env')
            self.assertEqual(paths.projects_file, data / 'env/projects.json')
            for value in (paths.jobs_dir, paths.runs_dir, paths.snapshots_dir, paths.maintenance_dir, paths.logs_dir, paths.cache_dir):
                self.assertTrue(value.is_relative_to(data))
            self.assertFalse(resource.exists())
            self.assertFalse(data.exists(), 'resolving roots must not create mutable state')

    def test_project_store_snapshot_and_core_follow_data_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(os.environ, LISHUTTLE_DATA_DIR=temporary)
            code = ('import json,sys;sys.path[:0]=["scripts","platform/backend"];'
                    'import core;from project_config import ProjectStore,write_snapshot;'
                    'print(json.dumps([str(ProjectStore().env_file),write_snapshot({"PROJECT_DIR":"fixture"}),'
                    'core.ENV_FILE,core.JOBS_DIR,str(core.RUNNER.history.root)]))')
            result = subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(all(Path(value).is_relative_to(Path(temporary)) for value in json.loads(result.stdout)))

    def test_batch_loaders_propagate_explicit_interpreter(self):
        for filename in ('load_local_env.bat','run_local.bat','build_local.bat','stage_local.bat','doctor_local.bat'):
            source = (ROOT / 'scripts' / filename).read_bytes().decode('gb18030')
            self.assertIn('LISHUTTLE_PYTHON',source,filename)
            self.assertNotRegex(source,r'(?m)^\s*python\s+[^\r\n]*\.py',filename)

    def test_batch_values_reject_unsafe_expansion_and_lossy_path_encoding(self):
        from render_schema import validate_batch_values
        for value in ('directory%TEMP%', 'broken"path', 'line\nbreak', 'emoji\U0001f6a6'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                validate_batch_values({'PROJECT_DIR':value})

    @unittest.skipUnless(os.name == 'nt','Windows batch transport')
    def test_batch_loader_uses_explicit_python_without_python_on_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root/'scripts'
            scripts.mkdir()
            shutil.copy2(ROOT/'scripts/load_local_env.bat',scripts/'load_local_env.bat')
            (scripts/'project_config.py').write_text('from pathlib import Path\np=Path(__file__).parent/"fixture.json"\np.write_text("{}")\nprint(p)\n')
            (scripts/'render_schema.py').write_text('import os\nassert os.environ.get("LISHUTTLE_CONFIG_SNAPSHOT")\nprint("PROJECT_DIR=fixture")\n')
            check = root/'check.bat'
            check.write_text('@echo off\nsetlocal DisableDelayedExpansion\ncall scripts\\load_local_env.bat doctor\nexit /b %errorlevel%\n')
            env = dict(os.environ,LISHUTTLE_PYTHON=sys.executable,PATH=str(Path(os.environ['SystemRoot'])/'System32'))
            env.pop('LISHUTTLE_CONFIG_SNAPSHOT',None)
            result = subprocess.run([os.environ.get('COMSPEC','cmd.exe'),'/d','/c',str(check)],cwd=root,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue((scripts/'fixture.json').is_file())


if __name__ == '__main__':
    unittest.main()
