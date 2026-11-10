"""Existing XML selection must not become another rendering operation."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core
from server import Api


class RuntimeConfigApiTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.project = self.root / 'project'
        self.runtime = self.project / 'build/Bin/runtimelibrary'
        self.runtime.mkdir(parents=True)
        self.env_file = self.root / 'env/local-win.env'
        self.env_file.parent.mkdir()
        self.env_file.write_text('PROJECT_DIR="' + self.project.as_posix() + '"\n'
            'BUILD_SUBDIR="build"\nEXE_NAME="fixture.exe"\n', encoding='utf-8')
        for name, value in [('ENV_FILE', str(self.env_file)),
                            ('ordered_functions', lambda: [{'name': 'pred'}, {'name': 'predindoor'}])]:
            p = patch.object(core, name, value); p.start(); self.addCleanup(p.stop)
        self.schema = self.runtime / 'saved.xml'
        self.raw = ('\ufeff<RuntimeSchema name="actual-task"><!-- keep -->'
            '<MapFormat>indoor</MapFormat><EngineeringFilePath>inputs/ap.csv</EngineeringFilePath>'
            '<PathlossDirectory>custom-output</PathlossDirectory><MaxDeepth>3</MaxDeepth>'
            '<Unknown>keep</Unknown></RuntimeSchema>').encode('utf-8')
        self.schema.write_bytes(self.raw)

    def listing(self):
        return Api.runtime_configs({})

    def activate(self, **changes):
        listing = self.listing()
        body = dict(schema='saved.xml', revision=hashlib.sha256(self.schema.read_bytes()).hexdigest(),
                    scope=listing['scope'], func='predindoor', task_id='7')
        body.update(changes)
        return Api.activate_runtime_config(body)

    def test_load_remembers_selection_without_touching_xml_or_assembly(self):
        modified = self.schema.stat().st_mtime_ns
        with patch.object(core, 'run_render', side_effect=AssertionError('must not render')), \
             patch.object(core, 'ensure_runtime_resources', side_effect=AssertionError('must not stage')), \
             patch.object(core, 'start_lishuttle', side_effect=AssertionError('must not run')):
            response = self.activate()
        self.assertTrue(response['ok'], response)
        self.assertEqual(response['job'], dict(schema='saved.xml', name='actual-task',
            func='predindoor', taskId='7', outDir=(self.runtime.parent / 'custom-output/actual-task').as_posix(), mode='existing'))
        self.assertEqual(response['inputs']['engineering_file'], (self.runtime.parent / 'inputs/ap.csv').as_posix())
        self.assertTrue(response['validation_required'])
        self.assertEqual((self.schema.read_bytes(), self.schema.stat().st_mtime_ns), (self.raw, modified))
        self.assertEqual(list(self.runtime.iterdir()), [self.schema])
        selected = self.listing()['selected']
        self.assertEqual((selected['schema'], selected['func'], selected['task_id']), ('saved.xml', 'predindoor', '7'))
        self.assertNotIn('preflight', selected)
        self.assertNotIn('sid', selected)

    def test_load_rejects_stale_file_scope_project_and_unsupported_function(self):
        for change in ({'revision': 'old'}, {'scope': 'old-build'}, {'_project': '/old-project'}, {'func': 'unsupported'}):
            with self.subTest(change=change):
                response = self.activate(**change)
                self.assertFalse(response.get('ok', False), response)
                self.assertTrue(response.get('error') or response.get('message'))
        self.assertEqual(self.schema.read_bytes(), self.raw)

    def test_missing_selection_record_does_not_create_files_on_list(self):
        result = self.listing()
        self.assertIsNone(result['selected'])
        self.assertFalse(self.env_file.with_name('project-profiles.json').exists())
        self.assertEqual(self.schema.read_bytes(), self.raw)

    def test_params_supplies_current_xml_engineering_path_without_task_package(self):
        result = Api.params(dict(schema=['saved.xml'], func=['predindoor']))
        self.assertNotIn('error', result)
        self.assertEqual(result['inputs']['engineering_file'], (self.runtime.parent / 'inputs/ap.csv').as_posix())

    def test_preflight_reports_rejected_filename_without_raising(self):
        report = Api.preflight(dict(schema='CON.xml', func='predindoor', task_id='1'))
        self.assertFalse(report['ok'])
        self.assertEqual(report['issues'][0]['code'], 'SCHEMA_NAME_INVALID')

    def test_current_schema_directory_browsing_uses_actual_name_and_output(self):
        target = self.runtime.parent / 'custom-output/actual-task'
        target.mkdir(parents=True)
        (target / 'evidence.txt').write_text('fixture')
        result = Api.results(dict(schema=['saved.xml']))
        self.assertEqual(result['dir'], target.as_posix())
        self.assertTrue(result['exists'])
        self.assertFalse(result['associated'])
        self.assertEqual(result['verdict'], 'unconfirmed')

    def test_saved_selection_is_not_shared_with_another_build(self):
        self.assertTrue(self.activate()['ok'])
        env = core.load_env()
        store = core.ProjectStore(core.ENV_FILE)
        store.save({'BUILD_SUBDIR': 'release'}, env['PROJECT_PROFILE_REVISION'])
        self.assertIsNone(self.listing()['selected'])
        env = core.load_env()
        store.save({'BUILD_SUBDIR': 'build'}, env['PROJECT_PROFILE_REVISION'])
        self.assertEqual(self.listing()['selected']['schema'], 'saved.xml')

    def test_import_preview_confirm_preserves_source_and_selects_copy(self):
        source = self.root / 'external.xml'
        source.write_bytes(self.raw)
        body = dict(source=source.as_posix(), destination_schema='imported.xml', scope=self.listing()['scope'])
        preview = Api.preview_runtime_import(body)
        self.assertNotIn('error', preview)
        self.assertFalse((self.runtime / 'imported.xml').exists())
        result = Api.import_runtime_config(dict(body, token=preview['token'], func='predindoor', task_id='8'))
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['job']['schema'], 'imported.xml')
        self.assertEqual((self.runtime / 'imported.xml').read_bytes(), self.raw)
        self.assertEqual(source.read_bytes(), self.raw)
        self.assertFalse((self.runtime / 'imported.xml.manifest.json').exists())

    def test_selection_and_import_reserve_runtime_before_reading_project(self):
        with core.RUNTIME.operation('fixture busy') as token:
            core.RUNTIME.bind(token, 987)
        self.addCleanup(lambda: core.RUNTIME.release(token))
        with patch.object(core, 'load_env', side_effect=AssertionError('must reject before reading')):
            for name in ('activate_runtime_config', 'import_runtime_config'):
                result = getattr(Api, name)({})
                self.assertEqual(result['code'], 'RUNTIME_BUSY')

    def test_cleanup_without_ui_selection_protects_saved_configuration(self):
        self.assertTrue(self.activate()['ok'])
        with patch('runtime_cleanup.cleanup_plan', return_value={'keep_schema': 'saved.xml'}) as cleanup:
            response = Api.cleanup_configs({})
        self.assertEqual(response['keep_schema'], 'saved.xml')
        self.assertEqual(cleanup.call_args.args[-1], 'saved.xml')
        other = self.runtime / 'manual.xml'
        other.write_bytes(self.raw)
        with patch('runtime_cleanup.cleanup_plan', return_value={'keep_schema': 'manual.xml'}) as cleanup:
            Api.cleanup_configs({'keep_schema': 'manual.xml'})
        self.assertEqual(cleanup.call_args.args[-1], 'manual.xml')

    def test_invalid_function_does_not_publish_an_import(self):
        source = self.root / 'external.xml'
        source.write_bytes(self.raw)
        body = dict(source=source.as_posix(), destination_schema='imported.xml', scope=self.listing()['scope'])
        preview = Api.preview_runtime_import(body)
        result = Api.import_runtime_config(dict(body, token=preview['token'], func='unsupported', task_id='1'))
        self.assertFalse(result['ok'])
        self.assertFalse((self.runtime / 'imported.xml').exists())

    def test_invalid_task_id_does_not_publish_an_import(self):
        source = self.root / 'external.xml'
        source.write_bytes(self.raw)
        body = dict(source=source.as_posix(), destination_schema='imported.xml', scope=self.listing()['scope'])
        preview = Api.preview_runtime_import(body)
        for task_id in ('abc', '-1', '2147483648', '1.5', ''):
            with self.subTest(task_id=task_id):
                result = Api.import_runtime_config(dict(body, token=preview['token'], func='predindoor', task_id=task_id))
                self.assertFalse(result['ok'], result)
                self.assertFalse((self.runtime / 'imported.xml').exists())

    def test_import_reports_success_when_only_selection_memory_fails(self):
        source = self.root / 'external.xml'
        source.write_bytes(self.raw)
        body = dict(source=source.as_posix(), destination_schema='imported.xml', scope=self.listing()['scope'])
        preview = Api.preview_runtime_import(body)
        with patch.object(Api, '_remember_runtime', side_effect=OSError('profile locked')):
            result = Api.import_runtime_config(dict(body, token=preview['token'], func='predindoor', task_id='1'))
        self.assertTrue(result['ok'], result)
        self.assertTrue(result['imported'])
        self.assertIn('profile locked', result['selection_warning'])
        self.assertEqual((self.runtime / 'imported.xml').read_bytes(), self.raw)


if __name__ == '__main__':
    unittest.main()
