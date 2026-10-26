import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
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

    def test_indoor_uses_full_sample_and_adds_required_map_fields(self):
        self.job.update(TEMPLATE='runtimeschema-indoor.xml.tpl', MAP_PATH='indoor/map')
        text = self.render()
        self.assertIn('<CpuLoad>100</CpuLoad>', text)
        self.assertIn('<MapFormat>indoor</MapFormat>', text)
        self.assertIn('<MapPath>indoor/map</MapPath>', text)
        self.assertIn('<!-- 原始注释 ${DO_NOT_EXPAND}，包括 <CpuLoad>9</CpuLoad> -->', text)

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
