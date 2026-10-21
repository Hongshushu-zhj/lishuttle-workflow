from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core
from server import Api


class RuntimeResourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'ThirdPart/Config'
        self.dll = self.root / 'ThirdPart/Dll/Release'
        self.bin = self.root / 'build/Bin'
        self.config.mkdir(parents=True)
        self.dll.mkdir(parents=True)
        self.env = dict(PROJECT_DIR=self.root.as_posix(), BUILD_SUBDIR='build',
                        CONFIG_SRC='ThirdPart/Config', DLL_SRC='ThirdPart/Dll/Release')
        for name, data in [('config/cellformat.xml', b'<Cell/>'),
                           ('config/scenesettings.xml', b'<Scene/>'),
                           ('models/cells/default.xml', b'<Model/>'),
                           ('antennas/nested/beam.txt', b'beam'),
                           ('runtimelibrary/runtimeschema.xml', b'<RuntimeSchema/>'),
                           ('lishuttlesign', b'sign'), ('log4cpp.conf', b'config-log'),
                           ('config/ignore.xml.bak', b'backup')]:
            path = self.config / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (self.dll / 'uplancommon.dll').write_bytes(b'dll')
        (self.dll / 'log4cpp.conf').write_bytes(b'dll-log')

    def test_missing_bin_copies_full_tree_dll_and_flat_config_xml(self):
        result = core.ensure_runtime_resources(self.env)
        self.assertEqual((self.bin / 'models/cells/default.xml').read_bytes(), b'<Model/>')
        self.assertEqual((self.bin / 'antennas/nested/beam.txt').read_bytes(), b'beam')
        self.assertEqual((self.bin / 'uplancommon.dll').read_bytes(), b'dll')
        self.assertEqual((self.bin / 'cellformat.xml').read_bytes(), b'<Cell/>')
        self.assertEqual((self.bin / 'config/cellformat.xml').read_bytes(), b'<Cell/>')
        self.assertEqual((self.bin / 'log4cpp.conf').read_bytes(), b'dll-log')
        self.assertFalse((self.bin / 'config/ignore.xml.bak').exists())
        self.assertEqual(len(result['copied']), 10)
        self.assertTrue(all(a['from'].startswith(self.root.as_posix()) for a in result['copied']))

    def test_repeat_assembly_keeps_customized_files_byte_for_byte(self):
        custom = {'runtimelibrary/runtimeschema.xml': b'edited XML\r\n',
                  'runtimelibrary/job.xml': b'job XML', 'antennas/nested/beam.txt': b'task beam',
                  'models/cells/default.xml': b'calibrated model', 'uplancommon.dll': b'existing dll'}
        for name, data in custom.items():
            p = self.bin / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        core.ensure_runtime_resources(self.env)
        for name, data in custom.items():
            self.assertEqual((self.bin / name).read_bytes(), data)
        again = core.ensure_runtime_resources(self.env)
        self.assertEqual(again['copied'], [])

    def test_missing_dll_source_fails_before_copying_anything(self):
        self.env['DLL_SRC'] = 'missing'
        with self.assertRaisesRegex(ValueError, '动态库'):
            core.ensure_runtime_resources(self.env)
        self.assertFalse(self.bin.exists())

    def test_empty_dll_source_does_not_report_complete_assembly(self):
        for path in self.dll.iterdir():
            path.unlink()
        with self.assertRaisesRegex(ValueError, '动态库'):
            core.ensure_runtime_resources(self.env)
        self.assertFalse(self.bin.exists())

    def test_unreadable_source_stops_instead_of_silently_skipping(self):
        def walk(path, **kwargs):
            kwargs['onerror'](PermissionError('cannot read resources'))
            return iter(())
        with patch.object(core.os, 'walk', side_effect=walk):
            with self.assertRaises(PermissionError):
                core.ensure_runtime_resources(self.env)
        self.assertFalse(self.bin.exists())

    def test_overlapping_source_is_rejected(self):
        self.env['CONFIG_SRC'] = '.'
        with self.assertRaises(ValueError):
            core.ensure_runtime_resources(self.env)
        self.assertFalse(self.bin.exists())

    def test_api_stages_before_render_and_then_overlays_selected_task(self):
        task = dict(name='task', dir=str(self.root / 'task'), has_antennas=True)
        order = []
        def stage(env):
            order.append('base')
            return {'copied': [], 'kept_count': 0}
        def render(job):
            order.append('render')
            return 0, 'render output'
        def overlay(*args, **kwargs):
            order.append('task')
            return []
        def launch(*args):
            order.append('launch')
            return {'path': 'project/.vs/launch.vs.json', 'entries': ['cali']}
        with patch.object(core, 'load_env', return_value=self.env), \
             patch.object(core, 'scan_tasks', return_value=([task], 'tasks')), \
             patch.object(core, 'validate_engineering', return_value='engineering.csv'), \
             patch.object(core, 'ensure_runtime_resources', side_effect=stage), \
             patch.object(core, 'build_job_env', return_value='job.env'), \
             patch.object(core, 'run_render', side_effect=render), \
             patch.object(core, 'schema_path', return_value=__file__), \
             patch.object(core, 'assemble_files', side_effect=overlay), \
             patch.object(core, 'sync_vs_launch', side_effect=launch) as sync:
            result = Api.render(dict(job_name='job', task=task, copy_antennas=True, copy_files=True))
        self.assertEqual(order, ['base', 'render', 'task', 'launch'])
        sync.assert_called_once_with(self.env, 'job.xml', 'pl', '1', 'outdoor')
        self.assertNotIn('error', result)
        self.assertIn('base_resources', result)
        self.assertIn('vs_launch', result)

    def test_launch_sync_failure_is_visible_and_failed_render_does_not_sync(self):
        task = dict(name='task', dir=str(self.root / 'task'), has_antennas=False)
        with patch.object(core, 'load_env', return_value=self.env), \
             patch.object(core, 'scan_tasks', return_value=([task], 'tasks')), \
             patch.object(core, 'validate_engineering', return_value='engineering.csv'), \
             patch.object(core, 'build_job_env', return_value='job.env'), \
             patch.object(core, 'run_render', return_value=(0, 'ok')) as render, \
             patch.object(core, 'schema_path', return_value=__file__), \
             patch.object(core, 'sync_vs_launch', side_effect=ValueError('JSON 无效')) as sync:
            result = Api.render(dict(job_name='job', task=task))
            self.assertIn('JSON 无效', result['vs_launch_warning'])
            self.assertTrue(result['schema_ok'])
            sync.reset_mock()
            render.return_value = (1, 'failed')
            result = Api.render(dict(job_name='job', task=task))
            sync.assert_not_called()

    def test_preview_never_copies_and_missing_sources_stop_render(self):
        task = dict(name='task', dir=str(self.root / 'task'), has_antennas=False)
        preview = dict(token='token', runtime_name='n', out_dir='out', changes=[], warnings=[])
        with patch.object(core, 'load_env', return_value=self.env), \
             patch.object(core, 'scan_tasks', return_value=([task], 'tasks')), \
             patch.object(core, 'preview_task_schema', return_value=preview), \
             patch.object(core, 'ensure_runtime_resources', side_effect=ValueError('缺少动态库')) as stage, \
             patch.object(core, 'build_job_env') as build:
            body = dict(job_name='job', task=task, use_existing_schema=True)
            self.assertEqual(Api.preview_render(body)['token'], 'token')
            stage.assert_not_called()
            result = Api.render(dict(body, preview_token='token'))
            self.assertIn('动态库', result['error'])
            build.assert_not_called()


if __name__ == '__main__':
    unittest.main()
