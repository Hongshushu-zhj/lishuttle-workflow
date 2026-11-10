import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import render_schema as renderer


class SampleRenderingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sample = self.root / 'ThirdPart/Config/runtimelibrary/runtimeschema.xml'
        self.sample.parent.mkdir(parents=True)
        self.env = dict(PROJECT_DIR=self.root.as_posix(), CONFIG_SRC='ThirdPart/Config',
                        BUILD_SUBDIR='build', EXE_NAME='lishuttle.exe',
                        MAP_ROOT=self.root.as_posix(), OUT_ROOT=self.root.as_posix())
        self.job = dict(JOB_NAME='new-job', SCHEMA_NAME='new-job.xml', FUNC='pred',
                        CITY='city', ENGINEERING_FILE='data & input.csv', POLYGON_FILE='area.txt')
        self.original = ('<?xml version="1.0" encoding="utf-8"?>\r\n'
                         '<RuntimeSchema name="sample">\r\n'
                         '  <!-- 原始注释 ${DO_NOT_EXPAND}，包括 <CpuLoad>9</CpuLoad> -->\r\n'
                         '  <EngineeringFilePath>sample.csv</EngineeringFilePath>\r\n'
                         '  <CpuLoad>100</CpuLoad>\r\n'
                         '  <FutureParameter enabled="true"/>\r\n'
                         '  <SpatialCalcMode>ground</SpatialCalcMode>\r\n'
                         '  <MaxCalcHeight>100</MaxCalcHeight>\r\n'
                         '  <DefaultFloorHeight>10</DefaultFloorHeight>\r\n'
                         '</RuntimeSchema>\r\n')
        self.sample.write_bytes(self.original.encode('utf-8'))
        self.indoor_sample = self.sample.with_name('indoorruntimeschema.xml')
        self.indoor_original = ('<?xml version="1.0" encoding="utf-8"?>\r\n'
            '<RuntimeSchema name="indoor-sample">\r\n'
            '  <!-- 室内底稿 ${KEEP} <MaxDeepth>99</MaxDeepth> -->\r\n'
            '  <EngineeringFilePath>author-ap.csv</EngineeringFilePath>\r\n'
            '  <MapFormat>indoor</MapFormat>\r\n'
            '  <MapPath>author-map</MapPath>\r\n'
            '  <SceneSettingsPath>author-scene.xml</SceneSettingsPath>\r\n'
            '  <PathlossDirectory>author-output</PathlossDirectory>\r\n'
            '  <PolygonFilePath>author-area.txt</PolygonFilePath>\r\n'
            '  <DriverTestFileDictionaryPath>author-dt</DriverTestFileDictionaryPath>\r\n'
            '  <MaxRayNumber>8</MaxRayNumber><MaxDiffraction>2</MaxDiffraction>\r\n'
            '  <MaxReflection>4</MaxReflection><MaxPenetration>2</MaxPenetration>\r\n'
            '  <MaxDeepth>6</MaxDeepth><IsForcedCalc>true</IsForcedCalc>\r\n'
            '  <IndoorRxPowerSF>10</IndoorRxPowerSF><IndoorSinrSF>2</IndoorSinrSF>\r\n'
            '  <DefaultCalcResolution>1</DefaultCalcResolution>\r\n'
            '  <DefaultUEHeight>1</DefaultUEHeight>\r\n'
            '  <FutureIndoorParameter enabled="true"/>\r\n'
            '</RuntimeSchema>\r\n')
        self.indoor_sample.write_bytes(self.indoor_original.encode('utf-8'))

    def render(self):
        with contextlib.redirect_stdout(io.StringIO()):
            renderer.do_render(self.env, self.job, 'test',
                               str(Path(renderer.ROOT) / 'jobs/test.env'),
                               str(Path(renderer.ROOT) / 'env/test.env'))
        return (self.root / 'build/Bin/runtimelibrary/new-job.xml').read_bytes().decode('utf-8')

    def test_copies_all_sample_text_except_task_values(self):
        expected = self.original.replace('name="sample"', 'name="new-job"').replace(
            '>sample.csv<', '>data &amp; input.csv<')
        self.assertEqual(self.render(), expected)

    def test_only_explicit_heights_override_sample_defaults(self):
        self.job.update(MAX_CALC_HEIGHT='6', DEFAULT_FLOOR_HEIGHT='3')
        text = self.render()
        self.assertIn('<MaxCalcHeight>6</MaxCalcHeight>', text)
        self.assertIn('<DefaultFloorHeight>3</DefaultFloorHeight>', text)
        self.assertIn('<SpatialCalcMode>ground</SpatialCalcMode>', text)

    def test_project_switch_uses_new_project_sample(self):
        self.sample.write_bytes(self.original.replace('<CpuLoad>100</CpuLoad>',
                                                      '<CpuLoad>80</CpuLoad>').encode('utf-8'))
        self.assertIn('<CpuLoad>80</CpuLoad>', self.render())

    def test_missing_sample_fails_instead_of_using_reduced_template(self):
        self.sample.unlink()
        with self.assertRaisesRegex(SystemExit, 'runtimeschema.xml'):
            self.render()

    def indoor_job(self, **values):
        self.job.update(FUNC='predindoor', TEMPLATE='runtimeschema-indoor.xml.tpl',
                        MAP_PATH='indoor/map', POLYGON_FILE='')
        self.job.update(values)

    def test_indoor_uses_its_own_full_sample_and_local_paths(self):
        self.indoor_job()
        text = self.render()
        expected = self.indoor_original.replace('name="indoor-sample"', 'name="new-job"')
        for old, new in [('author-ap.csv', 'data &amp; input.csv'), ('author-map', 'indoor/map'),
                         ('author-scene.xml', self.root.as_posix() + '/build/Bin/runtimelibrary/scenesettings.xml'),
                         ('author-output', self.root.as_posix()), ('author-area.txt', ''), ('author-dt', '')]:
            expected = expected.replace(old, new)
        self.assertEqual(text, expected)
        manifest = json.loads((self.root / 'build/Bin/runtimelibrary/new-job.xml.manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['schema_source'], self.indoor_sample.as_posix())

    def test_indoor_function_alone_selects_indoor_sample(self):
        for func in ('predindoor', 'plindoor', 'indoorrays'):
            with self.subTest(func=func):
                self.job.update(FUNC=func, MAP_PATH='indoor/map')
                self.assertIn('<MaxDeepth>6</MaxDeepth>', self.render())

    def test_indoor_map_format_selects_indoor_sample(self):
        self.job.update(MAP_FORMAT='indoor', MAP_PATH='indoor/map')
        self.assertIn('<MaxDeepth>6</MaxDeepth>', self.render())

    def test_indoor_missing_or_invalid_sample_preserves_previous_generation(self):
        self.render()
        output = self.root / 'build/Bin/runtimelibrary/new-job.xml'
        manifest = Path(str(output) + '.manifest.json')
        previous = (output.read_bytes(), manifest.read_bytes())
        self.indoor_job()
        for content in (None, '<broken>', '<Other/>', '<RuntimeSchema><MapFormat>PLANET</MapFormat></RuntimeSchema>'):
            with self.subTest(content=content):
                if content is None:
                    self.indoor_sample.unlink()
                else:
                    self.indoor_sample.write_text(content, encoding='utf-8')
                with self.assertRaisesRegex(SystemExit, 'indoorruntimeschema.xml'):
                    self.render()
                self.assertEqual((output.read_bytes(), manifest.read_bytes()), previous)

    def test_indoor_uses_selected_project_and_config_source(self):
        self.indoor_job()
        other = self.root / 'other-project'
        sample = other / 'custom-config/runtimelibrary/indoorruntimeschema.xml'
        sample.parent.mkdir(parents=True)
        sample.write_text(self.indoor_original.replace('<MaxDeepth>6</MaxDeepth>', '<MaxDeepth>3</MaxDeepth>'), encoding='utf-8')
        env = dict(self.env, PROJECT_DIR=other.as_posix(), CONFIG_SRC='custom-config')
        rendered, source = renderer.render_project_sample(renderer.build_table(env, self.job), self.job)
        self.assertIn('<MaxDeepth>3</MaxDeepth>', rendered)
        self.assertEqual(source, sample.as_posix())

    def test_indoor_duplicate_height_uses_engine_first_value_and_records_adjustment(self):
        self.indoor_job()
        self.indoor_sample.write_bytes(self.indoor_original.replace('</RuntimeSchema>',
            '  <DefaultUEHeight>1.5</DefaultUEHeight>\r\n</RuntimeSchema>').encode('utf-8'))
        text = self.render()
        self.assertEqual([e.text for e in ET.fromstring(text).findall('DefaultUEHeight')], ['1'])
        manifest = json.loads((self.root / 'build/Bin/runtimelibrary/new-job.xml.manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['sample_adjustments'], [dict(tag='DefaultUEHeight',
            original_values=['1', '1.5'], value='1', reason='室内引擎读取首项；新建任务仅保留首项，避免重复参数歧义')])

    def test_indoor_height_normalization_preserves_unrelated_repeated_and_nested_fields(self):
        self.indoor_job()
        extra = ('<!-- <DefaultUEHeight>comment</DefaultUEHeight> -->'
                 '<Future><DefaultUEHeight>nested</DefaultUEHeight></Future>'
                 '<MaxRayNumber>9</MaxRayNumber><DefaultUEHeight>1.5</DefaultUEHeight>')
        self.indoor_sample.write_bytes(self.indoor_original.replace('</RuntimeSchema>', extra + '</RuntimeSchema>').encode('utf-8'))
        text = self.render()
        root = ET.fromstring(text)
        self.assertEqual([n.text for n in root.findall('DefaultUEHeight')], ['1'])
        self.assertEqual([n.text for n in root.findall('MaxRayNumber')], ['8', '9'])
        self.assertEqual(root.findtext('Future/DefaultUEHeight'), 'nested')
        self.assertIn('<!-- <DefaultUEHeight>comment</DefaultUEHeight> -->', text)

    def test_indoor_structured_height_and_existing_xml_are_not_normalized(self):
        self.indoor_job()
        original = self.indoor_original.replace('</RuntimeSchema>',
            '<DefaultUEHeight>1.5</DefaultUEHeight></RuntimeSchema>')
        self.indoor_sample.write_bytes(original.encode('utf-8'))
        self.job['SCHEMA_SOURCE'] = self.indoor_sample.as_posix()
        self.assertEqual([n.text for n in ET.fromstring(self.render()).findall('DefaultUEHeight')], ['1', '1.5'])
        self.assertEqual(self.indoor_sample.read_bytes(), original.encode('utf-8'))
        manifest = self.root / 'build/Bin/runtimelibrary/new-job.xml.manifest.json'
        self.assertEqual(json.loads(manifest.read_text(encoding='utf-8'))['sample_adjustments'], [])
        self.job.pop('SCHEMA_SOURCE')
        structured = original.replace('<DefaultUEHeight>1</DefaultUEHeight>',
                                      '<DefaultUEHeight>1<!-- keep --></DefaultUEHeight>')
        self.indoor_sample.write_bytes(structured.encode('utf-8'))
        self.assertEqual(len(ET.fromstring(self.render()).findall('DefaultUEHeight')), 2)
        self.assertIn('<!-- keep -->', self.render())

    def test_empty_path_element_is_filled_without_touching_comments(self):
        self.sample.write_bytes(self.original.replace(
            '<EngineeringFilePath>sample.csv</EngineeringFilePath>',
            '<EngineeringFilePath/>').encode('utf-8'))
        self.assertIn('<EngineeringFilePath>data &amp; input.csv</EngineeringFilePath>',
                      self.render())

    def test_explicit_custom_template_remains_supported(self):
        template = self.root / 'custom.tpl'
        template.write_text('<RuntimeSchema name="${JOB_NAME}"/>', encoding='utf-8')
        self.job['TEMPLATE'] = str(template)
        self.sample.unlink()
        self.assertEqual(self.render(), '<RuntimeSchema name="new-job"/>')

    def test_no_render_does_not_read_sample_or_overwrite_existing_xml(self):
        self.render()
        output = self.root / 'build/Bin/runtimelibrary/new-job.xml'
        before = output.read_bytes()
        self.sample.unlink()
        with contextlib.redirect_stdout(io.StringIO()):
            renderer.do_render(self.env, self.job, 'test', 'job.env', 'env.env',
                               write_output=False)
        self.assertEqual(output.read_bytes(), before)

    def test_each_generation_has_a_unique_receipt_even_when_xml_is_identical(self):
        self.render()
        path = self.root / 'build/Bin/runtimelibrary/new-job.xml.manifest.json'
        first = json.loads(path.read_text(encoding='utf-8'))
        self.assertIn('generation', first)
        self.render()
        second = json.loads(path.read_text(encoding='utf-8'))
        self.assertNotEqual(first['generation']['attempt_id'], second['generation']['attempt_id'])
        self.assertEqual(first['generation']['schemas'], second['generation']['schemas'])

    def test_sample_regeneration_preserves_xml_and_manifest_versions(self):
        self.render()
        xml = self.root / 'build/Bin/runtimelibrary/new-job.xml'
        manifest = Path(str(xml) + '.manifest.json')
        first = (xml.read_bytes(), manifest.read_bytes())
        self.job['ENGINEERING_FILE'] = 'second.csv'
        self.render()
        second = (xml.read_bytes(), manifest.read_bytes())
        self.job['ENGINEERING_FILE'] = 'third.csv'
        self.render()
        history = xml.parent / '.lishuttle-history'
        self.assertTrue(Path(str(xml) + '.bak').is_file(), 'sample XML overwrite must keep a backup')
        self.assertTrue(Path(str(manifest) + '.bak').is_file(), 'manifest overwrite must keep a backup')
        self.assertEqual(Path(str(xml) + '.bak').read_bytes(), second[0])
        self.assertEqual(Path(str(manifest) + '.bak').read_bytes(), second[1])
        self.assertCountEqual([p.read_bytes() for p in history.glob(xml.name + '.[0-9]*.bak')],
                              [first[0], second[0]])
        self.assertCountEqual([p.read_bytes() for p in history.glob(manifest.name + '.[0-9]*.bak')],
                              [first[1], second[1]])

    def test_manifest_replace_failure_restores_old_xml_and_manifest(self):
        self.render()
        xml = self.root / 'build/Bin/runtimelibrary/new-job.xml'
        manifest = Path(str(xml) + '.manifest.json')
        before = (xml.read_bytes(), manifest.read_bytes())
        self.job['ENGINEERING_FILE'] = 'changed.csv'
        replace = renderer.os.replace
        failed = False

        def fail_manifest(source, destination):
            nonlocal failed
            if Path(destination) == manifest and not failed:
                failed = True
                raise OSError('manifest replace failed')
            return replace(source, destination)

        with patch.object(renderer.os, 'replace', side_effect=fail_manifest):
            with self.assertRaisesRegex(OSError, 'manifest replace'):
                self.render()
        self.assertEqual((xml.read_bytes(), manifest.read_bytes()), before)

    def test_first_generation_failure_removes_every_new_target(self):
        self.job['SCHEMA_NAME'] = 'one.xml,two.xml'
        directory = self.root / 'build/Bin/runtimelibrary'
        replace = renderer.os.replace

        def fail_second(source, destination):
            if Path(destination) == directory / 'two.xml':
                raise OSError('second XML failed')
            return replace(source, destination)

        with patch.object(renderer.os, 'replace', side_effect=fail_second):
            with self.assertRaisesRegex(OSError, 'second XML'):
                with contextlib.redirect_stdout(io.StringIO()):
                    renderer.do_render(self.env, self.job, 'test', 'job.env', 'env.env')
        self.assertFalse((directory / 'one.xml').exists())
        self.assertFalse((directory / 'two.xml').exists())
        self.assertFalse((directory / 'one.xml,two.xml.manifest.json').exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows drive-letter paths')
    def test_manifest_accepts_project_configuration_on_another_drive(self):
        other_drive = 'Z:' if self.root.drive.upper() != 'Z:' else 'Y:'
        job_path = str(self.root / 'jobs/test.env')
        env_path = str(self.root / 'env/test.env')
        with patch.object(renderer, 'ROOT', other_drive + '/workflow'), \
                contextlib.redirect_stdout(io.StringIO()):
            renderer.do_render(self.env, self.job, 'test', job_path, env_path)
        manifest = json.loads((self.root / 'build/Bin/runtimelibrary/new-job.xml.manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['job_file'], Path(job_path).as_posix())
        self.assertEqual(manifest['env_file'], Path(env_path).as_posix())


if __name__ == '__main__':
    unittest.main()
