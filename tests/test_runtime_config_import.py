"""Import is an explicit, byte-preserving, never-overwrite local copy."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'platform/backend'))
try:
    import runtime_configs
except ModuleNotFoundError:
    runtime_configs = None


class RuntimeImportTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(runtime_configs, 'runtime_configs import module is missing')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = {'PROJECT_DIR': str(self.root / 'project'), 'BUILD_SUBDIR': 'out/Debug',
                    'PROJECT_PROFILE_ID': 'profile-a', 'PROJECT_PROFILE_REVISION': '2'}
        self.runtime = Path(self.env['PROJECT_DIR']) / 'out/Debug/Bin/runtimelibrary'
        self.runtime.mkdir(parents=True)
        self.source = self.root / 'external.xml'
        self.raw = (b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-8"?>\r\n'
            b'<!-- original -->\r\n<RuntimeSchema name="actual-task">\r\n'
            b'  <PathlossDirectory>../actual-output</PathlossDirectory>\r\n'
            b'  <EngineeringFilePath>inputs/cells.csv</EngineeringFilePath>\r\n'
            b'  <Unknown alpha="1">keep</Unknown><Unknown>duplicate</Unknown>\r\n'
            b'</RuntimeSchema>\r\n')
        self.source.write_bytes(self.raw)

    def preview(self, name='imported.xml'):
        return runtime_configs.preview_runtime_import(self.env, str(self.source), name)

    def confirm(self, preview, env=None, name='imported.xml'):
        return runtime_configs.import_runtime_config(env or self.env, str(self.source), name, preview['token'])

    def test_import_preserves_all_bytes_name_and_paths_without_manifest(self):
        before = (self.source.read_bytes(), self.source.stat().st_mtime_ns)
        preview = self.preview()
        self.assertFalse(preview['conflict'])
        self.assertFalse(preview['same_file'])
        self.assertEqual(preview['runtime_name'], 'actual-task')
        self.assertTrue(preview['out_dir'].replace('\\', '/').endswith('/actual-output/actual-task'))
        self.assertFalse((self.runtime / 'imported.xml').exists())
        imported = self.confirm(preview)
        self.assertEqual(imported['schema'], 'imported.xml')
        self.assertEqual(imported['runtime_name'], 'actual-task')
        self.assertEqual(imported['revision'], hashlib.sha256(self.raw).hexdigest())
        self.assertEqual((self.runtime / 'imported.xml').read_bytes(), self.raw)
        self.assertEqual((self.source.read_bytes(), self.source.stat().st_mtime_ns), before)
        self.assertEqual(sorted(item.name for item in self.runtime.iterdir()), ['imported.xml'])

    def test_relative_source_or_non_runtime_root_is_rejected(self):
        with self.assertRaises(ValueError):
            runtime_configs.preview_runtime_import(self.env, 'external.xml', 'new.xml')
        self.source.write_text('<SceneSettings/>')
        with self.assertRaisesRegex(ValueError, 'RuntimeSchema'):
            self.preview()

    def test_malformed_and_non_utf8_sources_never_create_destination(self):
        for raw in (b'<RuntimeSchema', b'\xff<RuntimeSchema/>'):
            self.source.write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.preview()
            self.assertEqual(list(self.runtime.iterdir()), [])

    def test_same_file_returns_activation_only_and_does_not_rewrite(self):
        target = self.runtime / 'current.xml'
        target.write_bytes(self.raw)
        manifest = Path(str(target) + '.manifest.json')
        manifest.write_text('{"keep":"existing ownership"}')
        before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in (target, manifest)}
        preview = runtime_configs.preview_runtime_import(self.env, str(target), target.name)
        self.assertTrue(preview['same_file'])
        self.assertFalse(preview['conflict'])
        result = runtime_configs.import_runtime_config(self.env, str(target), target.name, preview['token'])
        self.assertTrue(result['activation_only'])
        self.assertEqual({path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in (target, manifest)}, before)

    def test_existing_xml_or_residual_manifest_is_a_conflict(self):
        for suffix in ('', '.manifest.json'):
            with self.subTest(suffix=suffix):
                existing = self.runtime / ('imported.xml' + suffix)
                existing.write_bytes(b'never overwrite')
                preview = self.preview()
                self.assertTrue(preview['conflict'])
                with self.assertRaisesRegex(ValueError, '存在|冲突'):
                    self.confirm(preview)
                self.assertEqual(existing.read_bytes(), b'never overwrite')
                existing.unlink()

    def test_preview_is_bound_to_source_destination_project_and_build(self):
        preview = self.preview()
        cases = [dict(self.env, PROJECT_DIR=str(self.root / 'other-project')),
                 dict(self.env, BUILD_SUBDIR='out/Release'),
                 dict(self.env, PROJECT_PROFILE_REVISION='3')]
        for env in cases:
            with self.subTest(env=env), self.assertRaisesRegex(ValueError, '预览|变化'):
                self.confirm(preview, env=env)
        with self.assertRaisesRegex(ValueError, '预览|变化'):
            self.confirm(preview, name='different.xml')
        self.source.write_bytes(self.raw + b'<!-- changed -->')
        with self.assertRaisesRegex(ValueError, '预览|变化'):
            self.confirm(preview)
        self.assertFalse((self.runtime / 'imported.xml').exists())

    def test_new_xml_or_manifest_after_preview_prevents_import(self):
        for suffix in ('', '.manifest.json'):
            with self.subTest(suffix=suffix):
                preview = self.preview()
                raced = self.runtime / ('imported.xml' + suffix)
                raced.write_bytes(b'external change')
                with self.assertRaisesRegex(ValueError, '预览|变化|存在|冲突'):
                    self.confirm(preview)
                self.assertEqual(raced.read_bytes(), b'external change')
                if suffix:
                    self.assertFalse((self.runtime / 'imported.xml').exists())
                raced.unlink()

    def test_publication_competitor_is_never_overwritten_or_rolled_back(self):
        preview = self.preview()
        target = self.runtime / 'imported.xml'
        original_link = runtime_configs.os.link
        def compete(source, destination):
            Path(destination).write_bytes(b'concurrent XML')
            return original_link(source, destination)
        with patch.object(runtime_configs.os, 'link', side_effect=compete):
            with self.assertRaises((ValueError, OSError)):
                self.confirm(preview)
        self.assertEqual(target.read_bytes(), b'concurrent XML')
        self.assertEqual(sorted(path.name for path in self.runtime.iterdir()), ['imported.xml'])

    def test_manifest_created_during_publication_rolls_back_only_new_copy(self):
        preview = self.preview()
        target = self.runtime / 'imported.xml'
        original_link = runtime_configs.os.link
        def compete(source, destination):
            result = original_link(source, destination)
            Path(str(destination) + '.manifest.json').write_bytes(b'concurrent manifest')
            return result
        with patch.object(runtime_configs.os, 'link', side_effect=compete):
            with self.assertRaisesRegex(ValueError, '存在|变化|冲突'):
                self.confirm(preview)
        self.assertFalse(target.exists())
        self.assertEqual(Path(str(target) + '.manifest.json').read_bytes(), b'concurrent manifest')

    def test_publication_error_leaves_no_partial_target_and_source_unchanged(self):
        preview = self.preview()
        with patch.object(runtime_configs.os, 'link', side_effect=PermissionError('file busy')):
            with self.assertRaises(OSError):
                self.confirm(preview)
        self.assertEqual(list(self.runtime.iterdir()), [])
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_busy_temporary_cleanup_reports_warning_after_successful_import(self):
        preview = self.preview()
        original_unlink = Path.unlink
        def busy_temporary(path, *args, **kwargs):
            if path.parent == self.runtime and path.name.startswith('.imported.xml.') and path.suffix == '.tmp':
                raise PermissionError('temporary held by another program')
            return original_unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', busy_temporary):
            result = self.confirm(preview)
        self.assertTrue(result['imported'])
        self.assertEqual((self.runtime / 'imported.xml').read_bytes(), self.raw)
        pending = [path for path in self.runtime.iterdir() if path.suffix == '.tmp']
        self.assertEqual(len(pending), 1)
        self.assertIn(str(pending[0]), result['cleanup_warning'])
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_busy_temporary_cleanup_does_not_mask_the_publication_error(self):
        preview = self.preview()
        original_unlink = Path.unlink
        def busy_temporary(path, *args, **kwargs):
            if path.parent == self.runtime and path.name.startswith('.imported.xml.') and path.suffix == '.tmp':
                raise PermissionError('temporary held by another program')
            return original_unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', busy_temporary), \
             patch.object(runtime_configs.os, 'link', side_effect=OSError('original publication failure')):
            with self.assertRaisesRegex(OSError, 'original publication failure'):
                self.confirm(preview)
        self.assertFalse((self.runtime / 'imported.xml').exists())
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_external_edit_after_publication_is_preserved_when_manifest_conflicts(self):
        preview = self.preview()
        target = self.runtime / 'imported.xml'
        original_link = runtime_configs.os.link
        def compete(source, destination):
            result = original_link(source, destination)
            Path(destination).write_bytes(b'external edit after publication')
            Path(str(destination) + '.manifest.json').write_bytes(b'concurrent manifest')
            return result
        with patch.object(runtime_configs.os, 'link', side_effect=compete):
            with self.assertRaisesRegex(ValueError, '存在|变化|冲突'):
                self.confirm(preview)
        self.assertEqual(target.read_bytes(), b'external edit after publication')
        self.assertEqual(self.source.read_bytes(), self.raw)


if __name__ == '__main__':
    unittest.main()
