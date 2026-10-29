"""Source-reviewed function scopes must follow real service dependency chains."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
from parameter_catalog import build_catalog, parse_document


class FunctionProfileTests(unittest.TestCase):
    def catalog(self, func, **values):
        spec = json.loads((Path(__file__).resolve().parents[1] / 'platform/backend/params_spec.json').read_text(encoding='utf-8'))
        document = parse_document(('<RuntimeSchema>' + ''.join(f'<{key}>{value}</{key}>' for key, value in values.items()) + '</RuntimeSchema>').encode())
        return build_catalog(document, spec, func)

    def rows(self, catalog):
        return {row['name']: row for group in catalog['groups'] for row in group['rows']}

    def test_coverage_has_rf_fields_but_not_calibration_or_sensing_fields(self):
        rows = self.rows(self.catalog('pred', RxPowerSF='4', SinrSF='1', UEThermalNoiseFactor='4',
            MinK0='1', Epoch='10', SigmaRCS='1', PWaveCount='5', UavType='1'))
        for tag in ('RxPowerSF', 'SinrSF', 'UEThermalNoiseFactor'):
            self.assertTrue(rows[tag]['recommended'], tag)
        for tag in ('MinK0', 'Epoch', 'SigmaRCS', 'PWaveCount', 'UavType'):
            self.assertFalse(rows[tag]['recommended'], tag)

    def test_indoor_prediction_uses_indoor_ray_dependencies(self):
        rows = self.rows(self.catalog('predindoor', MapFormat='indoor', MapPath='map', MaxReflection='4',
            IndoorRxPowerSF='4', IndoorSinrSF='1', UEThermalNoiseFactor='4',
            ProjectionFilePath='outdoor', DefaultAngleRes='1', MaxK0='2', IsOptIndoor='true'))
        for tag in ('MapFormat', 'MapPath', 'MaxReflection', 'IndoorRxPowerSF', 'IndoorSinrSF', 'UEThermalNoiseFactor'):
            self.assertTrue(rows[tag]['recommended'], tag)
        for tag in ('ProjectionFilePath', 'DefaultAngleRes', 'MaxK0', 'IsOptIndoor'):
            self.assertFalse(rows[tag]['recommended'], tag)

    def test_function_scene_controls_scope_and_reports_incompatible_xml(self):
        result = self.catalog('predindoor', MapFormat='PLANET', MapPath='map', MaxReflection='4')
        self.assertTrue(self.rows(result)['MaxReflection']['recommended'])
        self.assertTrue(result['profile']['scene_warning'])

    def test_calibration_keeps_pathloss_dependency_and_real_jitter_names(self):
        rows = self.rows(self.catalog('cali', MinK0='1', MaxMeanJitter='0.5', MaxVarJitter='4',
            DriverTestFileDictionaryPath='dt', DefaultAngleRes='0.2', RSRP_Weight='1', MaxMeanError='2'))
        for tag in ('MinK0', 'MaxMeanJitter', 'MaxVarJitter', 'DriverTestFileDictionaryPath', 'DefaultAngleRes'):
            self.assertTrue(rows[tag]['recommended'], tag)
        self.assertFalse(rows['RSRP_Weight']['recommended'])
        self.assertEqual(rows['DefaultAngleRes']['usage']['kind'], 'dependency')

    def test_acp_ranges_and_required_fields_follow_optimization_switches(self):
        off = self.catalog('acp', IsOptEleTilt='false', MinEleTilt='0', IsOptRsPower='true')
        row = self.rows(off)['MinEleTilt']
        self.assertTrue(row['recommended'])
        self.assertFalse(row['usage']['active'])
        self.assertIn('IsOptEleTilt', row['usage']['condition'])
        self.assertNotIn('MinEleTilt', off['profile']['missing_required'])
        self.assertIn('MinRSPower', off['profile']['missing_required'])
        on = self.catalog('acp', IsOptEleTilt='true', MinEleTilt='0')
        self.assertTrue(self.rows(on)['MinEleTilt']['usage']['active'])
        self.assertIn('MaxEleTilt', on['profile']['missing_required'])

    def test_acp_objectives_are_conditional_but_parsed_flags_are_not_assumed_used(self):
        rows = self.rows(self.catalog('acp', RSRP_Weight='0', RSRPUnCovRate='0.01',
            RSRPandSINR_Weight='1', RSRPandSINRUnCovRate='0.01', SigmaRCS='1', UavType='0'))
        self.assertFalse(rows['RSRPUnCovRate']['usage']['active'])
        self.assertTrue(rows['RSRPandSINRUnCovRate']['usage']['active'])
        self.assertFalse(rows['SigmaRCS']['recommended'])
        self.assertEqual(rows['SigmaRCS']['usage']['kind'], 'startup')
        self.assertFalse(rows['UavType']['recommended'])

    def test_sensing_keeps_real_sensing_controls_not_acp_monitoring(self):
        rows = self.rows(self.catalog('commsensing', SigmaRCS='1', PWaveCount='5', UavType='1', BsInterf='true',
            MultiPathInterf='true', ClutterInf='5', MonitorGridFilePath='monitor', IndoorRSRPThreshold='-110'))
        for tag in ('SigmaRCS', 'PWaveCount', 'UavType', 'BsInterf', 'MultiPathInterf', 'ClutterInf'):
            self.assertTrue(rows[tag]['recommended'], tag)
            self.assertTrue(rows[tag]['usage']['source'])
        self.assertFalse(rows['MonitorGridFilePath']['recommended'])
        self.assertFalse(rows['IndoorRSRPThreshold']['recommended'])

    def test_missing_parameters_are_reported_without_fabricating_xml_rows(self):
        result = self.catalog('cali', CpuLoad='100', VendorFlag='keep')
        self.assertEqual(set(self.rows(result)), {'CpuLoad', 'VendorFlag'})
        self.assertIn('CalNewModelName', result['profile']['missing_required'])
        self.assertNotIn('AllowedErrorOfGrid', result['profile']['missing_required'])
        self.assertIn('AllowedErrorOfGrid', result['profile']['missing_optional'])
        self.assertEqual(self.rows(result)['VendorFlag']['classification'], 'unclassified')

    def test_unreviewed_function_preserves_existing_recommendation_logic(self):
        result = self.catalog('pl', MinK0='1', DefaultCalcResolution='5')
        self.assertFalse(result.get('profile', {}).get('reviewed', False))
        self.assertTrue(self.rows(result)['DefaultCalcResolution']['recommended'])

    def test_source_review_checks_selected_project_instead_of_claiming_all_versions(self):
        from function_profiles import source_review
        with tempfile.TemporaryDirectory() as folder:
            result = source_review('pred', folder)
            self.assertEqual(result['status'], 'missing')
            self.assertTrue(result['files'])
            self.assertIn('Prediction/src/PredParams.cpp', result['files'])

    def test_changed_source_cannot_be_reported_as_verified(self):
        from function_profiles import source_review
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'Prediction/src/PredParams.cpp'
            source.parent.mkdir(parents=True)
            source.write_text('// different engine version', encoding='utf-8')
            result = source_review('pred', folder)
            self.assertEqual(result['status'], 'changed')
            self.assertIn('Prediction/src/PredParams.cpp', result['changed'])

    def test_antenna_smoothing_requires_both_numeric_scales(self):
        one = self.rows(self.catalog('pred', FourierScale='1', AntGainCalced='true'))
        self.assertFalse(one['FourierScale']['usage']['active'])
        both = self.rows(self.catalog('pred', FourierScale='1', VertFourierScale='1', AntGainCalced='true'))
        self.assertTrue(both['FourierScale']['usage']['active'])
        invalid = self.rows(self.catalog('pred', FourierScale='bad', VertFourierScale='1'))
        self.assertFalse(invalid['VertFourierScale']['usage']['active'])

    def test_acp_sensitivity_is_still_used_by_export_with_optimization_disabled(self):
        rows = self.rows(self.catalog('acp', IsOptEleTilt='false', EleTiltSensitivity='0'))
        self.assertTrue(rows['EleTiltSensitivity']['usage']['active'])
        self.assertIn('导出', rows['EleTiltSensitivity']['usage']['note'])

    def test_indoor_prediction_uses_das_floors_not_outdoor_scene_floor_defaults(self):
        rows = self.rows(self.catalog('predindoor', MapFormat='indoor', CityCode='city',
            DefaultFloorHeight='3', DefaultFloorLoss='10'))
        for tag in ('CityCode', 'DefaultFloorHeight', 'DefaultFloorLoss'):
            self.assertFalse(rows[tag]['recommended'], tag)
            self.assertEqual(rows[tag]['usage']['kind'], 'startup')


if __name__ == '__main__':
    unittest.main()
