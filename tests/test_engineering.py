import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core
from server import Api


HEADER = 'Cell ID,Longitude,Latitude,Height (m),Azimuth (°),Antenna,Max Power (dBm)\n'


class EngineeringSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'task'
        self.folder.mkdir()
        self.env = {'GONGCAN_ROOT': str(self.root)}

    def write(self, name, text, encoding='utf-8'):
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding=encoding)
        return path.as_posix()

    def scan(self):
        with patch.object(core, 'load_env', return_value=self.env):
            return core.scan_tasks()[0][0]

    def test_measurements_and_results_are_not_engineering(self):
        self.write('CALI002600.csv', 'PCTime,cellID,Lon,Lat,RSRP\n1,a,1,2,-80\n')
        self.write('summary.csv', 'cell,antenna,height,ant_gain\na,b,2,3\n')
        expected = self.write('LiJobID002600.csv', '小区ID,经度,纬度,天线高度,方位角,天线型号,功率\n' + HEADER,
                              encoding='gb18030')
        task = self.scan()
        self.assertEqual(task['engineering_file'], expected)
        self.assertEqual(task['engineering_candidates'], [expected])
        self.assertEqual(task['kind'], 'outdoor')

    def test_nested_runtime_packages_are_independent_tasks(self):
        for name in ('JobA', 'JobB'):
            self.write(f'{name}/engineering.csv', HEADER)
            self.write(f'{name}/run.xml', f'<RuntimeSchema name="{name}"><EngineeringFilePath>engineering.csv</EngineeringFilePath></RuntimeSchema>')
            self.write(f'{name}/antenna.xml', '<Antennas/>')
        with patch.object(core, 'load_env', return_value=self.env):
            tasks = core.scan_tasks()[0]
        self.assertEqual(len(tasks), 2)
        for task in tasks:
            self.assertEqual(len(task['engineering_candidates']), 1)
            self.assertTrue(task['antenna'].startswith(task['dir'] + '/'))
            self.assertEqual(len(task['schema_candidates']), 1)

    def test_xml_old_absolute_reference_disambiguates_valid_candidates(self):
        self.write('other.csv', HEADER)
        expected = self.write('LiJobID002600.csv', HEADER)
        self.write('schema.xml', '<RuntimeSchema><EngineeringFilePath>D:\\old\\LiJobID002600.csv</EngineeringFilePath></RuntimeSchema>')
        task = self.scan()
        self.assertEqual(task['engineering_file'], expected)
        self.assertIn('XML', task['engineering_reason'])

    def test_ambiguous_candidates_require_choice(self):
        self.write('a.csv', HEADER)
        self.write('b.csv', HEADER)
        task = self.scan()
        self.assertEqual(task['engineering_file'], '')
        with self.assertRaises(ValueError):
            core.validate_engineering(task)

    def test_invalid_explicit_selection_rejected(self):
        self.write('a.csv', HEADER)
        invalid = self.write('CALI.csv', 'cellID,Lon,Lat,RSRP\na,1,2,-80\n')
        task = self.scan()
        with self.assertRaises(ValueError):
            core.validate_engineering(task, invalid)

    def test_selected_csv_is_written_to_job_not_first_csv(self):
        self.write('a.csv', HEADER)
        expected = self.write('b.csv', HEADER)
        task = self.scan()
        task['engineering_file'] = core.validate_engineering(task, expected)
        with patch.object(core, 'load_env', return_value=self.env), patch.object(core, 'JOBS_DIR', str(self.root)):
            job = core.build_job_env('test', 'cali', '1', task, 'city', 'outdoor')
        self.assertIn(f'ENGINEERING_FILE="{expected}"', Path(job).read_text(encoding='utf-8'))
        saved = Path(job).read_text(encoding='utf-8')
        self.assertNotIn('MAX_CALC_HEIGHT=', saved)
        self.assertNotIn('DEFAULT_FLOOR_HEIGHT=', saved)

    def test_missing_candidates_do_not_fall_back_to_first_csv(self):
        self.write('CALI.csv', 'cellID,Lon,Lat,RSRP\na,1,2,-80\n')
        task = self.scan()
        self.assertEqual(task['engineering_candidates'], [])
        with self.assertRaises(ValueError):
            core.validate_engineering(task)

    def test_indoor_header(self):
        expected = self.write('ap.csv', 'AP ID,Floor,x,y,Height,Antenna,Power\n')
        task = self.scan()
        self.assertEqual(task['engineering_file'], expected)
        self.assertEqual(task['kind'], 'indoor')

    def test_duplicate_basenames_are_ambiguous(self):
        self.write('one/engineering.csv', HEADER)
        self.write('two/engineering.csv', HEADER)
        self.write('schema.xml', '<RuntimeSchema><EngineeringFilePath>D:/old/engineering.csv</EngineeringFilePath></RuntimeSchema>')
        self.assertEqual(self.scan()['engineering_file'], '')

    def test_api_revalidates_changed_file_before_any_job_write(self):
        selected = self.write('engineering.csv', HEADER)
        stale = self.scan()
        self.write('engineering.csv', 'cellID,Lon,Lat,RSRP\na,1,2,-80\n')
        with patch.object(core, 'load_env', return_value=self.env), patch.object(core, 'build_job_env') as build:
            result = Api.render({'job_name': 'test', 'task': stale, 'engineering_file': selected})
        self.assertIn('error', result)
        build.assert_not_called()

    def test_api_uses_validated_selection_instead_of_client_csv_list(self):
        self.write('a.csv', HEADER)
        selected = self.write('b.csv', HEADER)
        stale = self.scan()
        stale['csvs'] = ['fake.csv']
        with patch.object(core, 'load_env', return_value=self.env), \
                patch.object(core, 'build_job_env', return_value='job.env') as build, \
                patch.object(core, 'run_render', return_value=(0, '')), \
                patch.object(core, 'ensure_runtime_resources', return_value={}), \
                patch.object(core, 'schema_path', return_value=str(self.root / 'test.xml')):
            result = Api.render({'job_name': 'test', 'task': stale, 'engineering_file': selected})
        self.assertNotIn('error', result)
        self.assertEqual(build.call_args.args[3]['engineering_file'], selected)
        self.assertNotIn('fake.csv', build.call_args.args[3]['csvs'])


if __name__ == '__main__':
    unittest.main()
