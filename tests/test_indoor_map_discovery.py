"""Indoor scenes must flow from discovery to XML with their real floor files."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core
from preflight import _indoor
from project_detection import detect_project_config
import render_schema as renderer
from server import Api


DAS = 'FloorID: 1\nAltitude: 3\n1 0 0 0\n0 0 0 4 0 0 4 0 3 0 0 3 0.2 1\n'


class IndoorMapDiscoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / 'project'
        sample = self.project / 'config/runtimelibrary/runtimeschema.xml'
        sample.parent.mkdir(parents=True)
        sample.write_text('<RuntimeSchema name="sample"><MapFormat>PLANET</MapFormat>'
                          '<EngineeringFilePath>old.csv</EngineeringFilePath>'
                          '<PathlossDirectory>old</PathlossDirectory></RuntimeSchema>', encoding='utf-8')
        sample.with_name('indoorruntimeschema.xml').write_text(
            sample.read_text(encoding='utf-8').replace('PLANET', 'indoor'), encoding='utf-8')
        self.maps = self.root / 'map'
        self.scene = self.maps / 'test-indoor-map'
        self.scene.mkdir(parents=True)
        self.floor = self.scene / 'test-indoor.das'
        self.floor.write_text(DAS, encoding='utf-8')
        self.csv = self.root / 'cells.csv'
        self.csv.write_text('AP ID,x,y,Floor,Antenna,Power\n'
                            'AP ID,x,y,Floor,Antenna,Power\na,1,2,1,omni,20\n', encoding='utf-8')
        self.env = dict(PROJECT_DIR=self.project.as_posix(), BUILD_SUBDIR='build',
                        EXE_NAME='engine.exe', CONFIG_SRC='config', MAP_ROOT=self.maps.as_posix(),
                        OUT_ROOT=(self.root / 'outputs').as_posix(), DT_ROOT='')

    def scan(self):
        with patch.object(core, 'load_env', return_value=self.env):
            return core.scan_cities()[0]

    def test_scan_recognizes_real_filename_and_all_floors(self):
        second = self.scene / 'another-floor.das'
        second.write_text(DAS.replace('FloorID: 1', 'FloorID: 2'), encoding='utf-8')
        self.assertEqual(self.scan(), [dict(name='test-indoor-map', kind='indoor', checks=[
            [p.name, p.as_posix(), True] for p in (second, self.floor)])])

    def test_project_detection_offers_root_with_only_custom_indoor_filenames(self):
        result = detect_project_config(dict(PROJECT_DIR=self.project.as_posix()), machine={})
        self.assertEqual(result['values']['MAP_ROOT'], self.maps.as_posix())

    def test_das_scene_takes_priority_over_outdoor_indices(self):
        self.floor.rename(self.scene / 'building.das')
        self.assertEqual(self.scan()[0]['kind'], 'indoor')
        height = self.scene / 'heights/index.txt'
        height.parent.mkdir()
        height.write_text('index')
        self.assertEqual(self.scan()[0]['kind'], 'indoor')
        self.assertEqual(self.scan()[0]['checks'][0][0], 'building.das')

    def test_outdoor_indices_still_identify_scenes_without_das_files(self):
        self.floor.unlink()
        height = self.scene / 'heights/index.txt'
        height.parent.mkdir()
        height.write_text('index')
        self.assertEqual(self.scan()[0]['kind'], 'outdoor')

    def test_map_checks_do_not_treat_backup_or_nested_das_as_a_scene(self):
        self.floor.rename(self.scene / 'test-indoor.das.bak')
        nested = self.scene / 'backup'
        nested.mkdir()
        (nested / 'floor1.das').write_text(DAS, encoding='utf-8')
        (self.scene / 'directory.das').mkdir()
        self.assertEqual(self.scan(), [])

    def test_all_das_extensions_identify_indoor_scenes_and_assemble(self):
        for name in ('test-indoor.DAS', 'a.das', 'a.DaS', '楼.das'):
            with self.subTest(name=name):
                path = self.scene / name
                self.floor.rename(path)
                try:
                    self.assertEqual(self.scan(), [dict(name=self.scene.name, kind='indoor',
                        checks=[[name, path.as_posix(), True]])])
                    result = detect_project_config(dict(PROJECT_DIR=self.project.as_posix()), machine={})
                    self.assertEqual(result['values']['MAP_ROOT'], self.maps.as_posix())
                    code, receipt, output = self.render()
                    self.assertEqual(code, 0, output)
                    self.assertEqual(receipt['status'], 'ready')
                finally:
                    path.rename(self.floor)

    def test_das_named_directory_cannot_make_preflight_or_assembly_claim_ready(self):
        (self.scene / 'directory.das').mkdir()
        self.assertEqual(self.scan()[0]['checks'], [[self.floor.name, self.floor.as_posix(), True]])
        code, receipt, _ = self.render()
        self.assertEqual(code, 1)
        self.assertEqual(receipt['status'], 'missing_inputs')
        issues = []
        _indoor(str(self.scene), dict(floors=[1], path='cells.csv'), lambda *args: issues.append(args))
        self.assertIn('INDOOR_MAP_INVALID', [issue[1] for issue in issues])

    def test_name_without_das_extension_is_not_an_indoor_map(self):
        self.floor.rename(self.scene / 'floordas')
        self.assertEqual(self.scan(), [])
        issues = []
        floors = _indoor(str(self.scene), dict(floors=[], path='cells.csv'),
                         lambda *args: issues.append(args))
        self.assertEqual(floors, [])
        self.assertIn('INDOOR_MAP_MISSING', [issue[1] for issue in issues])

    def test_engine_filename_compatibility_is_separate_from_indoor_classification(self):
        for name in ('test-indoor.DAS', 'a.das'):
            with self.subTest(name=name):
                path = self.scene / name
                self.floor.rename(path)
                try:
                    self.assertEqual([scene['kind'] for scene in self.scan()], ['indoor'])
                    issues = []
                    floors = _indoor(str(self.scene), dict(floors=[1], path='cells.csv'),
                                     lambda *args: issues.append(args))
                    self.assertEqual(floors, [1])
                    errors = [issue for issue in issues if issue[0] == 'error']
                    self.assertEqual([issue[1] for issue in errors], ['INDOOR_MAP_FILENAME_UNSUPPORTED'])
                finally:
                    path.rename(self.floor)

    def test_unreadable_scene_does_not_hide_other_maps_and_cannot_pass_checks(self):
        readable = self.maps / 'readable-scene'
        readable.mkdir()
        (readable / 'floor1.das').write_text(DAS, encoding='utf-8')
        original = Path.iterdir

        def iterdir(path):
            if path == self.scene:
                raise PermissionError('scene cannot be listed')
            return original(path)

        with patch.object(Path, 'iterdir', iterdir):
            self.assertEqual([scene['name'] for scene in self.scan()], ['readable-scene'])
            result = detect_project_config(dict(PROJECT_DIR=self.project.as_posix()), machine={})
            self.assertEqual(result['values']['MAP_ROOT'], self.maps.as_posix())
            code, receipt, _ = self.render()
            self.assertEqual(code, 1)
            self.assertEqual(receipt['status'], 'missing_inputs')
            issues = []
            _indoor(str(self.scene), dict(floors=[], path='cells.csv'), lambda *args: issues.append(args))
            self.assertIn('INDOOR_MAP_MISSING', [issue[1] for issue in issues])

    def test_reused_xml_local_paths_accepts_custom_indoor_scene(self):
        source = self.root / 'indoor.xml'
        source.write_text('<RuntimeSchema name="old"><MapFormat>indoor</MapFormat>'
                          '<MapPath>old</MapPath><PathlossDirectory>old</PathlossDirectory>'
                          '<EngineeringFilePath>old.csv</EngineeringFilePath></RuntimeSchema>', encoding='utf-8')
        task = dict(name='task', scene='', engineering_file=self.csv.as_posix())
        with patch.object(core, 'load_env', return_value=self.env), \
                patch.object(Api, '_binding_task', return_value=(task, 'key', self.csv.as_posix(), source.as_posix())):
            result = Api.local_paths(dict(city='test-indoor-map'))
        self.assertNotIn('error', result)
        self.assertEqual(result['values']['MapPath'], self.scene.as_posix())

    def render(self, source=None, map_path=None):
        job = dict(JOB_NAME='indoor-job', SCHEMA_NAME='indoor-job.xml', FUNC='predindoor',
                   TEMPLATE='runtimeschema-indoor.xml.tpl', MAP_PATH=self.scene.as_posix(),
                   ENGINEERING_FILE=self.csv.as_posix(), POLYGON_FILE='')
        if source:
            job.update(SCHEMA_SOURCE=source.as_posix(), SYNC_ENGINEERING='1')
        if map_path is not None:
            job['MAP_PATH'] = map_path
        receipt = self.root / 'receipt.json'
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = renderer.do_render(self.env, job, 'test', 'job.env', 'env.env', receipt_path=str(receipt))
        return code, json.loads(receipt.read_text(encoding='utf-8')), output.getvalue()

    def test_render_checks_actual_filenames_and_records_ready_receipt(self):
        for reuse in (False, True):
            with self.subTest(reuse=reuse):
                source = self.root / 'reused.xml'
                source.write_text('<RuntimeSchema name="old"><MapFormat>indoor</MapFormat>'
                                  '<MapPath>old</MapPath><PathlossDirectory>old</PathlossDirectory>'
                                  '<PolygonFilePath/>'
                                  '<EngineeringFilePath>old.csv</EngineeringFilePath></RuntimeSchema>', encoding='utf-8')
                code, receipt, output = self.render(source if reuse else None)
                self.assertEqual(code, 0, output)
                self.assertEqual(receipt['status'], 'ready')
                self.assertIn(self.floor.as_posix(), output)
                xml = self.project / 'build/Bin/runtimelibrary/indoor-job.xml'
                self.assertEqual(ET.parse(xml).getroot().findtext('MapPath'), self.scene.as_posix())

    def test_empty_indoor_scene_still_records_missing_inputs(self):
        self.floor.unlink()
        code, receipt, _ = self.render()
        self.assertEqual(code, 1)
        self.assertEqual(receipt['status'], 'missing_inputs')
        self.assertTrue(receipt['missing_inputs'])

    def test_map_path_must_be_a_directory_even_if_a_das_file_exists(self):
        code, receipt, _ = self.render(map_path=self.floor.as_posix())
        self.assertEqual(code, 1)
        self.assertEqual(receipt['status'], 'missing_inputs')

    def test_preflight_checks_every_custom_floor_and_keeps_invalid_map_blocked(self):
        issues = []
        engineering = dict(floors=[1], path=self.csv.as_posix())
        self.assertEqual(_indoor(str(self.scene), engineering, lambda *args: issues.append(args)), [1])
        self.assertEqual(issues, [])
        (self.scene / 'floor2.das').write_text('FloorID: 2\nAltitude: 6\n2 0 0 0\n', encoding='utf-8')
        _indoor(str(self.scene), engineering, lambda *args: issues.append(args))
        self.assertIn('INDOOR_MAP_INVALID', [issue[1] for issue in issues])


if __name__ == '__main__':
    unittest.main()
