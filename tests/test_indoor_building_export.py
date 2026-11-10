from pathlib import Path
import hashlib
import importlib
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from file_safety import FileConflict

try:
    export_module = importlib.import_module('indoor_building_export')
except ModuleNotFoundError:
    export_module = None


SOURCE = Path('Propagation/Frame/src/PathLossofIndoorEngine.cpp')
BODY = ('#if false\n'
        '\t// 调试：生成建筑物墙体文本\n'
        '\tstd::string filePath = m_calcParams.pathlossDirectory + "/building.txt";\n'
        '\tpBuilding->Export(filePath.c_str());\n'
        '#endif\n')


class IndoorBuildingExportTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(export_module, '缺少室内 building.txt 源码开关模块')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'
        self.source = self.project / SOURCE
        self.env = {'PROJECT_DIR': str(self.project)}

    def write(self, text=BODY, encoding='utf-8', newline='\n', bom=False):
        self.source.parent.mkdir(parents=True, exist_ok=True)
        raw = text.replace('\n', newline).encode(encoding)
        if bom:
            raw = b'\xef\xbb\xbf' + raw
        self.source.write_bytes(raw)
        return raw

    def test_inspect_reports_disabled_known_block_without_writing(self):
        raw = self.write()
        state = export_module.inspect(self.env)
        self.assertTrue(state['supported'])
        self.assertFalse(state['enabled'])
        self.assertEqual(state['revision'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(Path(state['path']), self.source)
        self.assertTrue(state['requires_rebuild'])
        self.assertEqual(self.source.read_bytes(), raw)
        self.assertFalse(Path(str(self.source) + '.bak').exists())

    def test_enable_preserves_gbk_crlf_and_other_preprocessor_blocks(self):
        text = '#if false\nint unrelated = 1;\n#endif\n' + BODY + '#if true\nint tail = 2;\n#endif\n'
        raw = self.write(text, encoding='gbk', newline='\r\n')
        state = export_module.enable(self.env, hashlib.sha256(raw).hexdigest())
        expected = raw.replace(b'#if false\r\n\t//', b'#if true\r\n\t//', 1)
        self.assertEqual(self.source.read_bytes(), expected)
        self.assertTrue(state['enabled'])
        self.assertTrue(state['requires_rebuild'])
        self.assertEqual(state['revision'], hashlib.sha256(expected).hexdigest())
        self.assertEqual(Path(str(self.source) + '.bak').read_bytes(), raw)
        versions = list((self.source.parent / '.lishuttle-history').iterdir())
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0].read_bytes(), raw)

    def test_utf8_bom_and_final_newline_are_preserved(self):
        raw = self.write(BODY.rstrip('\n'), bom=True)
        export_module.enable(self.env, hashlib.sha256(raw).hexdigest())
        self.assertEqual(self.source.read_bytes(), raw.replace(b'false', b'true', 1))

    def test_already_enabled_is_idempotent_without_backups(self):
        raw = self.write(BODY.replace('#if false', '#if true'))
        state = export_module.enable(self.env, hashlib.sha256(raw).hexdigest())
        self.assertTrue(state['enabled'])
        self.assertFalse(state['changed'])
        self.assertEqual(self.source.read_bytes(), raw)
        self.assertFalse(Path(str(self.source) + '.bak').exists())
        self.assertFalse((self.source.parent / '.lishuttle-history').exists())

    def test_stale_revision_refuses_without_writing_or_backup(self):
        raw = self.write()
        with self.assertRaises(FileConflict):
            export_module.enable(self.env, 'stale')
        self.assertEqual(self.source.read_bytes(), raw)
        self.assertFalse(Path(str(self.source) + '.bak').exists())

    def test_missing_revision_refuses_even_if_already_enabled(self):
        raw = self.write(BODY.replace('#if false', '#if true'))
        for revision in (None, '', 123):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                export_module.enable(self.env, revision)
        self.assertEqual(self.source.read_bytes(), raw)

    def test_unsupported_shapes_are_read_only(self):
        cases = {
            'unknown guard': BODY.replace('#if false', '#if ENABLE_DEBUG'),
            'no guard': BODY.replace('#if false\n', '').replace('#endif\n', ''),
            'duplicate blocks': BODY + BODY,
            'missing export': BODY.replace('\tpBuilding->Export(filePath.c_str());\n', ''),
            'extra branch': BODY.replace('#endif', '#else\nint side = 0;\n#endif'),
            'extra code': BODY.replace('#endif', 'destroySomething();\n#endif'),
            'unclosed guard': BODY.replace('#endif', ''),
            'different export': BODY.replace('filePath.c_str()', 'otherPath.c_str()'),
            'guard hidden by continued comment': '// continued comment \\\n' + BODY,
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                raw = self.write(text)
                state = export_module.inspect(self.env)
                self.assertFalse(state['supported'])
                self.assertIsNone(state['enabled'])
                self.assertTrue(state['reason'])
                with self.assertRaises(ValueError):
                    export_module.enable(self.env, state['revision'])
                self.assertEqual(self.source.read_bytes(), raw)

    def test_comments_containing_fake_blocks_are_ignored(self):
        raw = self.write('/*\n' + BODY + '*/\n' + BODY)
        state = export_module.inspect(self.env)
        self.assertTrue(state['supported'])
        export_module.enable(self.env, state['revision'])
        expected = raw[:raw.index(b'*/') + 2] + raw[raw.index(b'*/') + 2:].replace(b'false', b'true', 1)
        self.assertEqual(self.source.read_bytes(), expected)

    def test_raw_string_containing_fake_block_does_not_select_a_different_guard(self):
        raw = self.write('const char* sample = R"example(\n' + BODY + ')example";\n' + BODY)
        state = export_module.inspect(self.env)
        self.assertTrue(state['supported'])
        export_module.enable(self.env, state['revision'])
        marker = raw.index(b')example";') + len(b')example";')
        expected = raw[:marker] + raw[marker:].replace(b'false', b'true', 1)
        self.assertEqual(self.source.read_bytes(), expected)

    def test_guard_spacing_and_trailing_comments_are_preserved(self):
        raw = self.write(BODY.replace('#if false', ' \t# if\tfalse // target'))
        export_module.enable(self.env, hashlib.sha256(raw).hexdigest())
        self.assertEqual(self.source.read_bytes(), raw.replace(b'false // target', b'true // target'))

    def test_nested_unrelated_guards_select_nearest_building_guard(self):
        raw = self.write('#ifdef SOME_FEATURE\n' + BODY + '#endif\n')
        export_module.enable(self.env, hashlib.sha256(raw).hexdigest())
        self.assertEqual(self.source.read_bytes(), raw.replace(b'#if false', b'#if true'))

    def test_missing_project_or_source_does_not_create_directories(self):
        for env in ({}, self.env):
            with self.subTest(env=env):
                state = export_module.inspect(env)
                self.assertFalse(state['supported'])
                self.assertTrue(state['reason'])
        self.assertFalse(self.project.exists())

    def test_symlink_escape_is_refused(self):
        outside = self.root / 'outside.cpp'
        outside.write_text(BODY, encoding='utf-8')
        self.source.parent.mkdir(parents=True)
        try:
            self.source.symlink_to(outside)
        except OSError:
            self.skipTest('当前 Windows 未允许创建测试符号链接')
        state = export_module.inspect(self.env)
        self.assertFalse(state['supported'])
        with self.assertRaises(ValueError):
            export_module.enable(self.env, state['revision'])
        self.assertEqual(outside.read_text(encoding='utf-8'), BODY)

    def test_resolved_source_outside_project_is_refused_without_reading_it(self):
        outside = self.root / 'outside.cpp'
        outside.write_text(BODY, encoding='utf-8')
        real_resolve = Path.resolve
        def escaped(path, *args, **kwargs):
            if path == self.source:
                return outside
            return real_resolve(path, *args, **kwargs)
        with patch.object(Path, 'resolve', autospec=True, side_effect=escaped):
            state = export_module.inspect(self.env)
            self.assertFalse(state['supported'])
            self.assertIn('当前项目', state['reason'])
            with self.assertRaises(ValueError):
                export_module.enable(self.env, 'any-revision')
        self.assertEqual(outside.read_text(encoding='utf-8'), BODY)

    def test_external_change_during_preparation_is_preserved(self):
        raw = self.write()
        import file_safety
        original = file_safety.os.fsync
        changed = []
        def edit_after_prepare(descriptor):
            original(descriptor)
            if not changed:
                changed.append(True)
                self.source.write_bytes(raw + b'// external edit\n')
        with patch.object(file_safety.os, 'fsync', side_effect=edit_after_prepare):
            with self.assertRaises(FileConflict):
                export_module.enable(self.env, hashlib.sha256(raw).hexdigest())
        self.assertEqual(self.source.read_bytes(), raw + b'// external edit\n')


if __name__ == '__main__':
    unittest.main()
