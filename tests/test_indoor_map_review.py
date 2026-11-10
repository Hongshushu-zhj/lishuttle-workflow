"""Independent map-discovery regressions using temporary scenes only."""
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

BACKEND = Path(__file__).resolve().parents[1] / 'platform/backend'
sys.path.insert(0, str(BACKEND))
import core
from preflight import _indoor, _path
import render_schema as renderer


DAS = 'FloorID: 1\nAltitude: 3\n1 0 0 0\n0 0 0 4 0 0 4 0 3 0 0 3 0.2 1\n'


class IndoorMapReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / 'project'
        self.binary = self.project / 'build/Bin'
        self.scene = self.binary / 'maps/scene'
        self.scene.mkdir(parents=True)
        self.floor = self.scene / 'custom-floor.das'
        self.floor.write_text(DAS, encoding='utf-8')
        sample = self.project / 'config/runtimelibrary/runtimeschema.xml'
        sample.parent.mkdir(parents=True)
        sample.write_text('<RuntimeSchema name="sample"><MapFormat>PLANET</MapFormat>'
                          '<EngineeringFilePath>old.csv</EngineeringFilePath>'
                          '<PathlossDirectory>old</PathlossDirectory></RuntimeSchema>', encoding='utf-8')
        self.csv = self.root / 'cells.csv'
        self.csv.write_text('fixture input', encoding='utf-8')
        self.env = {'PROJECT_DIR': self.project.as_posix(), 'BUILD_SUBDIR': 'build',
                    'EXE_NAME': 'engine.exe', 'CONFIG_SRC': 'config',
                    'OUT_ROOT': (self.root / 'outputs').as_posix(), 'MAP_ROOT': '', 'DT_ROOT': ''}
        self.job = {'JOB_NAME': 'review', 'SCHEMA_NAME': 'review.xml', 'FUNC': 'predindoor',
                    'TEMPLATE': 'runtimeschema-indoor.xml.tpl', 'MAP_PATH': 'maps/scene',
                    'ENGINEERING_FILE': self.csv.as_posix(), 'POLYGON_FILE': ''}

    def render(self, write_output=True):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = renderer.do_render(self.env, self.job, 'review', 'job.env', 'env.env',
                                      write_output=write_output)
        return code, output.getvalue()

    def test_project_sample_relative_map_path_is_checked_from_executable_directory(self):
        code, output = self.render()
        self.assertEqual(code, 0, output)
        generated = self.binary / 'runtimelibrary/review.xml'
        self.assertEqual(ET.parse(generated).getroot().findtext('MapPath'), 'maps/scene')
        self.assertIn(self.floor.as_posix(), output.replace('\\', '/'))

    def test_reused_relative_xml_map_path_remains_relative_and_reruns_without_source(self):
        source = self.root / 'source.xml'
        root = ET.Element('RuntimeSchema', name='original')
        for key, value in {'MapFormat': 'indoor', 'MapPath': 'maps/scene',
                           'EngineeringFilePath': self.csv.as_posix(),
                           'PathlossDirectory': (self.root / 'outputs').as_posix(),
                           'PolygonFilePath': ''}.items():
            ET.SubElement(root, key).text = value
        source.write_bytes(ET.tostring(root, encoding='utf-8'))
        self.job.update(SCHEMA_SOURCE=source.as_posix(), SYNC_ENGINEERING='0')
        code, output = self.render()
        self.assertEqual(code, 0, output)
        generated = self.binary / 'runtimelibrary/review.xml'
        self.assertEqual(ET.parse(generated).getroot().findtext('MapPath'), 'maps/scene')
        source.unlink()
        code, output = self.render(write_output=False)
        self.assertEqual(code, 0, output)

    def test_multiple_floor_files_are_all_validated_with_relative_xml_resolution(self):
        (self.scene / 'another-floor.das').write_text(DAS.replace('FloorID: 1', 'FloorID: 2'), encoding='utf-8')
        issues = []
        floors = _indoor(_path('maps/scene', self.binary), {'floors': [1, 2], 'path': 'cells.csv'},
                         lambda *args: issues.append(args))
        self.assertEqual(floors, [1, 2])
        self.assertEqual(issues, [])

    def test_duplicate_floor_ids_in_custom_named_files_remain_blocking(self):
        duplicate = self.scene / 'second-copy.das'
        duplicate.write_text(DAS, encoding='utf-8')
        issues = []
        _indoor(str(self.scene), {'floors': [1], 'path': 'cells.csv'}, lambda *args: issues.append(args))
        invalid = [issue for issue in issues if issue[1] == 'INDOOR_MAP_INVALID']
        self.assertEqual(len(invalid), 1)
        self.assertIn('重复楼层', invalid[0][2])

    def test_mixed_uppercase_and_short_das_files_remain_indoor_but_block_partial_run(self):
        upper = self.scene / 'upper-floor.DAS'
        short = self.scene / 'a.das'
        upper.write_text(DAS.replace('FloorID: 1', 'FloorID: 2'), encoding='utf-8')
        short.write_text(DAS.replace('FloorID: 1', 'FloorID: 3'), encoding='utf-8')
        height = self.scene / 'heights/index.txt'
        height.parent.mkdir()
        height.write_text('outdoor index', encoding='utf-8')
        with patch.object(core, 'load_env', return_value=dict(self.env, MAP_ROOT=str(self.scene.parent))):
            scenes, _ = core.scan_cities()
        self.assertEqual([scene['kind'] for scene in scenes], ['indoor'])
        self.assertEqual({check[0] for check in scenes[0]['checks']},
                         {self.floor.name, upper.name, short.name})
        issues = []
        floors = _indoor(str(self.scene), {'floors': [1, 2, 3], 'path': 'cells.csv'},
                         lambda *args: issues.append(args))
        self.assertEqual(floors, [1, 2, 3])
        self.assertEqual({(issue[0], issue[1], issue[4]) for issue in issues},
                         {('error', 'INDOOR_MAP_FILENAME_UNSUPPORTED', str(path))
                          for path in (upper, short)})

    def test_incompatible_uppercase_file_is_also_checked_for_invalid_content(self):
        upper = self.scene / 'broken-floor.DAS'
        upper.write_text('FloorID: 2\nAltitude: 6\n1 0 0 0\n', encoding='utf-8')
        issues = []
        floors = _indoor(str(self.scene), {'floors': [1, 2], 'path': 'cells.csv'},
                         lambda *args: issues.append(args))
        self.assertEqual(floors, [1])
        self.assertEqual({(issue[0], issue[1]) for issue in issues if issue[4] == str(upper)},
                         {('error', 'INDOOR_MAP_FILENAME_UNSUPPORTED'),
                          ('error', 'INDOOR_MAP_INVALID')})
        self.assertIn('AP_FLOOR_MISSING', [issue[1] for issue in issues])

    def test_legacy_engine_extra_files_cannot_silently_add_a_floor(self):
        for name in ('floordas', 'floor2.das.bakdas'):
            with self.subTest(name=name):
                extra = self.scene / name
                extra.write_text(DAS.replace('FloorID: 1', 'FloorID: 2'), encoding='utf-8')
                try:
                    issues = []
                    floors = _indoor(str(self.scene), {'floors': [1, 2], 'path': 'cells.csv'},
                                     lambda *args: issues.append(args))
                    self.assertEqual(floors, [1])
                    self.assertEqual([issue[1] for issue in issues],
                                     ['INDOOR_MAP_UNEXPECTED_ENTRY', 'AP_FLOOR_MISSING'])
                    self.assertEqual((issues[0][0], issues[0][4]), ('error', str(extra)))
                finally:
                    extra.unlink()

    def test_floor_named_directories_are_blocking_beside_a_valid_floor(self):
        for name, expected in (
                ('floordas', {'INDOOR_MAP_UNEXPECTED_ENTRY'}),
                ('directory.das', {'INDOOR_MAP_INVALID'}),
                ('directory.DAS', {'INDOOR_MAP_FILENAME_UNSUPPORTED', 'INDOOR_MAP_INVALID'})):
            with self.subTest(name=name):
                extra = self.scene / name
                extra.mkdir()
                try:
                    issues = []
                    floors = _indoor(str(self.scene), {'floors': [1], 'path': 'cells.csv'},
                                     lambda *args: issues.append(args))
                    self.assertEqual(floors, [1])
                    self.assertEqual({issue[1] for issue in issues}, expected)
                    self.assertTrue(all(issue[0] == 'error' and issue[4] == str(extra)
                                        for issue in issues))
                finally:
                    extra.rmdir()

    def test_isolated_preflight_import_finds_shared_parser_without_importing_core_first(self):
        source = ('import sys;sys.path.insert(0,sys.argv[1]);'
                  'import preflight;assert "core" not in sys.modules;issues=[];'
                  'floors=preflight._indoor(sys.argv[2],{"floors":[1],"path":"cells.csv"},'
                  'lambda *args:issues.append(args));assert floors==[1] and not issues')
        report = subprocess.run([sys.executable, '-I', '-c', source, str(BACKEND), str(self.scene)],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(report.returncode, 0, report.stderr)


if __name__ == '__main__':
    unittest.main()
