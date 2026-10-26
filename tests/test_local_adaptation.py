"""Local path defaults and CSV-owned cell radius regression coverage."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core
from server import Api


class LocalAdaptationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(PROJECT_DIR=self.root.as_posix(), BUILD_SUBDIR='build',
                        EXE_NAME='engine.exe', CONFIG_SRC='config',
                        MAP_ROOT=(self.root / 'maps').as_posix(),
                        OUT_ROOT=(self.root / 'outputs').as_posix(), DT_ROOT='D:/drive-test')
        self.csv = self.root / 'cells.csv'
        self.csv.write_text('小区,计算半径(m),备注\nCell ID,CalcRadius,Note\na,100,keep\nb,250,保留\n', encoding='utf-8-sig')
        self.schema = self.root / 'build/Bin/runtimelibrary/job.xml'
        self.schema.parent.mkdir(parents=True)
        self.schema.write_text('<RuntimeSchema name="job"><EngineeringFilePath>' + self.csv.as_posix() +
                               '</EngineeringFilePath><DefaultCalcRadius>800</DefaultCalcRadius></RuntimeSchema>', encoding='utf-8')
        self.original = self.schema.read_bytes()
        self.patcher = patch.object(core, 'load_env', return_value=self.env)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_radius_edit_updates_csv_and_keeps_xml_default(self):
        before = self.csv.read_bytes()
        result = Api.param_write(dict(schema='job.xml', tag='DefaultCalcRadius', value='350'))
        self.assertTrue(result['ok'], result)
        self.assertEqual([row[1] for row in core.read_csv_grid(str(self.csv))['rows']], ['350', '350'])
        self.assertEqual(self.schema.read_bytes(), self.original)
        self.assertEqual(Path(str(self.csv) + '.bak').read_bytes(), before)

    def test_radius_params_show_each_csv_value_and_xml_fallback_separately(self):
        result = Api.params(dict(schema=['job.xml'], func=['pl']))
        source = result.get('param_sources', {}).get('DefaultCalcRadius', {})
        self.assertEqual(source.get('kind'), 'engineering_csv')
        self.assertEqual(source['values'], ['100', '250'])
        self.assertEqual(source['fallback'], '800')
        self.assertEqual(source['path'], self.csv.as_posix())

    def test_radius_default_restore_cannot_overwrite_csv_or_xml(self):
        before = self.csv.read_bytes()
        with patch.object(core, 'thirdpart_defaults', return_value={
                'DefaultCalcRadius': dict(available=True, value='800', source='sample')}):
            result = Api.param_default(dict(schema='job.xml', tag='DefaultCalcRadius'))
        self.assertFalse(result['ok'])
        self.assertEqual(self.csv.read_bytes(), before)
        self.assertEqual(self.schema.read_bytes(), self.original)

    def test_real_engineering_radius_header_and_gbk_encoding(self):
        self.csv.write_bytes(('小区ID,小区计算半径,备注\r\nCell ID,Main Calculation Radius (m),Note\r\n'
                              'a,150,中文\r\nb,200,保留\r\n').encode('gb18030'))
        before = self.csv.read_bytes()
        result = Api.param_write(dict(schema='job.xml', tag='DefaultCalcRadius', value='125'))
        self.assertTrue(result['ok'], result)
        data = self.csv.read_bytes().decode('gb18030')
        self.assertIn('a,125,中文\r\n', data)
        self.assertIn('b,125,保留\r\n', data)
        self.assertEqual(Path(str(self.csv) + '.bak').read_bytes(), before)
        self.assertEqual(self.schema.read_bytes(), self.original)

    def test_english_only_radius_header_is_supported(self):
        self.csv.write_text('ID,半径\nCell ID,Main Calculation Radius (m)\na,175\n', encoding='utf-8-sig')
        result = Api.param_write(dict(schema='job.xml', tag='DefaultCalcRadius', value='225'))
        self.assertTrue(result['ok'], result)
        self.assertEqual(core.radius_source('job.xml')['values'], ['225'])

    def test_radius_relative_csv_path_uses_engine_working_directory(self):
        local = self.schema.parent.parent / 'data/cells.csv'
        local.parent.mkdir()
        local.write_bytes(self.csv.read_bytes())
        self.schema.write_text(self.schema.read_text().replace(self.csv.as_posix(), 'data/cells.csv'), encoding='utf-8')
        before = self.csv.read_bytes()
        result = Api.param_write(dict(schema='job.xml', tag='DefaultCalcRadius', value='180'))
        self.assertTrue(result['ok'], result)
        self.assertEqual(core.read_csv_grid(str(local))['rows'][0][1], '180')
        self.assertEqual(self.csv.read_bytes(), before)

    def test_missing_csv_radius_column_refuses_xml_edit(self):
        self.csv.write_text('小区,备注\nCell ID,Note\na,keep\n', encoding='utf-8-sig')
        result = Api.param_write(dict(schema='job.xml', tag='DefaultCalcRadius', value='350'))
        self.assertFalse(result['ok'])
        self.assertEqual(self.schema.read_bytes(), self.original)

    def test_invalid_radius_does_not_write_either_file(self):
        before = self.csv.read_bytes()
        for value in ('', 'NaN', 'inf', '-1', 'bad'):
            result = Api.param_write(dict(schema='job.xml', tag='DefaultCalcRadius', value=value))
            self.assertFalse(result['ok'], value)
        self.assertEqual(self.csv.read_bytes(), before)
        self.assertEqual(self.schema.read_bytes(), self.original)

    def test_local_paths_come_from_shared_project_map_and_task_resolution(self):
        source = self.root / 'task.xml'
        from task_schema import OUTDOOR_PATHS
        source.write_text('<RuntimeSchema name="task"><PathlossDirectory>old</PathlossDirectory>'
            '<PolygonFilePath/><EngineeringFilePath>old.csv</EngineeringFilePath>'
            '<SceneSettingsPath>old-scene</SceneSettingsPath><DriverTestFileDictionaryPath>old-dt</DriverTestFileDictionaryPath>'
            '<ClutterMatchPath>old-match</ClutterMatchPath>' +
            ''.join(f'<{tag}>/old/{rel}</{tag}>' for tag, rel in OUTDOOR_PATHS.items()) + '</RuntimeSchema>', encoding='utf-8')
        task = dict(name='task', dir=self.root.as_posix(), scene='', txts=[],
                    schema_candidates=[dict(path=source.as_posix())], engineering_file=self.csv.as_posix())
        with patch.object(Api, '_binding_task', return_value=(task, 'key', self.csv.as_posix(), source.as_posix())), \
                patch.object(core, 'scan_cities', return_value=([dict(name='city', kind='outdoor')], self.env['MAP_ROOT'])):
            result = Api.local_paths(dict(city='city'))
        self.assertNotIn('error', result)
        paths = result['values']
        self.assertEqual(paths['HeightIndexPath'], self.env['MAP_ROOT'] + '/city/heights/index.txt')
        self.assertEqual(paths['SceneSettingsPath'], (self.schema.parent / 'scenesettings.xml').as_posix())
        self.assertEqual(paths['PathlossDirectory'], self.env['OUT_ROOT'])
        self.assertEqual(paths['DriverTestFileDictionaryPath'], self.env['DT_ROOT'])
        self.assertNotIn('PolygonFilePath', paths)
        table = core.build_table(self.env, dict(JOB_NAME='job', CITY='city', SCHEMA_SOURCE=source.as_posix()))
        preview = core.render_existing(table)
        self.assertEqual(preview['scene_settings_file'], paths['SceneSettingsPath'])
        self.assertEqual(preview['drivetest_dir'], paths['DriverTestFileDictionaryPath'])

    def test_real_task_scan_local_paths_and_render_use_task_scene(self):
        folder = self.root / 'tasks/task'
        folder.mkdir(parents=True)
        scene = folder / 'scenesettings.xml'
        scene.write_text('<Scene/>', encoding='utf-8')
        engineering = folder / 'cells.csv'
        engineering.write_text('AP ID,x,y,Floor,Antenna,Power\nAP ID,x,y,Floor,Antenna,Power\na,1,2,1,book,30\n', encoding='utf-8')
        source = folder / 'task.xml'
        source.write_text('<RuntimeSchema name="task"><MapFormat>indoor</MapFormat>'
            '<MapPath>old-map</MapPath><PathlossDirectory>old</PathlossDirectory><PolygonFilePath/>'
            '<EngineeringFilePath>cells.csv</EngineeringFilePath><SceneSettingsPath>old-scene</SceneSettingsPath>'
            '</RuntimeSchema>', encoding='utf-8')
        mapfile = self.root / 'maps/building/building.das'
        mapfile.parent.mkdir(parents=True)
        mapfile.write_bytes(b'map')
        self.env['GONGCAN_ROOT'] = (self.root / 'tasks').as_posix()
        task = core.scan_tasks()[0][0]
        body = dict(task=task, city='building', engineering_file=engineering.as_posix(), schema_source=source.as_posix(),
                    job_name='job', sync_engineering=True, polygon_file='')
        paths = Api.local_paths(body)
        self.assertNotIn('error', paths)
        self.assertEqual(paths['values']['SceneSettingsPath'], scene.as_posix())
        self.assertEqual(paths['values']['MapPath'], mapfile.parent.as_posix())
        preview = core.preview_task_schema(body, task, 'indoor')
        self.assertEqual(preview['scene_settings_file'], scene.as_posix())
        with patch.object(core, 'JOBS_DIR', self.root.as_posix()):
            job_file = core.build_job_env('job', 'plindoor', '1', task, 'building', 'indoor')
        from render_schema import read_env_file
        table = core.build_table(self.env, read_env_file(job_file, 'job'))
        rendered = core.render_existing(table)
        self.assertEqual(rendered['scene_settings_file'], paths['values']['SceneSettingsPath'])
        self.assertEqual(rendered['engineering_file'], engineering.as_posix())
        self.assertIn('old-scene', source.read_text(encoding='utf-8'))

    def test_special_index_relocated_only_when_matching_file_exists(self):
        from task_schema import local_path_values, OUTDOOR_PATHS
        import xml.etree.ElementTree as ET
        root = ET.fromstring('<RuntimeSchema>' + ''.join(
            f'<{tag}>/old/{rel}</{tag}>' for tag, rel in OUTDOOR_PATHS.items()) + '</RuntimeSchema>')
        root.find('BulidVectorIndexPath').text = '/old/map/buildvector/hybrid-original-index.txt'
        table = core.build_table(self.env, dict(CITY='city'))
        values = local_path_values(table, root, strict=False)
        self.assertEqual(values['BulidVectorIndexPath'], '')
        with self.assertRaisesRegex(ValueError, '自定义地图路径'):
            local_path_values(table, root)
        local = self.root / 'maps/city/buildvector/hybrid-original-index.txt'
        local.parent.mkdir(parents=True)
        local.write_text('index')
        self.assertEqual(local_path_values(table, root)['BulidVectorIndexPath'], local.as_posix())

    def test_incomplete_profile_still_returns_map_and_existing_project_scene(self):
        # Reproduce the live profile: only project/map/task roots are configured.
        from task_schema import OUTDOOR_PATHS
        self.env.update(PROJECT_PROFILE_ID='partial', BUILD_SUBDIR='', EXE_NAME='',
                        CONFIG_SRC='', OUT_ROOT='', DT_ROOT='')
        scene = self.root / 'ThirdPart/Config/runtimelibrary/scenesettings.xml'
        scene.parent.mkdir(parents=True)
        scene.write_text('<Scene/>', encoding='utf-8')
        source = self.root / 'task.xml'
        source.write_text('<RuntimeSchema name="task"><PathlossDirectory>old</PathlossDirectory>'
            '<PolygonFilePath/><SceneSettingsPath>old-scene</SceneSettingsPath>'
            '<DriverTestFileDictionaryPath>old-dt</DriverTestFileDictionaryPath>'
            '<ClutterMatchPath>old-match</ClutterMatchPath>' +
            ''.join(f'<{tag}>/old/{rel}</{tag}>' for tag, rel in OUTDOOR_PATHS.items()) + '</RuntimeSchema>', encoding='utf-8')
        task = dict(scene='', schema_candidates=[dict(path=source.as_posix())])
        with patch.object(Api, '_binding_task', return_value=(task, 'key', '', source.as_posix())), \
                patch.object(core, 'scan_cities', return_value=([dict(name='city', kind='outdoor')], self.env['MAP_ROOT'])):
            result = Api.local_paths(dict(city='city'))
        self.assertNotIn('error', result)
        self.assertEqual(result['values']['HeightIndexPath'], self.env['MAP_ROOT'] + '/city/heights/index.txt')
        self.assertEqual(result['values']['SceneSettingsPath'], scene.as_posix())
        self.assertEqual(result['values']['PathlossDirectory'], '')
        self.assertIn('OUT_ROOT', result['unresolved']['PathlossDirectory'])
        self.assertIn('DT_ROOT', result['unresolved']['DriverTestFileDictionaryPath'])
        self.assertNotIn('/Bin/', result['values']['SceneSettingsPath'])
        # Discovery must not relax the real rendering validation.
        with self.assertRaisesRegex(ValueError, 'BUILD_SUBDIR'):
            core.build_table(self.env, dict(JOB_NAME='job', CITY='city'))

    def test_missing_scene_is_reported_without_inventing_build_paths(self):
        from render_schema import build_table
        self.env.update(PROJECT_PROFILE_ID='partial', BUILD_SUBDIR='', EXE_NAME='', CONFIG_SRC='', OUT_ROOT='')
        table = build_table(self.env, dict(CITY='city'), require_complete=False)
        self.assertEqual(table['SCENE_SETTINGS_FILE'], '')
        self.assertEqual(table['EXE_PATH'], '')


if __name__ == '__main__':
    unittest.main()
