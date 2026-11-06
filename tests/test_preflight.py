"""Read-only, source-aligned run checks on isolated synthetic inputs."""
import csv
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

BACKEND = Path(__file__).resolve().parents[1] / 'platform/backend'
sys.path.insert(0, str(BACKEND))
PROJECTION = 'WGS-84\n50\nUTM\n0 117 500000 0\n'
OUTDOOR_HEADER = ['Cell ID', 'Cell Name', 'Site ID', 'Site Name', 'Longitude', 'Latitude', 'Layer', 'Physical Cell ID', 'Height (m)', 'Azimuth (°)', 'Mechanical Downtilt (°)', 'Additional Electrical Downtilt (°)', 'SenseTilt', 'Antenna', 'SenseAntenna', 'Number of Transmission Antennas', 'Number of Reception Antennas', 'Max Power (dBm)', 'EPRE per antenna port', 'Bandwidth', 'Channel Number', 'Main Propagation Model', 'Main Resolution', 'Traffic Load (DL) (%)', 'Traffic Load (UL) (%)', 'Main Calculation Radius (m)', 'Transmission losses (dB)', 'Reception losses (dB)', 'Noise Figure (dB)', 'Miscellaneous Losses', 'Feeder Equipment', 'Feeder Length(m)', 'TMA Equipment', 'Transmitter Equipment', 'Active', 'Transmitter Type', 'Cell Type', 'Channel Allocation Status', 'Frequency Band', 'SenseActive', 'SensePower', 'CityCode']
OUTDOOR_ROW = ['c1', 'cell', 'site1', 'site', '119.000000', '26.000000', '1', '1', '20', '90', '0', '0', '0', 'omni', 'omni', '4', '4', '40', '14', '100', '504990', 'LiShuttleModel_1', '5', '15', '15', '800', '2', '2', '4', '0', '', '0', '', '0', '1', '1', 'NR', '0', '20', '1', '14', '350900']
INDOOR_HEADER = ['AP ID', 'AP Name', 'Cell ID', 'Floor', 'x', 'y', 'Height (m)', 'Azimuth (°)', 'Mechanical Downtilt (°)', 'Additional Electrical Downtilt (°)', 'Antenna', 'Number of Transmission Antennas', 'Number of Reception Antennas', 'Max Power (dBm)', 'EPRE per antenna port', 'Frequency Band', 'Channel Number', 'Main Propagation Model', 'Main Resolution', 'Traffic Load (DL) (%)', 'Traffic Load (UL) (%)', 'Main Calculation Radius (m)', 'Transmission losses (dB)', 'Reception losses (dB)', 'Noise Figure (dB)', 'Miscellaneous Losses', 'Feeder Equipment', 'Feeder Length(m)', 'Transmitter Equipment', 'Active', 'Transmitter Type', 'Cell Type']
INDOOR_ROW = ['AP1', 'AP', 'c1', '1', '2', '2', '2', '90', '0', '0', 'omni', '4', '4', '20', '14', '30', '1300', 'LiShuttleIndoorModel_1', '0.2', '15', '15', '800', '2', '2', '4', '0', '', '0', '', '1', '1', 'LTE-FDD']
CELL_FORMAT = dict(CellId='A', SiteId='C', Longitude='E', Latitude='F', PCI='H', AntennaHeight='I', Azimuth='J', Tilt='K', ElecTilt='L', SenseTilt='M', Antenna='N', SenseAntenna='O', TxNumber='P', RxNumber='Q', MaxPower='R', EPRE='S', BandWidth='T', ChannelNumber='U', PropagationModel='V', Resolution='W', DLTrafficLoad='X', ULTrafficLoad='Y', CalcRadius='Z', TxLoss='AA', RxLoss='AB', NoiseFigure='AC', MiscellaneousLoss='AD', FeederEquipment='AE', FeederLength='AF', TMAEquipment='AG', Active='AI', CellType='AK', SenseActive='AN', SensePower='AO', SenseNoiseFigure='AC')


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('preflight'), 'preflight module must exist')
        self.check = importlib.import_module('preflight').check_run
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'out/build/test/Bin'
        self.bin.mkdir(parents=True)
        self.put('lishuttle.exe', b'fixture')
        self.env = dict(PROJECT_DIR=str(self.root), BUILD_SUBDIR='out/build/test', EXE_NAME='lishuttle.exe')
        self.values = dict(EngineeringFilePath='cells.csv', PathlossDirectory='results',
            ProjectionFilePath='map/heights/projection.txt', HeightIndexPath='map/heights/index.txt',
            ClutterIndexPath='map/clutter/index.txt', PolygonFilePath='area.txt',
            ClutterMenuPath='map/clutter/menu.txt',
            MapFormat='PLANET', SpatialCalcMode='ground', DefaultFloorHeight='3', MaxCalcHeight='10')
        self.put('map/heights/projection.txt', PROJECTION)
        self.put('cellformat.xml', '<TableFormat><HeaderLines>2</HeaderLines>' + ''.join(f'<{k}>{v}</{k}>' for k, v in CELL_FORMAT.items()) + '</TableFormat>')
        self.put('runtimelibrary/scenesettings.xml', '<Cluttersettings><SceneInformation><SceneID>0</SceneID><OtoIModel>0</OtoIModel><PenetrationLoss>20</PenetrationLoss><LinearLoss>0.2</LinearLoss><FloorHeight>3</FloorHeight><FloorLoss>10</FloorLoss></SceneInformation></Cluttersettings>')
        self.put('models/LiShuttleModel.xml', '<PropagationCategory name="LiShuttleModel"><Model ID="1"><ModelName>Sub6G</ModelName><K0>28</K0><Knear>22</Knear><Kfar>40</Kfar><Kh>-9</Kh><K0_nlos>28</K0_nlos><Knear_nlos>22</Knear_nlos><Kfar_nlos>40</Kfar_nlos><Kh_nlos>-9</Kh_nlos></Model></PropagationCategory>')
        self.put('antennas/antenna.xml', '<AntennaSettings><AntennaEntity name="omni"><MaxGain>11</MaxGain><Broadcast_Beam_FILE>omni.txt</Broadcast_Beam_FILE></AntennaEntity></AntennaSettings>')
        self.put('antennas/omni.txt', 'HORIZONTAL 360\n' + ''.join(f'{i} 0\n' for i in range(360)) + 'VERTICAL 360\n' + ''.join(f'{i} 0\n' for i in range(360)))
        for kind in ('heights', 'clutter'):
            self.put(f'map/{kind}/index.txt', 'tile.dat 0 10 0 10 5\n')
            self.put(f'map/{kind}/tile.dat', b'\x01' * 8)
        self.put('area.txt', '119,26\n119.01,26\n119.01,26.01\n')
        self.put('map/clutter/menu.txt', '1 urban\n')
        self.cells()
        self.schema = self.bin / 'runtimelibrary/schema.xml'

    def put(self, path, data):
        path = self.bin / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode('utf-8'))
        return path

    def cells(self, indoor=False, rows=True):
        header = INDOOR_HEADER if indoor else OUTDOOR_HEADER
        row = INDOOR_ROW if indoor else OUTDOOR_ROW
        with self.put('cells.csv', '').open('w', encoding='utf-8', newline='') as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            writer.writerow(header)
            if rows:
                writer.writerow(row)

    def run_check(self, func='pred', **values):
        self.values.update(values)
        root = ET.Element('RuntimeSchema', name='fixture')
        for key, value in self.values.items():
            if value is not None:
                ET.SubElement(root, key).text = str(value)
        self.schema.parent.mkdir(exist_ok=True)
        self.schema.write_bytes(ET.tostring(root, encoding='utf-8'))
        return self.check(self.env, str(self.schema), func, '007')

    def codes(self, report):
        return {issue['code'] for issue in report['issues']}

    def test_ground_context_is_json_serializable_and_read_only(self):
        self.run_check()
        before = {str(p): (p.stat().st_mtime_ns, p.read_bytes()) for p in self.root.rglob('*') if p.is_file()}
        report = self.check(self.env, str(self.schema), 'pred', '007')
        self.assertTrue(report['ok'], report['issues'])
        context = report['context']
        self.assertEqual(context['mode']['layer_count'], 1)
        self.assertEqual(context['mode']['effective'], 'ground')
        self.assertEqual(context['task_id'], '007')
        self.assertEqual(context['schema_name'], 'schema.xml')
        self.assertEqual(context['task_name'], 'fixture')
        self.assertIn('RuntimeSchema', context['schema_text'])
        self.assertEqual(Path(context['pred_dir']), self.bin / 'results/fixture/pred/007')
        self.assertEqual(Path(context['models_dir']), self.bin / 'results/fixture/models_task007')
        self.assertEqual(context['params']['MaxCalcHeight'], '10')
        self.assertEqual(len(context['schema_digest']), 64)
        json.dumps(report, allow_nan=False)
        after = {str(p): (p.stat().st_mtime_ns, p.read_bytes()) for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_3d_layers_include_base_and_stop_at_last_full_step(self):
        report = self.run_check(SpatialCalcMode='3D', MaxCalcHeight='10', DefaultFloorHeight='3')
        self.assertTrue(report['ok'], report['issues'])
        self.assertEqual(report['context']['mode']['layer_count'], 4)
        self.assertEqual(report['context']['mode']['heights'], [0, 3, 6, 9])

    def test_3d_zero_height_is_one_base_layer(self):
        report = self.run_check(SpatialCalcMode='3d', MaxCalcHeight='0')
        self.assertTrue(report['ok'], report['issues'])
        self.assertEqual(report['context']['mode']['layer_count'], 1)

    def test_unrepresentable_layer_ratio_returns_error_instead_of_raising(self):
        report = self.run_check(SpatialCalcMode='3d', MaxCalcHeight='1e308', DefaultFloorHeight='1e-308')
        self.assertFalse(report['ok'])
        self.assertIn('INVALID_LAYER_GEOMETRY', self.codes(report))

    def test_missing_or_invalid_resolution_is_checked_without_mutation(self):
        report = self.run_check(DefaultCalcResolution='0')
        self.assertIn('INVALID_RESOLUTION', self.codes(report))

    def test_ground_does_not_treat_old_floor_cache_as_current_layer_evidence(self):
        self.put('results/fixture/site/c1.loss3d.csv', b'old unknown cache')
        report = self.run_check()
        self.assertTrue(report['ok'], report['issues'])
        self.assertNotIn('CACHE_FORMAT_UNCONFIRMED', self.codes(report))

    def test_unknown_map_format_blocks(self):
        report = self.run_check(MapFormat='mystery')
        self.assertIn('MAP_FORMAT_UNSUPPORTED', self.codes(report))

    def test_3d_invalid_height_or_step_blocks(self):
        for values in ({'MaxCalcHeight': '-1'}, {'DefaultFloorHeight': '0'}, {'MaxCalcHeight': 'nan'}, {'DefaultFloorHeight': 'inf'}):
            with self.subTest(values=values):
                self.values.update(MaxCalcHeight='10', DefaultFloorHeight='3')
                report = self.run_check(SpatialCalcMode='3d', **values)
                self.assertFalse(report['ok'])
                self.assertIn('INVALID_LAYER_GEOMETRY', self.codes(report))
                json.dumps(report, allow_nan=False)

    def test_whitespace_mode_is_invalid_and_missing_mode_defaults_ground(self):
        report = self.run_check(SpatialCalcMode=' ground ')
        self.assertFalse(report['ok'])
        self.assertIn('INVALID_SPATIAL_MODE', self.codes(report))
        report = self.run_check(SpatialCalcMode=None)
        self.assertEqual(report['context']['mode']['parsed'], 'ground')
        self.assertTrue(report['ok'], report['issues'])

    def test_floor_alias_without_usable_buildings_blocks(self):
        report = self.run_check(SpatialCalcMode='BUILDING')
        self.assertEqual(report['context']['mode']['effective'], 'floor')
        self.assertFalse(report['ok'])
        self.assertIn('FLOOR_DATA_REQUIRED', self.codes(report))

    def test_arbitrary_elevated_directory_is_not_floor_cache_evidence(self):
        self.put('results/fixture/prediction/007/3m/RSRP_0.dem', b'old')
        report = self.run_check(SpatialCalcMode='floor')
        self.assertIn('FLOOR_DATA_REQUIRED', self.codes(report))

    def test_missing_executable_and_schema_are_located_errors(self):
        (self.bin / 'lishuttle.exe').unlink()
        report = self.check(self.env, str(self.schema), 'pred', '1')
        self.assertFalse(report['ok'])
        self.assertIn('EXE_MISSING', self.codes(report))
        self.assertIn('SCHEMA_INVALID', self.codes(report))
        for issue in report['issues']:
            self.assertTrue({'severity', 'code', 'message', 'field', 'path'} <= set(issue))

    def test_wrong_or_header_only_engineering_blocks(self):
        self.cells(rows=False)
        report = self.run_check()
        self.assertIn('ENGINEERING_EMPTY', self.codes(report))
        self.cells(indoor=True)
        report = self.run_check()
        self.assertIn('ENGINEERING_KIND', self.codes(report))

    def test_bad_engineering_numeric_row_is_located(self):
        text = (self.bin / 'cells.csv').read_text(encoding='utf-8')
        (self.bin / 'cells.csv').write_text(text.replace('119.000000', 'nan'), encoding='utf-8')
        report = self.run_check()
        self.assertIn('ENGINEERING_ROW', self.codes(report))
        self.assertTrue(any('3' in i['message'] for i in report['issues'] if i['code'] == 'ENGINEERING_ROW'))

    def test_missing_map_index_reference_blocks(self):
        (self.bin / 'map/heights/tile.dat').unlink()
        report = self.run_check()
        self.assertIn('MAP_REFERENCE_MISSING', self.codes(report))

    def test_optional_building_data_does_not_block_ground(self):
        report = self.run_check(BuildingIndexPath='absent/index.txt', BulidVectorIndexPath='absent/vector.txt')
        self.assertTrue(report['ok'], report['issues'])

    def test_map_directory_branch_ignores_explicit_index_paths(self):
        self.put('map/clutter/menu.txt', '1 urban\n')
        report = self.run_check(MapPath='map', HeightIndexPath='absent', ClutterIndexPath='absent', ProjectionFilePath='absent')
        self.assertTrue(report['ok'], report['issues'])

    def test_map_directory_supports_engine_alternative_filenames(self):
        self.put('alternate/height/projection', PROJECTION)
        for kind in ('height', 'clutters'):
            self.put(f'alternate/{kind}/index', 'tile.b 0 10 0 10 5\n')
            self.put(f'alternate/{kind}/tile.b', b'12345678')
        self.put('alternate/clutters/menu', '1 urban\n')
        report = self.run_check(MapPath='alternate')
        self.assertTrue(report['ok'], report['issues'])

    def test_map_directory_and_explicit_indices_both_require_menu(self):
        (self.bin / 'map/clutter/menu.txt').unlink()
        report = self.run_check(MapPath='map')
        self.assertIn('MAP_MENU_MISSING', self.codes(report))
        self.values.pop('MapPath')
        self.assertIn('MAP_MENU_MISSING', self.codes(self.run_check()))

    def test_usable_buildings_leave_actual_floor_total_unknown_and_expose_cap(self):
        import struct
        self.put('map/buildings/index.txt', 'tile.b 0 10 0 10 5\n')
        self.put('map/buildings/tile.b', struct.pack('>4h', 0, 6, 0, 3))
        report = self.run_check(SpatialCalcMode='floor', BuildingIndexPath='map/buildings/index.txt', UsingBuildingPolygon='false')
        self.assertTrue(report['ok'], report['issues'])
        self.assertIsNone(report['context']['mode']['layer_count'])
        self.assertEqual(report['context']['mode']['layer_cap'], 4)
        self.assertEqual(report['context']['mode']['building_sample_height'], 6)

    def test_stale_floor_cache_step_is_reported_without_deletion(self):
        path = self.put('results/fixture/site/c1.loss3d.csv', b'PATHLOSS3D' + __import__('struct').pack('<II6q', 1, 60, 0, 1000, 500, 2, 2, 99))
        before = path.read_bytes()
        report = self.run_check(SpatialCalcMode='floor')
        self.assertIn('CACHE_LAYER_MISMATCH', self.codes(report))
        self.assertEqual(path.read_bytes(), before)

    def test_same_step_cache_still_requires_demonstrable_input_compatibility(self):
        self.put('results/fixture/site/c1.loss3d.csv', b'PATHLOSS3D' + __import__('struct').pack('<II6q', 1, 30, 0, 1000, 500, 2, 2, 99))
        report = self.run_check(SpatialCalcMode='floor')
        self.assertIn('CACHE_COMPATIBILITY_UNCONFIRMED', self.codes(report))
        self.assertIn('FLOOR_DATA_REQUIRED', self.codes(report))

    def test_duplicate_scalar_parameters_block_instead_of_last_wins(self):
        self.run_check()
        raw = self.schema.read_bytes().replace(b'</RuntimeSchema>', b'<SpatialCalcMode>3d</SpatialCalcMode></RuntimeSchema>')
        self.schema.write_bytes(raw)
        report = self.check(self.env, str(self.schema), 'pred', '007')
        self.assertIn('SCHEMA_DUPLICATE_FIELD', self.codes(report))

    def test_empty_polygon_falls_back_to_map_extent(self):
        report = self.run_check(PolygonFilePath='')
        self.assertTrue(report['ok'], report['issues'])
        self.assertIn('REGION_MAP_FALLBACK', self.codes(report))

    def indoor(self):
        self.cells(indoor=True)
        self.put('indoor/floor1.das', 'FloorID: 1\nAltitude: 3\n1 0 0 0\n0 0 0 4 0 0 4 0 3 0 0 3 0.2 1\n')

    def test_indoor_uses_actual_das_floors_and_ignores_spatial_mode(self):
        self.indoor()
        report = self.run_check('predindoor', MapFormat='indoor', MapPath='indoor', SpatialCalcMode=' invalid ', DefaultFloorHeight='0', MaxCalcHeight='nan')
        self.assertTrue(report['ok'], report['issues'])
        self.assertEqual(report['context']['indoor_floors'], [1])
        self.assertEqual(report['context']['mode']['effective'], 'indoor')
        self.assertFalse(report['context']['mode']['applies'])
        self.assertEqual(report['context']['mode']['layer_count'], 1)

    def test_ap_floor_missing_from_das_blocks(self):
        self.indoor()
        self.put('indoor/floor1.das', 'FloorID: 2\nAltitude: 3\n1 0 0 0\n0 0 0 4 0 0 4 0 3 0 0 3 0.2 1\n')
        report = self.run_check('predindoor', MapFormat='indoor', MapPath='indoor')
        self.assertIn('AP_FLOOR_MISSING', self.codes(report))

    def test_truncated_das_blocks(self):
        self.indoor()
        self.put('indoor/floor1.das', 'FloorID: 1\nAltitude: 3\n2 0 0 0\n')
        report = self.run_check('predindoor', MapFormat='indoor', MapPath='indoor')
        self.assertIn('INDOOR_MAP_INVALID', self.codes(report))

    def calibration(self):
        self.values.update({tag: value for tag, value in (
            ('MaxPower', '0'), ('MinPower', '-140'), ('MinK0', '1'), ('MaxK0', '60'),
            ('MinKnear', '0'), ('MaxKnear', '20'), ('MinDiff', '0'), ('MaxDiff', '20'),
            ('MinRef', '0'), ('MaxRef', '20'), ('CalNewModelName', 'fixture'),
            ('DriverTestFileDictionaryPath', 'dt'))})
        self.put('dt/index.txt', 'measured.csv\n')
        self.put('dt/measured.csv', 'PCTime,cellID,Lon,Lat,RSRP\n20250101,c1,119,26,-90\n')

    def test_cali_uses_ground_rays_without_3d_or_polygon_requirements(self):
        self.calibration()
        report = self.run_check('cali', SpatialCalcMode='3d', DefaultFloorHeight='0', MaxCalcHeight='nan', PolygonFilePath='missing')
        self.assertTrue(report['ok'], report['issues'])
        self.assertEqual(report['context']['mode']['effective'], 'ground')
        self.assertFalse(report['context']['mode']['applies'])

    def test_cali_pins_source_based_site_transceiver_and_cell_identities(self):
        self.calibration()
        report = self.run_check('cali')
        self.assertTrue(report['ok'], report['issues'])
        records = report['context']['engineering'].get('records')
        self.assertEqual(records, [dict(cell_id='c1', site_name='site1', transceiver_name='c1')])
        with (self.bin / 'cells.csv').open(encoding='utf-8', newline='') as stream:
            rows = list(csv.reader(stream))
        rows[2][0], rows[2][2] = 'later-cell', 'later-site'
        with (self.bin / 'cells.csv').open('w', encoding='utf-8', newline='') as stream:
            csv.writer(stream).writerows(rows)
        self.assertEqual(records, [dict(cell_id='c1', site_name='site1', transceiver_name='c1')],
                         '本次身份映射不能在运行后从当前工参重新推断')

    def test_executable_in_another_bin_cannot_select_an_unchecked_schema(self):
        external = self.put('../other-bin/other.exe', b'fixture')
        for value in (str(external.resolve()), '../other-bin/other.exe'):
            with self.subTest(value=value):
                self.env['EXE_NAME'] = value
                report = self.run_check()
                self.assertFalse(report['ok'], '引擎按实际 exe 目录找 XML，不能启动其他 Bin 的配置')
                self.assertIn('EXE_LOCATION_MISMATCH', self.codes(report))

    def test_prediction_selection_file_is_checked_only_when_requested(self):
        self.assertTrue(self.run_check(PredictedCells='')['ok'])
        self.assertIn('PREDICTED_CELLS_REQUIRED', self.codes(self.run_check(PredictedCells='missing.txt')))
        self.put('selected.txt', 'c1\n')
        self.assertTrue(self.run_check(PredictedCells='selected.txt')['ok'])

    def test_dt_correction_anchor_is_conditional_and_does_not_require_raw_dt_index(self):
        self.assertTrue(self.run_check(CorrectByDT='false', DriverTestFileDictionaryPath='missing')['ok'])
        report = self.run_check(CorrectByDT='true', DriverTestFileDictionaryPath='missing')
        self.assertIn('DT_ANCHOR_REQUIRED', self.codes(report))
        self.put('anchors/meas.anchor', b'opaque existing engine cache')
        report = self.run_check(CorrectByDT='true', DriverTestFileDictionaryPath='anchors')
        self.assertTrue(report['ok'], report['issues'])
        self.assertIn('DT_ANCHOR_FORMAT_UNCONFIRMED', self.codes(report))

    def test_cali_requires_index_references_not_arbitrary_csvs(self):
        self.calibration()
        (self.bin / 'dt/index.txt').unlink()
        report = self.run_check('cali')
        self.assertIn('DT_INDEX_REQUIRED', self.codes(report))

    def test_cali_dt_unknown_cell_or_invalid_measurement_blocks(self):
        self.calibration()
        self.put('dt/measured.csv', 'PCTime,cellID,Lon,Lat,RSRP\n20250101,unknown,119,26,-90\n')
        report = self.run_check('cali')
        self.assertIn('DT_NO_USABLE_ROWS', self.codes(report))

    def test_cali_constraint_pairs_and_disabled_targets_are_checked(self):
        self.calibration()
        report = self.run_check('cali', MinK0='100', IsLosCalibrated='false', IsNLosCalibrated='false')
        self.assertIn('CALIBRATION_RANGE', self.codes(report))
        self.assertIn('CALIBRATION_DISABLED', self.codes(report))

    def test_permanent_models_use_bin_models(self):
        self.calibration()
        report = self.run_check('cali', ModelTemporaryStorage='false')
        self.assertEqual(Path(report['context']['models_dir']), self.bin / 'models')

    def test_cali_invalid_sampling_constraints_block(self):
        self.calibration()
        report = self.run_check('cali', MinSamples='0', Epoch='-1', MinDeltaKfar='20', MaxDeltaKfar='10')
        self.assertIn('CALIBRATION_PARAMETER', self.codes(report))
        self.assertIn('CALIBRATION_RANGE', self.codes(report))

    def test_parameter_help_includes_base_and_floor_alias_without_default_edits(self):
        spec = json.loads((BACKEND / 'params_spec.json').read_text(encoding='utf-8'))
        params = {item['name']: item for item in spec['params']}
        self.assertIn('floor', params['SpatialCalcMode']['desc'])
        self.assertIn('building', params['SpatialCalcMode']['desc'])
        self.assertIn('+1', params['MaxCalcHeight']['desc'])
        self.assertEqual(params['SpatialCalcMode']['default'], '3d')
        from function_profiles import function_profile
        rules, _ = function_profile('cali', {'SpatialCalcMode': '3d'})
        self.assertEqual(rules['SpatialCalcMode']['kind'], 'startup')
        self.assertFalse(rules['MaxCalcHeight']['active'])

    def rewrite_cells(self, header, rows):
        with (self.bin / 'cells.csv').open('w', encoding='utf-8', newline='') as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            writer.writerow(header)
            writer.writerows(rows)

    def test_floor_ignores_inactive_raster_when_vector_selected(self):
        import struct
        self.put('map/buildings/index.txt', 'tile.b 0 10 0 10 5\n')
        self.put('map/buildings/tile.b', struct.pack('>4h', 0, 6, 0, 3))
        report = self.run_check(SpatialCalcMode='floor', BuildingIndexPath='map/buildings/index.txt', UsingBuildingPolygon='true')
        self.assertIn('FLOOR_DATA_REQUIRED', self.codes(report))

    def test_floor_ignores_inactive_vector_when_raster_selected(self):
        self.put('map/vector/index.txt', 'buildings attribute 0 10 0 10 buildings\n')
        self.put('map/vector/buildings', '1 buildings 4\n0 0\n4 0\n4 4\n0 4\n')
        self.put('map/vector/attribute', '1 "building" 6 129\n')
        report = self.run_check(SpatialCalcMode='floor', BulidVectorIndexPath='map/vector/index.txt', UsingBuildingPolygon='false')
        self.assertIn('FLOOR_DATA_REQUIRED', self.codes(report))

    def test_missing_polygon_element_blocks_but_empty_element_remains_valid(self):
        for func in ('pred', 'commsensing'):
            report = self.run_check(func, PolygonFilePath=None)
            self.assertIn('REGION_ELEMENT_REQUIRED', self.codes(report))

    def test_dt_unfamiliar_header_is_warning_and_valid_positional_data_passes(self):
        self.calibration()
        self.put('dt/measured.csv', 'Time,ServingCell,Longitude,Latitude,Signal\n20250101,c1,119,26,-90\n')
        report = self.run_check('cali')
        self.assertTrue(report['ok'], report['issues'])
        self.assertTrue(any(i['code'] == 'DT_HEADER' and i['severity'] == 'warning' for i in report['issues']))

    def test_projection_requires_four_lines_and_finite_numeric_fields(self):
        for text in ('UTM\n', 'WGS-84\n50\nUTM\n0 117 500000\n', 'WGS-84\n50\nUTM\n0 nan 500000 0\n'):
            with self.subTest(text=text):
                self.put('map/heights/projection.txt', text)
                self.assertIn('MAP_PROJECTION_INVALID', self.codes(self.run_check()))

    def test_identical_scalar_duplicates_warn_and_keep_engine_first_value(self):
        self.run_check()
        self.schema.write_bytes(self.schema.read_bytes().replace(b'</RuntimeSchema>', b'<DefaultFloorHeight>3</DefaultFloorHeight></RuntimeSchema>'))
        report = self.check(self.env, str(self.schema), 'pred', '007')
        self.assertTrue(report['ok'], report['issues'])
        self.assertTrue(any(i['code'] == 'SCHEMA_DUPLICATE_FIELD' and i['severity'] == 'warning' for i in report['issues']))

    def test_outdoor_loader_mandatory_columns_cannot_be_empty(self):
        for tag in ('Site ID', 'Antenna', 'EPRE per antenna port', 'SensePower', 'Main Propagation Model', 'Channel Number', 'Mechanical Downtilt (°)', 'Number of Transmission Antennas', 'Number of Reception Antennas', 'Cell Type'):
            with self.subTest(tag=tag):
                row = OUTDOOR_ROW.copy()
                row[OUTDOOR_HEADER.index(tag)] = ''
                self.rewrite_cells(OUTDOOR_HEADER, [row])
                self.assertIn('ENGINEERING_ROW', self.codes(self.run_check()))

    def test_fixed_indoor_loader_mandatory_columns_cannot_be_empty(self):
        self.indoor()
        for tag in ('AP ID', 'Antenna', 'EPRE per antenna port', 'Main Propagation Model', 'Channel Number', 'Mechanical Downtilt (°)', 'Number of Transmission Antennas', 'Number of Reception Antennas', 'Traffic Load (UL) (%)', 'Cell Type'):
            with self.subTest(tag=tag):
                row = INDOOR_ROW.copy()
                row[INDOOR_HEADER.index(tag)] = ''
                self.rewrite_cells(INDOOR_HEADER, [row])
                report = self.run_check('predindoor', MapFormat='indoor', MapPath='indoor')
                self.assertIn('ENGINEERING_ROW', self.codes(report))

    def test_unconfigured_reordered_engineering_layout_is_rejected(self):
        header, row = OUTDOOR_HEADER.copy(), OUTDOOR_ROW.copy()
        for values in (header, row):
            values[13], values[18] = values[18], values[13]
        self.rewrite_cells(header, [row])
        self.assertIn('ENGINEERING_LAYOUT', self.codes(self.run_check()))

    def test_configured_reordered_layout_uses_bin_cellformat(self):
        header, row = OUTDOOR_HEADER.copy(), OUTDOOR_ROW.copy()
        for values in (header, row):
            values[13], values[18] = values[18], values[13]
        self.rewrite_cells(header, [row])
        path = self.bin / 'cellformat.xml'
        path.write_text(path.read_text(encoding='utf-8').replace('<Antenna>N</Antenna>', '<Antenna>S</Antenna>').replace('<EPRE>S</EPRE>', '<EPRE>N</EPRE>'), encoding='utf-8')
        report = self.run_check()
        self.assertTrue(report['ok'], report['issues'])

    def test_scene_settings_required_and_explicit_relative_path_is_used(self):
        (self.bin / 'runtimelibrary/scenesettings.xml').unlink()
        self.assertIn('SCENE_SETTINGS_MISSING', self.codes(self.run_check()))
        self.put('custom-scene.xml', '<Cluttersettings/>')
        self.assertTrue(self.run_check(SceneSettingsPath='custom-scene.xml')['ok'])

    def test_scene_default_uses_only_bin_runtimelibrary(self):
        (self.bin / 'config/scenesettings.xml').unlink(missing_ok=True)
        path = self.put('runtimelibrary/scenesettings.xml', '<Cluttersettings/>')
        report = self.run_check()
        self.assertTrue(report['ok'], report['issues'])
        self.assertEqual(Path(report['context']['resources']['scene_settings']), path)

    def test_old_config_scene_cannot_replace_missing_runtime_default(self):
        (self.bin / 'runtimelibrary/scenesettings.xml').unlink(missing_ok=True)
        self.put('config/scenesettings.xml', '<Cluttersettings/>')
        report = self.run_check()
        self.assertFalse(report['ok'])
        self.assertIn('SCENE_SETTINGS_MISSING', self.codes(report))
        issue = next(i for i in report['issues'] if i['code'] == 'SCENE_SETTINGS_MISSING')
        self.assertEqual(Path(issue['path']), self.bin / 'runtimelibrary/scenesettings.xml')
        self.assertIn('Bin/runtimelibrary/scenesettings.xml', issue['message'])

    def test_output_path_colliding_with_a_file_blocks_without_creating_folders(self):
        self.put('results', 'file blocks output directory')
        self.assertIn('OUTPUT_NOT_DIRECTORY', self.codes(self.run_check()))

    def test_outdoor_missing_model_reference_blocks_and_auto_model_needs_no_base_xml(self):
        (self.bin / 'models/LiShuttleModel.xml').unlink()
        self.assertIn('MODEL_REFERENCE_MISSING', self.codes(self.run_check()))
        row = OUTDOOR_ROW.copy()
        row[21] = 'LiShuttleAuto'
        self.rewrite_cells(OUTDOOR_HEADER, [row])
        self.assertTrue(self.run_check()['ok'])

    def test_missing_antenna_or_gain_reference_blocks(self):
        (self.bin / 'antennas/omni.txt').unlink()
        self.assertIn('ANTENNA_GAIN_INVALID', self.codes(self.run_check()))
        self.put('antennas/antenna.xml', '<AntennaSettings/>')
        self.assertIn('ANTENNA_REFERENCE_MISSING', self.codes(self.run_check()))

    def test_map_raster_shorter_than_declared_grid_blocks(self):
        self.put('map/heights/tile.dat', b'12')
        self.assertIn('MAP_RASTER_TRUNCATED', self.codes(self.run_check()))

    def test_raster_building_branch_requires_input_even_for_ground(self):
        report = self.run_check(UsingBuildingPolygon='false')
        self.assertIn('MAP_INDEX_MISSING', self.codes(report))

    def test_selected_vector_needs_matching_finite_geometry(self):
        self.put('map/vector/index.txt', 'buildings attribute 0 10 0 10 buildings\n')
        self.put('map/vector/buildings', '1 buildings 4\n0 0\n4 0\n4 4\n0 4\n')
        self.put('map/vector/attribute', '1 "building" 5000 129\n')
        report = self.run_check(SpatialCalcMode='floor', BulidVectorIndexPath='map/vector/index.txt')
        self.assertTrue(report['ok'], report['issues'])
        self.assertEqual(report['context']['mode']['building_sample_height'], 5000)
        self.put('map/vector/buildings', '1 buildings 4\n0 0\n')
        self.assertIn('FLOOR_DATA_REQUIRED', self.codes(self.run_check()))

    def test_indoor_without_antenna_gain_does_not_require_gain_library_or_model_file(self):
        self.indoor()
        (self.bin / 'antennas/antenna.xml').unlink()
        (self.bin / 'models/LiShuttleModel.xml').unlink()
        report = self.run_check('predindoor', MapFormat='indoor', MapPath='indoor', AntGainCalced='false')
        self.assertTrue(report['ok'], report['issues'])

    def test_multiple_root_model_fragments_are_accepted(self):
        path = self.bin / 'models/LiShuttleModel.xml'
        path.write_text('<ModelVersion>1</ModelVersion>' + path.read_text(encoding='utf-8'), encoding='utf-8')
        self.assertTrue(self.run_check()['ok'])

    def test_ground_effective_height_preserves_configured_height(self):
        mode = self.run_check()['context']['mode']
        self.assertEqual(mode['max_height'], 0)
        self.assertEqual(mode['configured_max_height'], 10)
        self.calibration()
        mode = self.run_check('cali', SpatialCalcMode='3d', MaxCalcHeight='10')['context']['mode']
        self.assertEqual(mode['max_height'], 0)
        self.assertEqual(mode['configured_max_height'], 10)

    def test_presuffixed_antenna_requires_exact_loaded_beam(self):
        row = OUTDOOR_ROW.copy()
        row[13] = 'omni_6'
        self.rewrite_cells(OUTDOOR_HEADER, [row])
        self.put('antennas/antenna.xml', '<AntennaSettings><AntennaEntity name="omni"><MaxGain>11</MaxGain><Broadcast_Beam_FILE electilt="7">omni.txt</Broadcast_Beam_FILE></AntennaEntity></AntennaSettings>')
        self.assertIn('ANTENNA_REFERENCE_MISSING', self.codes(self.run_check()))

    def test_base_antenna_selects_nonzero_tilt_when_loaded(self):
        self.put('antennas/antenna.xml', '<AntennaSettings><AntennaEntity name="omni"><MaxGain>11</MaxGain><Broadcast_Beam_FILE>omni.txt</Broadcast_Beam_FILE><Broadcast_Beam_FILE electilt="7">omni.txt</Broadcast_Beam_FILE></AntennaEntity></AntennaSettings>')
        report = self.run_check()
        self.assertTrue(report['ok'], report['issues'])
        self.assertEqual(report['context']['resources']['antenna_gains'][0]['tilt'], 7)

    def test_sensing_antenna_is_required_only_for_commsensing(self):
        row = OUTDOOR_ROW.copy()
        row[14] = 'missing-sensing'
        self.rewrite_cells(OUTDOOR_HEADER, [row])
        self.assertTrue(self.run_check()['ok'])
        self.assertIn('ANTENNA_REFERENCE_MISSING', self.codes(self.run_check('commsensing')))

    def test_output_parent_must_exist_for_nonrecursive_engine_mkdir(self):
        report = self.run_check(PathlossDirectory='missing/parent/results')
        self.assertIn('OUTPUT_PARENT_MISSING', self.codes(report))
        self.assertFalse((self.bin / 'missing').exists())

    def test_task_components_reject_windows_reserved_characters(self):
        self.run_check()
        for char in '<>:"|?*':
            with self.subTest(char=char):
                self.assertIn('INVALID_TASK_NAME', self.codes(self.check(self.env, str(self.schema), 'pred', 'bad' + char)))
                root = ET.parse(self.schema).getroot()
                root.set('name', 'bad' + char)
                self.schema.write_bytes(ET.tostring(root, encoding='utf-8'))
                self.assertIn('INVALID_TASK_NAME', self.codes(self.check(self.env, str(self.schema), 'pred', '007')))

    def test_dynamic_runtime_checks_are_explicitly_unconfirmed(self):
        report = self.run_check()
        self.assertTrue(any(i['code'] == 'RUNTIME_RESOURCES_UNCONFIRMED' and i['severity'] == 'warning' for i in report['issues']))

    def test_legacy_35_column_layout_uses_defaults_when_format_file_missing(self):
        (self.bin / 'cellformat.xml').unlink()
        # Original CellLoader.h layout, before the sensing columns were added.
        positions = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 16,
            17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30,
            31, 32, 33, 34, 35, 36]
        self.rewrite_cells([OUTDOOR_HEADER[i] for i in positions], [[OUTDOOR_ROW[i] for i in positions]])
        report = self.run_check()
        self.assertTrue(report['ok'], report['issues'])
        self.assertIn('ENGINEERING_FORMAT_DEFAULT', self.codes(report))

    def test_unrepresentable_raster_geometry_returns_json_safe_error(self):
        for line in ('tile.dat 0 10 0 10 1e308',
                'tile.dat -1e308 1e308 0 10 5', 'tile.dat 0 10 0 10 1e-308'):
            with self.subTest(line=line):
                self.put('map/heights/index.txt', line + '\n')
                try:
                    report = self.run_check()
                except (OverflowError, ValueError) as exc:
                    self.fail(f'check_run must return an error report: {exc}')
                self.assertFalse(report['ok'])
                self.assertIn('MAP_INDEX_INVALID', self.codes(report))
                json.dumps(report, allow_nan=False)

    def test_building_evidence_ignores_samples_after_declared_grid(self):
        import struct
        self.put('map/buildings/index.txt', 'tile.b 0 10 0 10 5\n')
        self.put('map/buildings/tile.b', struct.pack('>5h', 0, 0, 0, 0, 6))
        report = self.run_check(SpatialCalcMode='floor', BuildingIndexPath='map/buildings/index.txt', UsingBuildingPolygon='false')
        self.assertIn('FLOOR_DATA_REQUIRED', self.codes(report))

    def test_building_evidence_accepts_valid_grid_with_odd_trailing_byte(self):
        import struct
        self.put('map/buildings/index.txt', 'tile.b 0 10 0 10 5\n')
        self.put('map/buildings/tile.b', struct.pack('>4h', 0, 6, 0, 3) + b'X')
        report = self.run_check(SpatialCalcMode='floor', BuildingIndexPath='map/buildings/index.txt', UsingBuildingPolygon='false')
        self.assertTrue(report['ok'], report['issues'])
        self.assertEqual(report['context']['mode']['building_sample_height'], 6)

    def test_legacy_indoor_functions_use_indoor_family_and_remain_unconfirmed(self):
        self.indoor()
        for func in ('plindoor', 'indoorrays'):
            with self.subTest(func=func):
                report = self.run_check(func, MapFormat='indoor', MapPath='indoor', SpatialCalcMode='invalid')
                self.assertTrue(report['ok'], report['issues'])
                self.assertIn('FUNCTION_UNREVIEWED', self.codes(report))
                self.assertEqual(report['context']['mode']['effective'], 'indoor')
                self.assertEqual(report['context']['function_contract'], 'unconfirmed')

    def test_unreviewed_functions_check_common_inputs_without_outdoor_contract(self):
        for func in ('debug', 'test', 'custom-function'):
            with self.subTest(func=func):
                report = self.run_check(func, EngineeringFilePath=None, MapFormat='custom',
                    MapPath='missing', PolygonFilePath=None, DefaultCalcResolution='0', SpatialCalcMode='invalid')
                self.assertTrue(report['ok'], report['issues'])
                self.assertIn('FUNCTION_UNREVIEWED', self.codes(report))
                self.assertEqual(report['context']['function_contract'], 'unconfirmed')
                self.assertIsNone(report['context']['mode']['layer_count'])
        report = self.run_check('debug', PathlossDirectory=None)
        self.assertIn('OUTPUT_REQUIRED', self.codes(report))
        (self.bin / 'lishuttle.exe').unlink()
        self.assertIn('EXE_MISSING', self.codes(self.run_check('test')))


if __name__ == '__main__':
    unittest.main()
