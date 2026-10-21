import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core
import render_schema as renderer
from task_schema import render_existing, OUTDOOR_PATHS
from server import Api


class TaskSchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'task'
        self.folder.mkdir()
        self.source = self.folder / 'schema_job.xml'
        self.text = ('\ufeff<?xml version="1.0" encoding="utf-8"?>\r\n'
                     '<RuntimeSchema name="original-name">\r\n'
                     '  <!-- 注释 <PathlossDirectory>unchanged</PathlossDirectory> ${KEEP} -->\r\n'
                     '  <MapFormat>indoor</MapFormat>\r\n'
                     '  <MapPath>old-map</MapPath>\r\n'
                     '  <PolygonFilePath />\r\n'
                     '  <PathlossDirectory>old-output</PathlossDirectory>\r\n'
                     '  <EngineeringFilePath>old.csv</EngineeringFilePath>\r\n'
                     '  <SceneSettingsPath>old-scene.xml</SceneSettingsPath>\r\n'
                     '  <MaxCalcHeight>123</MaxCalcHeight>\r\n'
                     '  <DefaultCalcResolution>0.17</DefaultCalcResolution>\r\n'
                     '  <Unknown value="keep"/>\r\n'
                     '</RuntimeSchema>\r\n')
        self.source.write_bytes(self.text.encode('utf-8'))
        self.env = dict(PROJECT_DIR=self.root.as_posix(), BUILD_SUBDIR='build',
                        EXE_NAME='lishuttle.exe', CONFIG_SRC='config', MAP_ROOT='maps',
                        OUT_ROOT=self.root.as_posix() + '/outputs', GONGCAN_ROOT=str(self.root))
        self.job = dict(JOB_NAME='new-file', SCHEMA_NAME='new-file.xml', FUNC='plindoor',
                        TEMPLATE='runtimeschema-indoor.xml.tpl', MAP_PATH='new & map',
                        ENGINEERING_FILE='selected.csv', POLYGON_FILE='',
                        MAX_CALC_HEIGHT='3', DEFAULT_FLOOR_HEIGHT='3',
                        SCHEMA_SOURCE=self.source.as_posix(), SYNC_ENGINEERING='0')

    def render(self):
        with contextlib.redirect_stdout(io.StringIO()):
            renderer.do_render(self.env, self.job, 'test', renderer.ROOT + '/jobs/test.env',
                               renderer.ROOT + '/env/test.env')
        return self.root / 'build/Bin/runtimelibrary/new-file.xml'

    def test_scanner_only_offers_runtime_schema_roots(self):
        (self.folder / 'antenna.xml').write_text('<Antennas/>')
        (self.folder / 'broken.xml').write_text('<RuntimeSchema>')
        with patch.object(core, 'load_env', return_value=self.env):
            task = core.scan_tasks()[0][0]
        self.assertEqual([c['path'] for c in task['schema_candidates']], [self.source.as_posix()])

    def test_reuse_changes_only_requested_paths_byte_for_byte(self):
        output = self.render().read_bytes().decode('utf-8')
        expected = self.text.replace('>old-map<', '>new &amp; map<').replace(
            '>old-output<', '>' + self.env['OUT_ROOT'] + '<')
        self.assertEqual(output, expected)
        self.assertEqual(self.source.read_bytes().decode('utf-8'), self.text)

    def test_optional_engineering_sync(self):
        self.job['SYNC_ENGINEERING'] = '1'
        self.assertIn('<EngineeringFilePath>selected.csv</EngineeringFilePath>',
                      self.render().read_text(encoding='utf-8-sig'))

    def test_missing_required_tag_fails_without_writing_destination(self):
        self.source.write_bytes(self.text.replace('<MapPath>old-map</MapPath>', '').encode('utf-8'))
        with self.assertRaisesRegex((SystemExit, ValueError), 'MapPath'):
            self.render()
        self.assertFalse((self.root / 'build/Bin/runtimelibrary/new-file.xml').exists())

    def test_existing_destination_is_backed_up(self):
        output = self.root / 'build/Bin/runtimelibrary/new-file.xml'
        output.parent.mkdir(parents=True)
        output.write_bytes(b'previous configuration')
        self.render()
        self.assertEqual(Path(str(output) + '.bak').read_bytes(), b'previous configuration')

    def test_manifest_cli_and_results_use_preserved_name(self):
        output = self.render()
        manifest = json.loads(Path(str(output) + '.manifest.json').read_text(encoding='utf-8'))
        expected = self.env['OUT_ROOT'] + '/original-name'
        self.assertEqual(manifest['run']['out_dir'], expected)
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            renderer.do_print_run(renderer.build_table(self.env, self.job))
        self.assertIn('OUT_DIR=' + expected, stdout.getvalue())
        with patch.object(core, 'load_env', return_value=self.env):
            self.assertEqual(core.results('new-file')['dir'], expected)

    def test_outdoor_only_allowed_paths_change(self):
        paths = ''.join(f'<{tag}>old/{rel}</{tag}>' for tag, rel in OUTDOOR_PATHS.items())
        self.text = self.text.replace('<MapFormat>indoor</MapFormat>', '').replace(
            '<MapPath>old-map</MapPath>', paths + '<ClutterMatchPath>old-match.xml</ClutterMatchPath>')
        self.source.write_bytes(self.text.encode('utf-8'))
        self.job.pop('TEMPLATE')
        self.job.update(CITY='new-city', POLYGON_FILE='region.txt')
        table = renderer.build_table(self.env, self.job)
        result = render_existing(table)
        import re
        allowed = set(OUTDOOR_PATHS) | {'ClutterMatchPath', 'PolygonFilePath', 'PathlossDirectory'}
        def mask(text):
            parts = re.split(r'(<!--.*?-->)', text, flags=re.S)
            for i in range(0, len(parts), 2):
                for tag in allowed:
                    parts[i] = re.sub(rf'<{tag}\b[^>]*(?:/>|>[^<]*</{tag}>)', f'<{tag}>PATH</{tag}>', parts[i])
            return ''.join(parts)
        self.assertEqual(mask(self.text), mask(result['text']))
        self.assertEqual({c['tag'] for c in result['changes']}, allowed)

    def preview_body(self):
        with patch.object(core, 'load_env', return_value=self.env):
            task = core.scan_tasks()[0][0]
        return dict(job_name='new-file', task=task, city='indoor-map', city_kind='indoor',
                    func='plindoor', use_existing_schema=True, schema_source=self.source.as_posix(),
                    sync_engineering=False, polygon_file='', copy_files=True)

    def test_api_preview_does_not_write_and_rejects_changed_source(self):
        body = self.preview_body()
        with patch.object(core, 'load_env', return_value=self.env), patch.object(core, 'build_job_env') as build:
            preview = Api.preview_render(body)
            self.assertIn('token', preview)
            build.assert_not_called()
            self.source.write_bytes(self.text.replace('>123<', '>124<').encode('utf-8'))
            result = Api.render(dict(body, preview_token=preview['token']))
            self.assertIn('error', result)
            build.assert_not_called()

    def test_api_apply_persists_reuse_and_skips_shared_resource_changes(self):
        body = self.preview_body()
        def render_job(path):
            job = renderer.read_env_file(path, 'job')
            with contextlib.redirect_stdout(io.StringIO()):
                rc = renderer.do_render(self.env, job, 'test', renderer.ROOT + '/jobs/test.env',
                                        renderer.ROOT + '/env/test.env')
            return rc, ''
        with patch.object(core, 'load_env', return_value=self.env), \
                patch.object(core, 'JOBS_DIR', str(self.root)), \
                patch.object(core, 'run_render', side_effect=render_job), \
                patch.object(core, 'ensure_runtime_resources', return_value={}), \
                patch.object(core, 'assemble_files') as assemble:
            preview = Api.preview_render(body)
            result = Api.render(dict(body, preview_token=preview['token']))
            self.assertNotIn('error', result)
            self.assertTrue(result['schema_ok'])
            self.assertEqual(result['out_dir'], self.env['OUT_ROOT'] + '/original-name')
            saved_job = renderer.read_env_file(str(self.root / 'web-new-file.env'), 'job')
            self.assertEqual(saved_job['SCHEMA_SOURCE'], self.source.as_posix())
            self.assertEqual(saved_job['SYNC_ENGINEERING'], '0')
            assemble.assert_not_called()
        self.assertEqual(self.source.read_bytes().decode('utf-8'), self.text)

    def test_sync_requires_a_valid_selected_engineering_file(self):
        body = self.preview_body()
        with patch.object(core, 'load_env', return_value=self.env), patch.object(core, 'build_job_env') as build:
            result = Api.preview_render(dict(body, sync_engineering=True))
        self.assertIn('error', result)
        build.assert_not_called()

    def test_cli_uses_current_destination_without_original_source(self):
        output = self.render()
        output.write_bytes(output.read_bytes().replace(b'name="original-name"', b'name="edited-name"'))
        self.source.unlink()
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            renderer.do_print_run(renderer.build_table(self.env, self.job))
        self.assertIn('OUT_DIR=' + self.env['OUT_ROOT'] + '/edited-name', stdout.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            renderer.do_render(self.env, self.job, 'test', 'job.env', 'env.env', write_output=False)
        self.assertIn(self.env['OUT_ROOT'] + '/edited-name', stdout.getvalue())

    def test_relative_engineering_input_is_checked_from_executable_directory(self):
        exe_dir = self.root / 'build/Bin'
        exe_dir.mkdir(parents=True)
        (exe_dir / 'old.csv').write_text('valid placeholder')
        map_dir = self.root / 'map'
        map_dir.mkdir()
        (map_dir / 'building.das').write_text('valid placeholder')
        self.job['MAP_PATH'] = map_dir.as_posix()
        with contextlib.redirect_stdout(io.StringIO()):
            rc = renderer.do_render(self.env, self.job, 'test', renderer.ROOT + '/jobs/test.env',
                                    renderer.ROOT + '/env/test.env')
        self.assertEqual(rc, 0)

    def test_cli_pre_render_metadata_can_repair_malformed_destination(self):
        output = self.render()
        output.write_text('<broken', encoding='utf-8')
        def load(_path, label):
            return self.env if label == '环境文件' else self.job
        args = ['render_schema.py', 'jobs/test.env', 'test', '--print-run', '--prepare-render']
        with patch.object(sys, 'argv', args), patch.object(renderer, 'read_env_file', side_effect=load), \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            renderer.main()
        self.assertIn('OUT_DIR=' + self.env['OUT_ROOT'] + '/original-name', stdout.getvalue())
        # --no-render 必须校验实际目标，不能悄悄回退到源配置。
        with patch.object(sys, 'argv', args + ['--no-render']), \
                patch.object(renderer, 'read_env_file', side_effect=load), \
                self.assertRaises(ValueError):
            renderer.main()


if __name__ == '__main__':
    unittest.main()
