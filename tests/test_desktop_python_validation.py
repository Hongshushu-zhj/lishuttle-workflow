"""Exercise real Windows batch prechecks without reaching engine/build operations."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINTS = ('doctor_local.bat', 'build_local.bat', 'stage_local.bat', 'run_local.bat')
STOP = 83
MARKER = 'PYTHON_PRECHECK_PASSED'


@unittest.skipUnless(os.name == 'nt', 'real Windows batch entrypoints')
class DesktopPythonValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bundled = ROOT / '.desktop-build/python-package'
        if not (bundled / 'python.exe').is_file():
            raise unittest.SkipTest('prepare the offline bundled Python runtime first')
        cls.temporary = tempfile.TemporaryDirectory(prefix='解释器 validation ! ')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.runtime = cls.root / '内置 Python ! 空间'
        shutil.copytree(bundled, cls.runtime)
        cls.python = cls.runtime / 'python.exe'
        cls.scripts = cls.root / '隔离 工作区 !' / 'scripts'
        cls.scripts.mkdir(parents=True)
        cls.scratch = cls.root / '临时 导出 !'
        cls.scratch.mkdir()
        for name in ENTRYPOINTS + ('validate_local_python.bat',):
            source = ROOT / 'scripts' / name
            if source.exists():
                shutil.copy2(source, cls.scripts / name)
        # Every successful precheck must stop here, before loading real profiles,
        # invoking CMake, copying resources, or starting an engine.
        (cls.scripts / 'load_local_env.bat').write_text(
            f'@echo off\necho {MARKER}\nexit /b {STOP}\n', encoding='ascii')
        (cls.scripts / 'run_local.py').write_text(
            f'import sys\nprint("{MARKER}", flush=True)\nraise SystemExit({STOP})\n',
            encoding='ascii')
        cls.system32 = Path(os.environ['SystemRoot']) / 'System32'
        cls.command = cls.system32 / 'cmd.exe'

    def invoke(self, entrypoint, interpreter, path=None):
        env = dict(os.environ)
        for key in ('LISHUTTLE_PYTHON', 'PYTHONHOME', 'PYTHONPATH',
                    'LISHUTTLE_CONFIG_SNAPSHOT'):
            env.pop(key, None)
        env['PATH'] = str(path or self.system32)
        env['TEMP'] = str(self.scratch)
        env['TMP'] = str(self.scratch)
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        if interpreter is not None:
            env['LISHUTTLE_PYTHON'] = str(interpreter)
        result = subprocess.run(
            [str(self.command), '/d', '/v:off', '/c', str(self.scripts / entrypoint)],
            cwd=self.scripts.parent, env=env, capture_output=True, timeout=20)
        encoding = 'utf-8' if entrypoint == 'run_local.bat' else 'gbk'
        output = (result.stdout + result.stderr).decode(encoding, errors='replace')
        return result.returncode, output

    def assert_passes_precheck(self, interpreter, path=None):
        for name in ENTRYPOINTS:
            with self.subTest(entrypoint=name):
                code, output = self.invoke(name, interpreter, path)
                # The profile-based entrypoints deliberately map loader errors
                # to 1; run forwards the isolated Python script's status.
                self.assertEqual(code, STOP if name == 'run_local.bat' else 1, output)
                self.assertIn(MARKER, output)

    def test_absolute_bundled_interpreter_without_python_on_path(self):
        self.assert_passes_precheck(self.python)

    def test_inherited_quoted_interpreter_with_chinese_spaces_and_bang(self):
        self.assert_passes_precheck(f'"{self.python}"')

    def test_invalid_explicit_interpreter_never_falls_back_to_path_python(self):
        missing = self.root / '不存在 Python !' / 'python.exe'
        fallback_path = str(self.runtime) + os.pathsep + str(self.system32)
        for name in ENTRYPOINTS:
            with self.subTest(entrypoint=name):
                code, output = self.invoke(name, missing, fallback_path)
                self.assertNotIn(code, (0, STOP), output)
                self.assertNotIn(MARKER, output)
                self.assertIn(str(missing), output)
                self.assertIn('[ERROR]', output)

    def test_cli_defaults_to_bare_python_only_when_override_is_absent(self):
        self.assert_passes_precheck(
            None, str(self.runtime) + os.pathsep + str(self.system32))

    def test_explicit_bare_python_command_remains_supported(self):
        self.assert_passes_precheck(
            'python', str(self.runtime) + os.pathsep + str(self.system32))

    def test_profile_loader_preserves_validated_interpreter_path(self):
        loader = self.scripts / 'load_local_env.bat'
        early_stop = loader.read_bytes()
        self.addCleanup(loader.write_bytes, early_stop)
        shutil.copy2(ROOT / 'scripts/load_local_env.bat', loader)
        # Reach the real loader's first Python subprocess, then stop before
        # producing a snapshot or reading any real profile/project data.
        (self.scripts / 'project_config.py').write_text(
            f'import sys\nprint("{MARKER}", file=sys.stderr, flush=True)\n'
            f'raise SystemExit({STOP})\n', encoding='ascii')
        for name in ENTRYPOINTS[:-1]:
            with self.subTest(entrypoint=name):
                code, output = self.invoke(name, f'"{self.python}"')
                self.assertEqual(code, 1, output)
                self.assertIn(MARKER, output)

    def test_required_import_failure_is_not_hidden(self):
        broken = self.root / '不完整 Python !'
        shutil.copytree(self.runtime, broken)
        archive = broken / 'python313.zip'
        replacement = archive.with_suffix('.new.zip')
        with zipfile.ZipFile(archive) as source, zipfile.ZipFile(replacement, 'w') as target:
            for item in source.infolist():
                if not item.filename.startswith('xml/'):
                    target.writestr(item, source.read(item))
        replacement.replace(archive)
        for name in ENTRYPOINTS:
            with self.subTest(entrypoint=name):
                code, output = self.invoke(name, broken / 'python.exe')
                self.assertNotIn(code, (0, STOP), output)
                self.assertNotIn(MARKER, output)
                self.assertIn('ModuleNotFoundError', output)
                self.assertIn('xml', output)
                self.assertIn(str(broken / 'python.exe'), output)


if __name__ == '__main__':
    unittest.main()
