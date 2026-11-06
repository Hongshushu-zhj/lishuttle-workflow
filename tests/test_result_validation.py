from pathlib import Path
import importlib.util
import json
import os
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))


class ResultValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.pred = self.root / 'output/prediction/7'
        self.dt = self.root / 'dt'
        self.models = self.root / 'output/models_task7'
        self.ctx = dict(func='pred', task_id='7', schema_name='different-config.xml', task_name='demo',
            out_dir=str(self.root / 'output'), pred_dir=str(self.pred),
            dt_dir=str(self.dt), models_dir=str(self.models), bin_dir=str(self.root / 'Bin'),
            params={'ModelTemporaryStorage': 'true', 'IsCorrectSceneModel': 'false'},
            mode=dict(effective='ground', layer_count=1, floor_height=3, max_height=7),
            regions=[dict(id=0, points=[])], indoor_floors=[1], result_capabilities={'clean_grids': True},
            engineering={'records': [dict(site_name='a', transceiver_name='a', cell_id='a')]})

    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('result_validation'), 'result validation module must exist')
        import result_validation
        return result_validation

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode() if isinstance(data, str) else data)

    def raster(self, name, values=(-900, -32768, -800, -750), folder=None):
        self.write((folder or self.pred) / name, struct.pack('<' + 'h' * len(values), *values))

    def outdoor(self, func='pred', layers=(0,), regions=(0,)):
        products = ('RSRP', 'DLRSSINR', 'BESTSERVER') if func == 'pred' else ('ECHORP', 'SCR')
        self.ctx['func'] = func
        entries = ['UTM 50']
        for region in regions:
            for product in products:
                name = product + (str(region) if region else '') + '.dem'
                entries.append(name + ' 0 2 0 2 1')
                for layer in layers:
                    folder = self.pred if not layer else self.pred / f'{layer * 3}m'
                    self.raster(name, (1, -32768, 1, 1) if product == 'BESTSERVER' else (-900, -32768, -800, -750), folder)
        self.write(self.pred / 'index.txt', '\n'.join(entries) + '\n')
        self.write(self.pred / 'cellid.csv', '1,cell-a\n')

    def indoor(self, numeric=False):
        self.ctx['func'] = 'predindoor'
        self.ctx['mode'] = dict(effective='indoor', layer_count=1)
        self.raster('RSRP_1.dem')
        self.raster('DLRSSINR_1.dem')
        self.write(self.pred / 'index.txt', '0 2 0 2 1\n' if numeric else
            'RSRP_1.dem 0 2 0 2 1\nDLRSSINR_1.dem 0 2 0 2 1\n')

    def calibration(self, scene=False):
        self.ctx['func'] = 'cali'
        self.ctx['params']['IsCorrectSceneModel'] = str(scene).lower()
        self.write(self.dt / 'meas.anchor', b'anchor')
        self.write(self.dt / 'clean_grids.csv', 'PCTime,cellID,Lon,Lat,RSRP\n12:00:00,a,113.1,23.1,-90\n')
        self.write(self.dt / 'demo_cell_summary.csv', 'cell,filter_type,cal_ret,update\na,0x0,0x0,yes\n')
        if scene:
            self.write(self.dt / 'demo_scene_summary.csv', 'sceneNo,model_id\n1,m\n')

    def line(self, site='a', success='Y', update='Y', code='0'):
        return f'Calibration site({site}): grid count=12, success={success}, update={update}, code=0x{code}.'

    def result(self, baseline=None, lines=(), exit_code=0, cancelled=False, complete=True):
        # Existing cases isolate cells outcomes. Supply an explicit source skip
        # record for the other attempted kinds unless the case tests those logs.
        lines = list(lines)
        if self.ctx['func'] == 'cali' and complete:
            if not any('general model' in line.lower() or 'common model' in line.lower() for line in lines):
                lines.append('No enough data for general model calibration:')
            if self.ctx['params']['IsCorrectSceneModel'] == 'true' and not any('scene ' in line or "scenes' calibration" in line for line in lines):
                lines.append("No enough data for scenes' calibration!")
        empty_baseline = dict(files={}, engineering_records=[dict(record) for record in self.ctx.get('engineering', {}).get('records', [])])
        return self.api().validate(self.ctx, baseline if baseline is not None else empty_baseline, lines, exit_code, cancelled)

    def model_xml(self, *names, scene=False, version=None):
        """Minimal reviewed engine format, including valid sibling roots."""
        version = (1 if scene else 0) if version is None else version
        models = []
        for identifier, name in enumerate(names, 1):
            parameters = ''.join(f'<{field}>1</{field}>' for field in ('K0', 'Knear', 'Kfar', 'K0_nlos', 'Knear_nlos', 'Kfar_nlos'))
            if scene:
                parameters += '<Frequency>sub6G</Frequency><City>city</City><Features>default</Features>'
                training = '<dataSize>0</dataSize><sumY>0</sumY><squareY>0</squareY><sumX>0,0,0,0</sumX><squareX>0,0,0,0</squareX><sumProduct>0,0,0,0,0,0,0,0,0,0</sumProduct>'
                parameters += f'<TRAING_LOS>{training}</TRAING_LOS><TRAING_NLOS>{training}</TRAING_NLOS>'
            models.append(f'<Model ID="{identifier}"><ModelName>{escape(name)}</ModelName>{parameters}</Model>')
        return f'<?xml version="1.0"?><ModelVersion>{version}</ModelVersion><PropagationCategory name="LiShuttleModel">' + ''.join(models) + '</PropagationCategory>'

    def codes(self, result):
        return {item['code'] for item in result['issues']}

    def test_new_ground_outputs_success_and_json_contract(self):
        baseline = self.api().snapshot(self.ctx)
        self.outdoor()
        result = self.result(baseline)
        self.assertEqual(result['verdict'], 'success')
        json.dumps(result)
        self.assertEqual(result['process']['exit_code'], 0)
        self.assertEqual(result['process'].get('exit'), 0)
        self.assertTrue(all('rel' in item and 'size' in item for item in result['files']))

    def test_snapshot_contains_hash_and_time_and_detects_same_size_rewrite(self):
        self.outdoor()
        baseline = self.api().snapshot(self.ctx)
        item = baseline['files'][str((self.pred / 'RSRP.dem').resolve())]
        self.assertEqual(len(item['sha256']), 64)
        self.assertIn('mtime_ns', item)
        self.raster('RSRP.dem', (-901, -32768, -800, -750))
        os.utime(self.pred / 'RSRP.dem', ns=(item['mtime_ns'], item['mtime_ns']))
        result = self.result(baseline)
        checked = next(x for x in result['artifacts']['checked'] if x['path'].endswith('RSRP.dem'))
        self.assertTrue(checked['changed'])
        self.assertEqual(result['verdict'], 'unconfirmed')

    def test_completion_and_mtime_only_cannot_confirm_old_outputs(self):
        self.outdoor()
        baseline = self.api().snapshot(self.ctx)
        os.utime(self.pred / 'RSRP.dem', None)
        result = self.result(baseline, ['Finished the predication.(7).'])
        self.assertEqual(result['verdict'], 'unconfirmed')
        self.assertIn('NO_CURRENT_ARTIFACT', self.codes(result))

    def test_ground_ignores_stale_elevated_files(self):
        self.write(self.pred / '3m/RSRP.dem', b'bad')
        baseline = self.api().snapshot(self.ctx)
        self.outdoor()
        result = self.result(baseline)
        self.assertEqual(result['verdict'], 'success')
        self.assertFalse(any('/3m/' in x['path'].replace('\\', '/') for x in result['artifacts']['checked']))

    def test_dimension_mismatch_has_region_layer_and_path(self):
        self.outdoor()
        self.raster('RSRP.dem', (-900,))
        result = self.result()
        self.assertEqual(result['verdict'], 'failed')
        item = next(x for x in result['issues'] if x['code'] == 'RASTER_SIZE')
        self.assertEqual((item['region'], item['layer']), (0, 0))
        self.assertTrue(item['path'].endswith('RSRP.dem'))

    def test_invalid_bestserver_id_fails(self):
        self.outdoor()
        self.raster('BESTSERVER.dem', (9, -32768, 1, 1))
        self.assertIn('BESTSERVER_ID', self.codes(self.result()))

    def test_bestserver_zero_is_invalid_even_if_mapping_contains_zero(self):
        self.outdoor()
        self.write(self.pred / 'cellid.csv', '0,cell-zero\n1,cell-a\n')
        self.raster('BESTSERVER.dem', (0, 1, 1, 1))
        self.assertIn('BESTSERVER_ID', self.codes(self.result()))

    def test_all_sentinel_ground_is_not_usable(self):
        self.outdoor()
        self.raster('RSRP.dem', (-32768,) * 4)
        self.assertEqual(self.result()['verdict'], 'failed')

    def test_commsensing_requires_echo_scr_and_mapping_but_no_bsintf(self):
        self.outdoor('commsensing')
        self.assertEqual(self.result()['verdict'], 'success')
        (self.pred / 'cellid.csv').unlink()
        self.assertEqual(self.result()['verdict'], 'failed')

    def test_3d_nonmultiple_height_requires_only_real_layers(self):
        self.ctx['mode'].update(effective='3d', layer_count=3)
        self.outdoor(layers=(0, 1, 2))
        self.assertEqual(self.result()['verdict'], 'success')
        (self.pred / '6m/SCR.dem').parent.joinpath('RSRP.dem').unlink()
        self.assertEqual(self.result()['verdict'], 'failed')

    def test_floor_does_not_invent_rectangular_stack_for_other_region(self):
        self.ctx['mode'].update(effective='floor', layer_count=3)
        self.ctx['regions'].append(dict(id=1, points=[]))
        self.outdoor(layers=(0, 1, 2), regions=(0,))
        # Only region 0 was computed; absent region 1 does not demand fake upper products.
        self.assertNotEqual(self.result()['verdict'], 'failed')

    def test_floor_unknown_expected_layers_unconfirmed(self):
        self.ctx['mode'].update(effective='floor', layer_count=None)
        self.outdoor()
        self.assertEqual(self.result()['verdict'], 'unconfirmed')

    def test_upper_floor_all_sentinel_is_legitimate(self):
        self.ctx['mode'].update(effective='floor', layer_count=2)
        self.outdoor(layers=(0, 1))
        for product in ('RSRP', 'DLRSSINR', 'BESTSERVER'):
            self.raster(product + '.dem', (-32768,) * 4, self.pred / '3m')
        self.assertEqual(self.result()['verdict'], 'success')

    def test_unknown_index_is_unconfirmed(self):
        self.outdoor()
        self.write(self.pred / 'index.txt', 'future-format 9\n')
        self.assertEqual(self.result()['verdict'], 'unconfirmed')

    def test_index_path_traversal_is_rejected_without_reading_external_file(self):
        self.outdoor()
        self.write(self.pred / 'index.txt', 'UTM 50\n../../outside.dem 0 2 0 2 1\n')
        self.assertEqual(self.result()['verdict'], 'failed')
        self.assertIn('UNSAFE_INDEX_PATH', self.codes(self.result()))

    def test_indoor_requires_final_pair_not_ils(self):
        self.indoor()
        self.assertEqual(self.result()['verdict'], 'success')
        (self.pred / 'RSRP_1.dem').unlink()
        self.write(Path(self.ctx['out_dir']) / 'ray.ils', b'cache')
        self.assertEqual(self.result()['verdict'], 'failed')

    def test_numeric_indoor_index_detected_explicitly(self):
        self.indoor(numeric=True)
        result = self.result()
        self.assertEqual(result['artifacts']['index_format'], 'indoor_numeric_legacy')
        self.assertEqual(result['verdict'], 'success')

    def test_missing_indoor_floor_metadata_is_unconfirmed(self):
        self.indoor()
        self.ctx['indoor_floors'] = []
        self.assertEqual(self.result()['verdict'], 'unconfirmed')

    def test_unknown_function_and_missing_context_do_not_false_succeed(self):
        self.ctx['func'] = 'acp'
        self.assertEqual(self.result()['verdict'], 'unconfirmed')
        self.assertEqual(self.api().validate({}, {}, [], 0)['verdict'], 'unconfirmed')

    def test_cancel_and_nonzero_override_valid_artifacts(self):
        self.outdoor()
        self.assertEqual(self.result(exit_code=3)['verdict'], 'failed')
        self.assertEqual(self.result(exit_code=0, cancelled=True)['verdict'], 'cancelled')

    def test_calibration_current_updates_accept_multi_root_models(self):
        baseline = self.api().snapshot(self.ctx)
        self.calibration()
        self.write(self.models / 'cells/model.xml', self.model_xml('a'))
        result = self.result(baseline, [self.line()])
        self.assertEqual(result['verdict'], 'success')
        self.assertEqual(result['business']['updated'], 1)
        self.assertNotIn('CorrectionMeanVariance.xml', [Path(x['path']).name for x in result['issues']])

    def test_calibration_mixed_site_results_are_partial_and_codes_preserved(self):
        self.calibration()
        self.write(self.models / 'cells/model.xml', self.model_xml('a'))
        result = self.result(lines=[self.line(), self.line('b', 'N', 'N', '8')])
        self.assertEqual(result['verdict'], 'partial')
        self.assertEqual((result['business']['succeeded'], result['business']['failed'], result['business']['updated']), (1, 1, 1))
        self.assertEqual(result['business']['sites'][1]['code'], 8)

    def test_calibration_success_without_update_is_no_update(self):
        self.calibration()
        result = self.result(lines=[self.line(update='N')])
        self.assertEqual(result['verdict'], 'no_update')

    def test_calibration_solver_failure_not_success_even_zero_code(self):
        self.calibration()
        result = self.result(lines=[self.line(success='N', update='N')])
        self.assertEqual(result['verdict'], 'failed')

    def test_calibration_claimed_update_requires_changed_model(self):
        self.calibration()
        self.write(self.models / 'old.xml', '<Model/>')
        baseline = self.api().snapshot(self.ctx)
        self.write(self.dt / 'demo_cell_summary.csv', 'cell,update\na,yes\nb,no\n')
        self.assertEqual(self.result(baseline, [self.line()])['verdict'], 'unconfirmed')

    def test_calibration_history_and_completion_cannot_supply_current_counts(self):
        self.calibration()
        baseline = self.api().snapshot(self.ctx)
        result = self.result(baseline, ['Propagation model calibration ends (Engine 7).'])
        self.assertEqual(result['verdict'], 'unconfirmed')
        self.assertEqual(result['business']['updated'], 0)

    def test_calibration_scene_report_conditional_and_invalid_xml_rejected(self):
        self.calibration(scene=True)
        self.write(self.models / 'cells/new.xml', '<Model>broken')
        result = self.result(lines=[self.line()])
        self.assertEqual(result['verdict'], 'failed')
        self.assertIn('MODEL_XML', self.codes(result))
        (self.dt / 'demo_scene_summary.csv').unlink()
        self.assertIn('REQUIRED_FILE', self.codes(self.result(lines=[self.line()])))

    def test_missing_baseline_cannot_make_existing_outputs_current(self):
        self.outdoor()
        self.assertEqual(self.api().validate(self.ctx, {}, [], 0)['verdict'], 'unconfirmed')

    def test_known_floor_cap_without_observed_upper_output_is_unconfirmed(self):
        self.ctx['mode'].update(effective='floor', layer_count=3)
        self.outdoor()
        self.assertEqual(self.result()['verdict'], 'unconfirmed')

    def test_floor_stack_requires_intermediate_layers_only_for_computed_region(self):
        self.ctx['mode'].update(effective='floor', layer_count=3)
        self.outdoor(layers=(0, 2))
        self.assertEqual(self.result()['verdict'], 'failed')

    def test_indoor_companion_metric_grid_mismatch_fails(self):
        self.indoor()
        self.write(self.pred / 'index.txt', 'RSRP_1.dem 0 2 0 2 1\nDLRSSINR_1.dem 10 12 10 12 1\n')
        self.assertIn('INDEX_GRID_MISMATCH', self.codes(self.result()))

    def test_calibration_unrelated_xml_cannot_confirm_cell_model_updates(self):
        self.calibration()
        self.write(self.models / 'unrelated.xml', '<Model><ModelName>x</ModelName></Model>')
        self.assertEqual(self.result(lines=[self.line()])['verdict'], 'unconfirmed')

    def test_calibration_current_scene_rows_require_scene_model_persistence(self):
        self.calibration(scene=True)
        self.write(self.models / 'cells/model.xml', self.model_xml('a'))
        result = self.result(lines=[self.line(), 'The calibration of scene city completed.'])
        self.assertNotEqual(result['verdict'], 'success')

    def test_calibration_scene_header_only_does_not_require_scene_models(self):
        self.calibration(scene=True)
        self.write(self.dt / 'demo_scene_summary.csv', 'sceneNo,model_id\n')
        self.write(self.models / 'cells/model.xml', self.model_xml('a'))
        self.assertEqual(self.result(lines=[self.line()])['verdict'], 'success')

    def test_calibration_zero_grid_success_is_unconfirmed(self):
        self.calibration()
        result = self.result(lines=[self.line(update='N').replace('count=12', 'count=0')])
        self.assertEqual(result['verdict'], 'unconfirmed')

    def test_calibration_mixed_success_and_failure_without_updates_is_partial(self):
        self.calibration()
        result = self.result(lines=[self.line(update='N'), self.line('b', 'N', 'N', '8')])
        self.assertEqual(result['verdict'], 'partial')

    def test_calibration_empty_cell_report_does_not_prove_business_results(self):
        self.calibration()
        self.write(self.dt / 'demo_cell_summary.csv', 'cell,update\n')
        self.assertNotEqual(self.result(lines=[self.line(update='N')])['verdict'], 'no_update')

    def test_calibration_in_place_storage_uses_bin_models_and_ignores_temporary_models(self):
        self.calibration()
        self.write(self.models / 'cells/old.xml', self.model_xml('a'))
        self.ctx['params']['ModelTemporaryStorage'] = 'false'
        self.ctx['models_dir'] = str(self.root / 'Bin/models')
        self.assertEqual(self.result(lines=[self.line()])['verdict'], 'unconfirmed')
        self.write(Path(self.ctx['models_dir']) / 'cells/demo.xml', self.model_xml('a'))
        self.assertEqual(self.result(lines=[self.line()])['verdict'], 'success')

    def test_multichunk_raster_statistics_and_hashes(self):
        self.outdoor()
        values = (-900,) * (1024 * 1024 // 2 + 3)
        self.raster('RSRP.dem', values)
        self.write(self.pred / 'index.txt', 'UTM 50\nRSRP.dem 0 524291 0 1 1\nDLRSSINR.dem 0 524291 0 1 1\nBESTSERVER.dem 0 524291 0 1 1\n')
        self.raster('DLRSSINR.dem', values)
        self.raster('BESTSERVER.dem', (1,) * len(values))
        result = self.result()
        self.assertEqual(result['verdict'], 'success')
        rsrp = next(entry for entry in result['artifacts']['checked'] if entry['path'].endswith('RSRP.dem'))
        self.assertEqual((rsrp['valid'], rsrp['minimum'], rsrp['maximum']), (len(values), -900, -900))

    def cell_model(self, *names):
        self.write(self.models / 'cells/city.xml', self.model_xml(*(names or ('a',))))

    def general_model(self, filename='LiShuttleModel.xml', name='new_general'):
        self.ctx['params']['CalNewModelName'] = name
        self.write(self.models / filename, self.model_xml(name))

    def test_report_baseline_uses_task_name_instead_of_schema_filename(self):
        self.calibration()
        baseline = self.api().snapshot(self.ctx)
        self.assertIn(str((self.dt / 'demo_cell_summary.csv').resolve()), baseline['files'])
        self.assertNotIn(str((self.dt / 'different-config.xml_cell_summary.csv').resolve()), baseline['files'])
        self.assertEqual(self.result(baseline, [self.line(update='N')])['verdict'], 'unconfirmed')

    def test_missing_task_name_is_unknown_not_filename_fallback(self):
        self.calibration()
        self.ctx.pop('task_name')
        result = self.result(lines=[self.line(update='N')])
        self.assertIn('CALIBRATION_CONTEXT_UNKNOWN', self.codes(result))
        self.assertEqual(result['business'].get('counts', {}).get('unit'), 'model_kinds')

    def test_general_save_failure_with_saved_cells_is_partial(self):
        self.calibration()
        self.cell_model()
        self.ctx['params']['CalNewModelName'] = 'new_general'
        result = self.result(lines=[self.line(), 'The calibration of the general model completed!', 'Failed to save the common model!'])
        self.assertEqual(result['verdict'], 'partial')
        self.assertEqual(result['business']['model_kinds']['general']['status'], 'failed')
        self.assertIn('GENERAL_MODEL_SAVE_FAILED', self.codes(result))

    def test_general_completion_requires_named_current_model(self):
        self.calibration()
        self.ctx['params']['CalNewModelName'] = 'new_general'
        self.general_model(name='wrong_general')
        self.ctx['params']['CalNewModelName'] = 'new_general'
        result = self.result(lines=[self.line(update='N'), 'The calibration of the general model completed!'])
        self.assertEqual(result['verdict'], 'unconfirmed')
        self.assertIn('NO_CURRENT_GENERAL_MODEL', self.codes(result))

    def test_general_only_update_is_success_not_no_update(self):
        self.calibration()
        self.general_model()
        result = self.result(lines=[self.line(update='N'), 'The calibration of the general model completed!', 'The saved common model is "LiShuttle_1".'])
        self.assertEqual(result['verdict'], 'success')
        self.assertEqual(result['business']['updated'], 0)
        self.assertEqual(result['business']['model_kinds']['general']['updated'], 1)
        self.assertEqual(result['business']['counts']['unit'], 'model_kinds')

    def test_general_uses_actual_existing_bin_bundle_filename(self):
        self.calibration()
        self.write(self.root / 'Bin/models/custom_bundle.xml', self.model_xml('old'))
        baseline = self.api().snapshot(self.ctx)
        self.general_model('custom_bundle.xml')
        # Report is current; do not let report attribution mask model handling.
        self.write(self.dt / 'demo_cell_summary.csv', 'cell,update\na,no\n')
        self.write(self.dt / 'clean_grids.csv', 'PCTime,cellID,Lon,Lat,RSRP\n12:00:01,a,113.1,23.1,-91\n')
        result = self.result(baseline, [self.line(update='N'), 'The calibration of the general model completed!'])
        self.assertEqual(result['verdict'], 'success')

    def test_general_unchanged_model_cannot_prove_persistence(self):
        self.calibration()
        self.general_model()
        baseline = self.api().snapshot(self.ctx)
        self.write(self.dt / 'demo_cell_summary.csv', 'cell,update\na,no\n')
        self.write(self.dt / 'clean_grids.csv', 'PCTime,cellID,Lon,Lat,RSRP\n12:00:01,a,113.1,23.1,-91\n')
        result = self.result(baseline, [self.line(update='N'), 'The calibration of the general model completed!'])
        self.assertEqual(result['verdict'], 'unconfirmed')

    def test_general_failure_and_successful_site_updates_are_partial(self):
        self.calibration()
        self.cell_model()
        result = self.result(lines=[self.line(), 'The calibration of the general model failed!'])
        self.assertEqual(result['verdict'], 'partial')

    def test_missing_general_outcome_remains_unconfirmed(self):
        self.calibration()
        self.cell_model()
        self.assertEqual(self.result(lines=[self.line()], complete=False)['verdict'], 'unconfirmed')

    def test_unrelated_unchanged_broken_xml_does_not_poison_current_models(self):
        self.calibration()
        self.write(self.models / 'legacy_unrelated.xml', '<broken>')
        baseline = self.api().snapshot(self.ctx)
        self.cell_model()
        self.write(self.dt / 'demo_cell_summary.csv', 'cell,update\na,yes\n')
        self.write(self.dt / 'clean_grids.csv', 'PCTime,cellID,Lon,Lat,RSRP\n12:00:01,a,113.1,23.1,-91\n')
        result = self.result(baseline, [self.line()])
        self.assertEqual(result['verdict'], 'success')
        self.assertNotIn('MODEL_XML', self.codes(result))

    def test_scene_only_update_changes_aggregate_result(self):
        self.calibration(scene=True)
        self.write(self.dt / 'demo_scene_summary.csv', 'sceneNo,model_id\ncity,1\n')
        self.write(self.models / 'scenes/SceneModel.xml', self.model_xml('city', scene=True))
        result = self.result(lines=[self.line(update='N'), 'The calibration of scene city completed.'])
        self.assertEqual(result['verdict'], 'success')
        self.assertEqual(result['business']['updated'], 0)
        self.assertEqual(result['business']['model_kinds']['scenes']['updated'], 1)

    def test_failed_scene_makes_accepted_general_update_partial(self):
        self.calibration(scene=True)
        self.write(self.dt / 'demo_scene_summary.csv', 'sceneNo,model_id\n')
        self.general_model()
        result = self.result(lines=[self.line(update='N'), 'The calibration of the general model completed!', 'The calibration of scene city failed!!'])
        self.assertEqual(result['verdict'], 'partial')

    def test_scene_identity_must_match_successful_current_scene(self):
        self.calibration(scene=True)
        self.write(self.dt / 'demo_scene_summary.csv', 'sceneNo,model_id\ncity,1\n')
        self.write(self.models / 'scenes/SceneModel.xml', self.model_xml('old_city', scene=True))
        result = self.result(lines=[self.line(update='N'), 'The calibration of scene city completed.'])
        self.assertEqual(result['verdict'], 'unconfirmed')

    def test_clean_grids_known_capability_requires_current_usable_output(self):
        self.calibration()
        (self.dt / 'clean_grids.csv').unlink()
        self.assertIn('REQUIRED_FILE', self.codes(self.result(lines=[self.line(update='N')])))
        self.write(self.dt / 'clean_grids.csv', 'PCTime,cellID,Lon,Lat,RSRP\n')
        self.assertIn('CLEAN_GRIDS_EMPTY', self.codes(self.result(lines=[self.line(update='N')])))
        self.write(self.dt / 'clean_grids.csv', 'PCTime,cellID,Lon,Lat,RSRP\n12:00:00,a,nan,23,-90\n')
        self.assertIn('CLEAN_GRIDS_FORMAT', self.codes(self.result(lines=[self.line(update='N')])))

    def test_clean_grids_unknown_legacy_capability_is_explicitly_uncertain(self):
        self.calibration()
        self.ctx.pop('result_capabilities')
        (self.dt / 'clean_grids.csv').unlink()
        result = self.result(lines=[self.line(update='N')])
        self.assertEqual(result['verdict'], 'unconfirmed')
        self.assertIn('CLEAN_GRIDS_CAPABILITY_UNKNOWN', self.codes(result))

    def test_clean_grids_accepts_source_nul_terminated_windows_header(self):
        self.calibration()
        self.write(self.dt / 'clean_grids.csv', 'PCTime,cellID,Lon,Lat,RSRP\0,distance,azimuth,tilt,real_pathloss,ant_gain,error,pred_rsrp\0\n12:00:00,a,113.1,23.1,-90,1,2,3,100,5,0,-90\n')
        self.assertEqual(self.result(lines=[self.line(update='N')])['verdict'], 'no_update')

    def test_floor_known_cap_ignores_stale_above_cap_artifacts(self):
        self.ctx['mode'].update(effective='floor', layer_count=None, layer_cap=2, configured_layer_count=2, max_height=3)
        self.write(self.pred / '9m/RSRP.dem', b'old corrupt')
        baseline = self.api().snapshot(self.ctx)
        self.outdoor(layers=(0, 1))
        result = self.result(baseline)
        self.assertEqual(result['verdict'], 'success')
        self.assertFalse(any('/9m/' in entry['path'].replace('\\', '/') for entry in result['artifacts']['checked']))

    def test_floor_stale_in_cap_layer_does_not_expand_current_stack(self):
        self.ctx['mode'].update(effective='floor', layer_count=None, layer_cap=4, configured_layer_count=4, max_height=9)
        self.write(self.pred / '9m/RSRP.dem', b'old corrupt')
        baseline = self.api().snapshot(self.ctx)
        self.outdoor(layers=(0, 1))
        result = self.result(baseline)
        self.assertEqual(result['verdict'], 'success')
        self.assertFalse(any(item['rel'].startswith('9m/') for item in result['files']))

    def test_3d_all_required_base_metrics_empty_does_not_require_full_cube(self):
        self.ctx['mode'].update(effective='3d', layer_count=3)
        self.outdoor()
        for product in ('RSRP', 'DLRSSINR', 'BESTSERVER'):
            self.raster(product + '.dem', (-32768,) * 4)
        result = self.result()
        self.assertEqual(result['verdict'], 'unconfirmed')
        self.assertIn('EMPTY_REGION', self.codes(result))
        self.assertFalse(any(entry['code'] == 'REQUIRED_FILE' and entry.get('layer', 0) > 0 for entry in result['issues']))

    def test_3d_only_bestserver_empty_does_not_bypass_required_cube(self):
        self.ctx['mode'].update(effective='3d', layer_count=3)
        self.outdoor(layers=(0, 1, 2))
        self.raster('BESTSERVER.dem', (-32768,) * 4)
        result = self.result()
        self.assertEqual(result['verdict'], 'failed')
        self.assertIn('NO_VALID_CELLS', self.codes(result))

    def test_no_selected_cells_log_identifies_no_participation_without_missing_cube(self):
        self.ctx['mode'].update(effective='3d', layer_count=3)
        result = self.result(lines=['No cells have been choosed to this predication'])
        self.assertEqual(result['verdict'], 'unconfirmed')
        self.assertIn('NO_PARTICIPATING_CELLS', self.codes(result))
        self.assertNotIn('REQUIRED_FILE', self.codes(result))

    def test_3d_derived_configured_cap_still_requires_current_upper_layers(self):
        self.ctx['mode'].update(effective='3d', layer_count=None, max_height=7, floor_height=3)
        self.outdoor()
        self.assertEqual(self.result()['verdict'], 'failed')

    def test_named_general_factory_save_error_overrides_saved_common_log(self):
        self.calibration()
        self.general_model()
        result = self.result(lines=[self.line(update='N'), 'The calibration of the general model completed!',
            'The saved common model is "LiShuttle_1".', 'Failed to save propagation model(new_general), and the error code is 2!'])
        self.assertEqual(result['business']['model_kinds']['general']['updated'], 0)
        self.assertEqual(result['business']['model_kinds']['general']['status'], 'failed')
        self.assertNotEqual(result['verdict'], 'success')

    def test_healthy_general_with_invalid_cells_preserves_partial(self):
        self.calibration()
        self.general_model()
        self.write(self.models / 'cells/city.xml', '<broken>')
        result = self.result(lines=[self.line(), 'The calibration of the general model completed!'])
        self.assertEqual(result['verdict'], 'partial')
        self.assertEqual(result['artifacts']['status'], 'invalid')

    def test_clean_grid_unchanged_report_cannot_confirm_current_business(self):
        self.calibration()
        baseline = self.api().snapshot(self.ctx)
        self.write(self.dt / 'demo_cell_summary.csv', 'cell,update\na,no\n')
        result = self.result(baseline, [self.line(update='N')])
        self.assertEqual(result['verdict'], 'unconfirmed')

    def test_model_kind_counts_do_not_add_sites_to_models_and_scenes(self):
        self.calibration()
        self.general_model()
        self.ctx['engineering']['records'].append(dict(site_name='b', transceiver_name='b', cell_id='b'))
        self.write(self.dt / 'demo_cell_summary.csv', 'cell,update\na,yes\nb,yes\n')
        self.cell_model('a', 'b')
        result = self.result(lines=[self.line(), self.line('b'), 'The calibration of the general model completed!'])
        kinds = result['business']['model_kinds']
        self.assertEqual((kinds['cells']['processed'], kinds['cells']['unit']), (2, 'site_groups'))
        self.assertEqual(result['business']['counts']['processed'], 2)
        self.assertEqual(result['business']['counts']['updated'], 2)

    def disjoint_identities(self):
        self.ctx['engineering']['records'] = [dict(site_name='site-S', transceiver_name='transceiver-T', cell_id='cell-C')]
        self.write(self.dt / 'demo_cell_summary.csv', 'cell,model_id,update\ntransceiver-T,original-model,yes\n')

    def test_cells_unrelated_valid_model_cannot_confirm_claimed_updated_site(self):
        self.calibration()
        self.disjoint_identities()
        self.cell_model('unrelated_old_cell')
        result = self.result(lines=[self.line('site-S')])
        self.assertEqual(result['verdict'], 'unconfirmed')
        self.assertEqual(result['business']['model_kinds']['cells']['updated'], 0)

    def test_cells_distinct_site_transceiver_and_cell_domains_link_correctly(self):
        self.calibration()
        self.disjoint_identities()
        self.cell_model('cell-C')
        self.assertEqual(self.result(lines=[self.line('site-S')])['verdict'], 'success')

    def test_cells_missing_mapping_does_not_invent_names_from_report_or_model(self):
        self.calibration()
        self.ctx['engineering']['records'] = []
        self.cell_model('a')
        result = self.result(lines=[self.line()])
        self.assertEqual(result['verdict'], 'unconfirmed')
        self.assertIn('CELL_IDENTITY_MAPPING_UNKNOWN', self.codes(result))

    def test_old_baseline_without_fixed_mapping_cannot_be_backfilled_after_run(self):
        self.calibration()
        self.cell_model('a')
        self.assertEqual(self.result({'files': {}}, [self.line()])['verdict'], 'unconfirmed')

    def test_cells_confirm_only_verified_site_subset_when_second_save_missing(self):
        self.calibration()
        self.ctx['engineering']['records'].append(dict(site_name='site-B', transceiver_name='transceiver-B', cell_id='cell-B'))
        self.write(self.dt / 'demo_cell_summary.csv', 'cell,update\na,yes\ntransceiver-B,yes\n')
        self.cell_model('a')
        result = self.result(lines=[self.line(), self.line('site-B')])
        self.assertEqual(result['verdict'], 'unconfirmed')
        self.assertEqual(result['business']['model_kinds']['cells']['updated'], 1)
        self.assertEqual(result['business']['updated'], 2)

    def test_cells_site_requires_all_mapped_saved_objects_and_updated_summary(self):
        self.calibration()
        self.ctx['engineering']['records'].append(dict(site_name='a', transceiver_name='second-T', cell_id='second-C'))
        self.write(self.dt / 'demo_cell_summary.csv', 'cell,update\na,yes\nsecond-T,yes\n')
        self.cell_model('a')
        result = self.result(lines=[self.line()])
        self.assertEqual(result['verdict'], 'unconfirmed')
        self.assertEqual(result['business']['model_kinds']['cells']['updated'], 0)
        self.cell_model('a', 'second-C')
        self.assertEqual(self.result(lines=[self.line()])['verdict'], 'success')
        self.write(self.dt / 'demo_cell_summary.csv', 'cell,update\na,yes\nsecond-T,no\n')
        self.assertEqual(self.result(lines=[self.line()])['verdict'], 'unconfirmed')

    def test_pinned_identity_context_is_independent_of_later_csv_contents(self):
        self.calibration()
        self.disjoint_identities()
        csv_path = self.root / 'engineering.csv'
        self.ctx['engineering']['path'] = str(csv_path)
        self.write(csv_path, 'SiteId,CellId\nsite-S,cell-C\n')
        baseline = self.api().snapshot(self.ctx)
        self.write(csv_path, 'SiteId,CellId\nother,new-selection\n')
        self.write(self.dt / 'demo_cell_summary.csv', 'cell,model_id,update\ntransceiver-T,original-model,yes\ntransceiver-extra,base,no\n')
        self.write(self.dt / 'clean_grids.csv', 'PCTime,cellID,Lon,Lat,RSRP\n12:00:01,transceiver-T,113.1,23.1,-91\n')
        self.cell_model('cell-C')
        self.assertEqual(self.result(baseline, [self.line('site-S')])['verdict'], 'success')

    def test_changed_identity_context_cannot_replace_prelaunch_mapping(self):
        self.calibration()
        baseline = self.api().snapshot(self.ctx)
        self.ctx['engineering']['records'] = [dict(site_name='new-site', transceiver_name='new-trans', cell_id='new-cell')]
        self.write(self.dt / 'demo_cell_summary.csv', 'cell,update\nnew-trans,yes\n')
        self.write(self.dt / 'clean_grids.csv', 'PCTime,cellID,Lon,Lat,RSRP\n12:00:01,new-trans,113.1,23.1,-91\n')
        self.cell_model('new-cell')
        result = self.result(baseline, [self.line('new-site')])
        self.assertEqual(result['verdict'], 'unconfirmed')
        self.assertIn('CELL_IDENTITY_CONTEXT_CHANGED', self.codes(result))

    def test_arbitrary_named_xml_is_not_a_general_engine_model(self):
        self.calibration()
        self.ctx['params']['CalNewModelName'] = 'new_general'
        self.write(self.models / 'LiShuttleModel.xml', '<Anything><ModelName>new_general</ModelName></Anything>')
        result = self.result(lines=[self.line(update='N'), 'The calibration of the general model completed!'])
        self.assertEqual(result['verdict'], 'unconfirmed')
        self.assertIn('MODEL_FORMAT_UNKNOWN', self.codes(result))
        item = result['business']['model_kinds']['general']['items'][0]
        self.assertEqual(item['status'], 'unconfirmed')
        self.assertIn('无法确认', item['reason'])

    def test_reviewed_model_missing_coefficients_is_invalid(self):
        self.calibration()
        self.general_model()
        path = self.models / 'LiShuttleModel.xml'
        self.write(path, self.model_xml('new_general').replace('<Knear>1</Knear>', ''))
        result = self.result(lines=[self.line(update='N'), 'The calibration of the general model completed!'])
        self.assertIn('MODEL_STRUCTURE', self.codes(result))
        self.assertEqual(result['business']['model_kinds']['general']['status'], 'failed')

    def test_general_append_can_preserve_same_name_with_distinct_ids(self):
        self.calibration()
        self.general_model()
        self.write(self.models / 'LiShuttleModel.xml', self.model_xml('new_general', 'new_general'))
        result = self.result(lines=[self.line(update='N'), 'The calibration of the general model completed!'])
        self.assertEqual(result['verdict'], 'success')
        self.assertEqual(result['business']['model_kinds']['general']['updated'], 1)
        self.assertNotIn('MODEL_STRUCTURE', self.codes(result))
        self.assertEqual(result['business']['model_kinds']['general']['items'][0]['status'], 'success')
        model = next(entry for entry in result['artifacts']['checked'] if entry['path'].endswith('LiShuttleModel.xml'))
        self.assertEqual(model['model_ids'], [1, 2])

    def test_general_duplicate_ids_are_invalid_even_with_distinct_names(self):
        self.calibration()
        self.general_model()
        fragment = self.model_xml('old_general', 'new_general').replace('ID="2"', 'ID="1"')
        self.write(self.models / 'LiShuttleModel.xml', fragment)
        result = self.result(lines=[self.line(update='N'), 'The calibration of the general model completed!'])
        self.assertIn('MODEL_STRUCTURE', self.codes(result))
        self.assertEqual(result['business']['model_kinds']['general']['status'], 'failed')

    def test_cells_and_scenes_duplicate_names_do_not_bypass_identity_checks(self):
        self.calibration(scene=True)
        self.write(self.models / 'cells/city.xml', self.model_xml('a', 'a'))
        self.write(self.dt / 'demo_scene_summary.csv', 'sceneNo,model_id\ncity,1\n')
        self.write(self.models / 'scenes/SceneModel.xml', self.model_xml('city', 'city', scene=True))
        result = self.result(lines=[self.line(), 'The calibration of scene city completed.'])
        failures = {issue.get('model_kind') for issue in result['issues'] if issue['code'] == 'MODEL_STRUCTURE'}
        self.assertEqual(failures, {'cells', 'scenes'})
        self.assertEqual(result['business']['model_kinds']['cells']['status'], 'failed')
        self.assertEqual(result['business']['model_kinds']['scenes']['status'], 'failed')

    def test_unknown_model_version_is_unconfirmed(self):
        self.calibration()
        self.general_model()
        self.write(self.models / 'LiShuttleModel.xml', self.model_xml('new_general', version=99))
        result = self.result(lines=[self.line(update='N'), 'The calibration of the general model completed!'])
        self.assertEqual(result['verdict'], 'unconfirmed')
        self.assertIn('MODEL_VERSION_UNKNOWN', self.codes(result))
        item = result['business']['model_kinds']['general']['items'][0]
        self.assertEqual(item['status'], 'unconfirmed')
        self.assertIn('无法确认', item['reason'])

    def test_reviewed_model_nonfinite_coefficient_or_invalid_id_is_not_usable(self):
        self.calibration()
        self.general_model()
        for fragment in (self.model_xml('new_general').replace('<K0>1</K0>', '<K0>nan</K0>'),
                         self.model_xml('new_general').replace('ID="1"', 'ID="not-integer"')):
            self.write(self.models / 'LiShuttleModel.xml', fragment)
            result = self.result(lines=[self.line(update='N'), 'The calibration of the general model completed!'])
            self.assertIn('MODEL_STRUCTURE', self.codes(result))
            self.assertNotEqual(result['verdict'], 'success')

    def test_scene_requires_source_metadata_beyond_generic_coefficients(self):
        self.calibration(scene=True)
        self.write(self.dt / 'demo_scene_summary.csv', 'sceneNo,model_id\ncity,1\n')
        self.write(self.models / 'scenes/SceneModel.xml', self.model_xml('city', version=1))
        result = self.result(lines=[self.line(update='N'), 'The calibration of scene city completed.'])
        self.assertIn('MODEL_STRUCTURE', self.codes(result))
        self.assertNotEqual(result['verdict'], 'success')

    def test_empty_cells_model_has_category_and_preserves_healthy_general_partial(self):
        self.calibration()
        self.general_model()
        self.write(self.models / 'cells/city.xml', b'')
        result = self.result(lines=[self.line(), 'The calibration of the general model completed!'])
        self.assertEqual(result['verdict'], 'partial')
        issue = next(item for item in result['issues'] if item['code'] == 'EMPTY_FILE')
        self.assertEqual(issue.get('model_kind'), 'cells')
        self.assertEqual(result['business']['model_kinds']['cells']['status'], 'failed')
        self.assertNotIn('NO_CURRENT_MODEL', self.codes(result))

    def test_unreadable_new_cells_model_has_category_and_preserves_partial(self):
        self.calibration()
        self.general_model()
        self.cell_model('a')
        api = self.api()
        original = api._fingerprint
        blocked = (self.models / 'cells/city.xml').resolve()
        def read(path):
            if path == blocked:
                raise PermissionError('synthetic denied current model')
            return original(path)
        with patch.object(api, '_fingerprint', side_effect=read):
            result = self.result(lines=[self.line(), 'The calibration of the general model completed!'])
        self.assertEqual(result['verdict'], 'partial')
        self.assertTrue(any(item['code'] == 'ARTIFACT_READ' and item.get('model_kind') == 'cells' for item in result['issues']))

    def test_unchanged_summary_cannot_verify_cells_even_with_current_named_model(self):
        self.calibration()
        baseline = self.api().snapshot(self.ctx)
        self.cell_model('a')
        self.write(self.dt / 'clean_grids.csv', 'PCTime,cellID,Lon,Lat,RSRP\n12:00:01,a,113.1,23.1,-91\n')
        result = self.result(baseline, [self.line()])
        self.assertEqual(result['verdict'], 'unconfirmed')
        self.assertEqual(result['business']['model_kinds']['cells']['updated'], 0)

    def test_duplicate_logged_site_name_cannot_prove_unique_group_attribution(self):
        self.calibration()
        self.cell_model('a')
        result = self.result(lines=[self.line(), self.line()])
        self.assertEqual(result['verdict'], 'unconfirmed')
        self.assertIn('CELL_SITE_GROUP_AMBIGUOUS', self.codes(result))

    def test_empty_general_model_is_attributed_and_preserves_saved_cells(self):
        self.calibration()
        self.cell_model('a')
        self.ctx['params']['CalNewModelName'] = 'new_general'
        self.write(self.models / 'LiShuttleModel.xml', b'')
        result = self.result(lines=[self.line(), 'The calibration of the general model completed!'])
        self.assertEqual(result['verdict'], 'partial')
        self.assertTrue(any(item['code'] == 'EMPTY_FILE' and item.get('model_kind') == 'general' for item in result['issues']))


if __name__ == '__main__':
    unittest.main()
