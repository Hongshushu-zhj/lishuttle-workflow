"""Runtime XML, rather than the help dictionary, owns the parameter inventory."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core
from server import Api


class ParameterCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(PROJECT_DIR=str(self.root), BUILD_SUBDIR='build', CONFIG_SRC='config')
        self.schema = self.root/'build/Bin/runtimelibrary/job.xml'
        self.schema.parent.mkdir(parents=True)
        self.patcher = patch.object(core, 'load_env', return_value=self.env)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def xml(self, body):
        self.schema.write_text('<RuntimeSchema name="task">' + body + '</RuntimeSchema>', encoding='utf-8')

    def rows(self, result):
        self.assertNotIn('error', result)
        return {p['name']:p for g in result['groups'] for p in g['rows']}

    def test_default_view_contains_every_actual_field_and_no_fabricated_defaults(self):
        self.xml('<MapFormat>PLANET</MapFormat><DefaultCalcResolution>5</DefaultCalcResolution>'
                 '<VendorExtension>keep</VendorExtension><MinK0>10</MinK0>')
        result = Api.params(dict(schema=['job.xml'], func=['pl']))
        rows = self.rows(result)
        self.assertEqual(set(rows), set(result['values']))
        self.assertNotIn('MaxCalcHeight', rows)
        self.assertEqual(rows['VendorExtension']['classification'], 'unclassified')
        self.assertEqual(rows['MinK0']['group'], '模型校正')
        self.assertEqual(rows['MinK0']['classification'], 'other')
        self.assertEqual(result['counts']['total'], 4)
        self.assertEqual(result['counts']['unclassified'], 1)

    def test_function_filter_keeps_unclassified_fields_and_restores_known_labels(self):
        self.xml('<DefaultCalcResolution>5</DefaultCalcResolution><MinK0>10</MinK0><CustomFlag>x</CustomFlag>')
        pl = self.rows(Api.params(dict(schema=['job.xml'], func=['pl'], all=['0'])))
        cali = self.rows(Api.params(dict(schema=['job.xml'], func=['cali'], all=['0'])))
        self.assertNotIn('MinK0', pl)
        self.assertIn('CustomFlag', pl)
        self.assertIn('MinK0', cali)
        all_rows = self.rows(Api.params(dict(schema=['job.xml'], func=['pl'], all=['1'])))
        self.assertEqual(all_rows['MinK0']['group'], cali['MinK0']['group'])
        self.assertNotEqual(all_rows['MinK0']['classification'], 'unclassified')

    def test_map_format_is_authoritative_and_hybrid_includes_both_scenes(self):
        self.xml('<MapFormat>PLANET</MapFormat><MapPath/><MaxCalcHeight>3</MaxCalcHeight><MaxReflection>2</MaxReflection>')
        rows = self.rows(Api.params(dict(schema=['job.xml'], func=['pl'], all=['0'])))
        self.assertIn('MaxCalcHeight', rows)
        hybrid = self.rows(Api.params(dict(schema=['job.xml'], func=['plhybrid'], all=['0'])))
        self.assertIn('MapPath', hybrid)
        self.assertIn('MaxCalcHeight', hybrid)

    def test_real_xml_parser_ignores_comments_and_reads_attributes_cdata_and_empty_fields(self):
        self.xml('<!-- <Phantom>not a parameter</Phantom> -->'
                 '<Actual unit="m">12</Actual><Empty unit="m"/>'
                 '<Text><![CDATA[a < b & c]]></Text>')
        values = core.read_schema('job.xml')[1]
        self.assertEqual(values, {'Actual':'12', 'Empty':'', 'Text':'a < b & c'})
        rows = self.rows(Api.params(dict(schema=['job.xml'], func=['pl'])))
        self.assertEqual(set(rows), set(values))

    def test_structured_and_duplicate_parameters_are_visible_but_not_editable(self):
        self.xml('<Custom><Item>1</Item></Custom><Repeat>first</Repeat><Repeat>second</Repeat>')
        rows = self.rows(Api.params(dict(schema=['job.xml'], func=['pl'])))
        self.assertTrue(rows['Custom']['read_only'])
        self.assertTrue(rows['Repeat']['read_only'])
        self.assertIn('second', rows['Repeat']['display_value'])
        before = self.schema.read_bytes()
        for tag in ('Custom','Repeat','Item'):
            result = Api.param_write(dict(schema='job.xml', tag=tag, value='changed'))
            self.assertFalse(result['ok'], tag)
        self.assertEqual(before, self.schema.read_bytes())

    def test_edit_attributed_field_preserves_comments_attributes_and_other_bytes(self):
        self.xml('<!-- <Actual unit="old">comment</Actual> --><Actual unit="m">12</Actual><Keep>中文</Keep>')
        before = self.schema.read_bytes()
        result = Api.param_write(dict(schema='job.xml', tag='Actual', value='2 < 3 & 4'))
        self.assertTrue(result['ok'], result)
        expected = before.replace(b'<Actual unit="m">12</Actual>', b'<Actual unit="m">2 &lt; 3 &amp; 4</Actual>')
        self.assertEqual(self.schema.read_bytes(), expected)
        self.assertEqual(Path(str(self.schema)+'.bak').read_bytes(), before)

    def test_empty_attributed_field_is_editable_and_preserves_attribute(self):
        self.xml('<Empty unit="m"/>')
        result = Api.param_write(dict(schema='job.xml', tag='Empty', value='25'))
        self.assertTrue(result['ok'], result)
        self.assertIn('<Empty unit="m">25</Empty>', self.schema.read_text(encoding='utf-8'))

    def test_invalid_xml_reports_parse_error_instead_of_partial_parameter_list(self):
        self.schema.write_text('<RuntimeSchema><A>1</A><B></RuntimeSchema>', encoding='utf-8')
        result = Api.params(dict(schema=['job.xml'], func=['pl']))
        self.assertIn('error', result)
        self.assertIn('XML', result['error'])

    def test_newly_documented_fields_are_grouped_by_verified_function(self):
        self.xml('<CpuLoad>90</CpuLoad><AllowedErrorOfGrid>10</AllowedErrorOfGrid><EleTiltSensitivity>1</EleTiltSensitivity>')
        rows = self.rows(Api.params(dict(schema=['job.xml'], func=['cali'])))
        self.assertEqual(rows['CpuLoad']['classification'], 'recommended')
        self.assertEqual(rows['AllowedErrorOfGrid']['group'], '模型校正')
        self.assertEqual(rows['AllowedErrorOfGrid']['classification'], 'recommended')
        self.assertEqual(rows['EleTiltSensitivity']['group'], '参数优化')
        self.assertEqual(rows['EleTiltSensitivity']['classification'], 'other')

    def test_invalid_text_cannot_corrupt_xml(self):
        self.xml('<Actual>12</Actual>')
        before = self.schema.read_bytes()
        result = Api.param_write(dict(schema='job.xml', tag='Actual', value='bad\x00text'))
        self.assertFalse(result['ok'])
        self.assertEqual(before, self.schema.read_bytes())

    def test_namespaced_fields_and_non_utf8_files_remain_visible_without_unsafe_edits(self):
        self.schema.write_text('<RuntimeSchema xmlns:x="urn:test"><x:Field>1</x:Field></RuntimeSchema>', encoding='utf-8')
        rows = self.rows(Api.params(dict(schema=['job.xml'])))
        self.assertTrue(rows['{urn:test}Field']['read_only'])
        self.schema.write_bytes('<?xml version="1.0" encoding="UTF-16"?><RuntimeSchema><Field>1</Field></RuntimeSchema>'.encode('utf-16'))
        before = self.schema.read_bytes()
        rows = self.rows(Api.params(dict(schema=['job.xml'])))
        self.assertTrue(rows['Field']['read_only'])
        self.assertFalse(Api.param_write(dict(schema='job.xml', tag='Field', value='中文'))['ok'])
        self.assertEqual(before,self.schema.read_bytes())

    def test_internal_comments_do_not_pollute_scene_or_csv_semantic_values(self):
        csv = self.schema.parent.parent/'cells.csv'
        csv.write_text('小区,半径\nCell ID,CalcRadius\na,125\n',encoding='utf-8-sig')
        self.xml('<MapFormat>indoor<!-- note --></MapFormat><MapPath>map</MapPath>'
                 '<EngineeringFilePath>cells.csv<!-- keep --></EngineeringFilePath><DefaultCalcRadius>800</DefaultCalcRadius>')
        result = Api.params(dict(schema=['job.xml'],func=['plindoor']))
        self.assertEqual(result['values']['MapFormat'],'indoor')
        self.assertEqual(result['values']['EngineeringFilePath'],'cells.csv')
        self.assertEqual(result['scene'],'indoor')
        self.assertEqual(result['param_sources']['DefaultCalcRadius']['values'],['125'])
        self.assertTrue(self.rows(result)['MapFormat']['read_only'])


if __name__ == '__main__':
    unittest.main()
