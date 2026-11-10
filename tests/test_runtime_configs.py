"""Existing runtime XML is discovered and described without rewriting it."""
import hashlib
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'platform/backend'))
try:
    import runtime_configs
except ModuleNotFoundError:
    runtime_configs = None


class RuntimeConfigTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(runtime_configs, 'runtime_configs discovery module is missing')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = {'PROJECT_DIR': str(self.root / 'project'), 'BUILD_SUBDIR': 'out/Debug',
                    'PROJECT_PROFILE_ID': 'profile-a', 'PROJECT_PROFILE_REVISION': '3'}
        self.bin = Path(self.env['PROJECT_DIR']) / 'out/Debug/Bin'
        self.runtime = self.bin / 'runtimelibrary'
        self.runtime.mkdir(parents=True)

    def write(self, name='保存 配置.xml', extra=''):
        path = self.runtime / name
        path.write_bytes(('<RuntimeSchema name="actual-task"><MapFormat>indoor</MapFormat>'
            '<PathlossDirectory>../actual-output</PathlossDirectory>'
            '<EngineeringFilePath>inputs/cells.csv</EngineeringFilePath>'
            '<Unknown>keep</Unknown>' + extra + '</RuntimeSchema>').encode('utf-8'))
        return path

    def test_describe_uses_actual_name_and_bin_relative_paths_without_writing(self):
        path = self.write(extra='<Unknown>second</Unknown><!-- keep -->')
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        value = runtime_configs.describe_runtime_config(self.env, path.name)
        self.assertEqual(value['schema'], path.name)
        self.assertEqual(value['runtime_name'], 'actual-task')
        self.assertEqual(value['scene'], 'indoor')
        self.assertEqual(value['revision'], hashlib.sha256(before[0]).hexdigest())
        self.assertEqual(Path(value['file']), path)
        self.assertEqual(Path(value['out_dir']), (self.bin / '../actual-output/actual-task').resolve())
        self.assertEqual(Path(value['engineering_file']), self.bin / 'inputs/cells.csv')
        self.assertEqual(value['values']['EngineeringFilePath'], 'inputs/cells.csv')
        self.assertTrue(value['valid'])
        self.assertTrue(value['warnings'])  # Missing resources and duplicate scalar stay visible.
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.assertFalse(Path(str(path) + '.manifest.json').exists())

    def test_list_ignores_non_runtime_xml_backups_manifests_and_subdirectories(self):
        self.write('handwritten.xml')
        generated = self.write('platform.xml')
        Path(str(generated) + '.manifest.json').write_text('{}')
        (self.runtime / 'scene.xml').write_text('<SceneSettings/>')
        (self.runtime / 'cellformat.xml').write_text('<CellFormat/>')
        (self.runtime / 'broken.xml').write_text('<RuntimeSchema')
        (self.runtime / 'saved.xml.bak').write_text('<RuntimeSchema/>')
        (self.runtime / 'directory.xml').mkdir()
        listed = runtime_configs.list_runtime_configs(self.env)
        values = {item['schema']: item for item in listed['configs']}
        self.assertEqual(set(values), {'handwritten.xml', 'platform.xml', 'broken.xml'})
        self.assertTrue(values['handwritten.xml']['valid'])
        self.assertFalse(values['broken.xml']['valid'])
        self.assertTrue(values['broken.xml']['reason'])
        self.assertEqual(values['broken.xml']['revision'], hashlib.sha256(b'<RuntimeSchema').hexdigest())
        self.assertTrue(values['broken.xml']['modified'])
        self.assertEqual(Path(listed['directory']), self.runtime)
        self.assertEqual(listed['scope'], runtime_configs.runtime_scope(self.env))

    def test_safe_missing_schema_path_preserves_parameter_api_behavior(self):
        missing = dict(self.env, BUILD_SUBDIR='out/not-created')
        result = runtime_configs.resolve_runtime_config(missing, 'new 配置.xml')
        self.assertEqual(Path(result), Path(missing['PROJECT_DIR']) / 'out/not-created/Bin/runtimelibrary/new 配置.xml')
        self.assertFalse(Path(result).exists())

    def test_rejects_path_traversal_windows_aliases_and_non_xml_filenames(self):
        invalid = ('', '../saved.xml', '..\\saved.xml', '/saved.xml', 'C:\\saved.xml',
                   'nested/saved.xml', 'saved.xml:secret', 'a?.xml', 'a*.xml', 'a|b.xml',
                   'a\x00.xml', 'a\n.xml', 'saved.xml ', 'saved.xml.', 'CON.xml', 'LPT1.xml',
                   'a.xml.bak', '.xml')
        for schema in invalid:
            with self.subTest(schema=schema), self.assertRaises(ValueError):
                runtime_configs.resolve_runtime_config(self.env, schema)

    def test_empty_build_is_rejected_instead_of_scanning_project_bin(self):
        with self.assertRaisesRegex(ValueError, '构建'):
            runtime_configs.list_runtime_configs(dict(self.env, BUILD_SUBDIR=''))

    def test_scope_is_actual_bin_specific_and_ignores_profile_revision(self):
        first = runtime_configs.runtime_scope(self.env)
        self.assertEqual(first, runtime_configs.runtime_scope(dict(self.env,
            BUILD_SUBDIR='out/Debug/../Debug', PROJECT_PROFILE_REVISION='99')))
        self.assertNotEqual(first, runtime_configs.runtime_scope(dict(self.env, BUILD_SUBDIR='out/Release')))
        self.assertNotEqual(first, runtime_configs.runtime_scope(dict(self.env, PROJECT_DIR=str(self.root / 'other'))))

    @unittest.skipUnless(os.name == 'nt', 'Windows directory junction')
    def test_runtime_directory_junction_is_rejected_without_requiring_symlink_privileges(self):
        self.runtime.rmdir()
        outside = self.root / 'outside'
        outside.mkdir()
        result = subprocess.run(['cmd', '/d', '/c', 'mklink', '/J', str(self.runtime), str(outside)],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with self.assertRaisesRegex(ValueError, '链接|目录之外'):
            runtime_configs.resolve_runtime_config(self.env, 'outside.xml')

    def test_symlink_xml_and_runtime_directory_cannot_escape_bin(self):
        source = self.root / 'outside.xml'
        source.write_text('<RuntimeSchema name="outside"/>')
        link = self.runtime / 'linked.xml'
        try:
            link.symlink_to(source)
        except OSError as exc:
            self.skipTest('symlinks unavailable: ' + str(exc))
        with self.assertRaises(ValueError):
            runtime_configs.resolve_runtime_config(self.env, link.name)
        self.assertNotIn(link.name, [item['schema'] for item in runtime_configs.list_runtime_configs(self.env)['configs']])
        link.unlink()
        self.runtime.rmdir()
        self.runtime.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            runtime_configs.resolve_runtime_config(self.env, 'outside.xml')


if __name__ == '__main__':
    unittest.main()
