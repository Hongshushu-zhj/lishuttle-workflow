"""Independent regression checks for editor dependency revisions."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core
from server import Api


class EditorIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.csv = self.root / 'cells.csv'
        self.csv.write_bytes(b'Cell ID,CalcRadius\r\na,100\r\nb,200\r\n')
        self.schema = self.root / 'build/Bin/runtimelibrary/job.xml'
        self.schema.parent.mkdir(parents=True)
        self.schema.write_text('<RuntimeSchema><EngineeringFilePath>' + self.csv.as_posix() +
            '</EngineeringFilePath><DefaultCalcRadius>800</DefaultCalcRadius><Actual>12</Actual></RuntimeSchema>',
            encoding='utf-8')
        self.format = self.schema.parent.parent / 'cellformat.xml'
        self.format.write_text('<TableFormat><HeaderLines>1</HeaderLines>'
            '<CellId>A</CellId><CalcRadius>B</CalcRadius></TableFormat>', encoding='utf-8')
        env = dict(PROJECT_DIR=self.root.as_posix(), BUILD_SUBDIR='build', CONFIG_SRC='config')
        patcher = patch.object(core, 'load_env', return_value=env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_radius_source_switch_during_csv_preparation_does_not_write_old_csv(self):
        source = core.radius_source('job.xml')
        before = self.csv.read_bytes()
        read_grid = core.read_csv_grid
        reads = 0

        def switch_source(*args, **kwargs):
            nonlocal reads
            grid = read_grid(*args, **kwargs)
            reads += 1
            if reads == 2:
                self.schema.write_text(self.schema.read_text(encoding='utf-8').replace('cells.csv', 'other.csv'),
                                       encoding='utf-8')
            return grid

        with patch.object(core, 'read_csv_grid', side_effect=switch_source):
            result = Api.param_write(dict(schema='job.xml', tag='DefaultCalcRadius', value='300',
                revision=source['schema_revision'], source_revision=source['revision'],
                format_revision=source['format_revision']))
        self.assertEqual(result.get('code'), 'FILE_CONFLICT', result)
        self.assertEqual(self.csv.read_bytes(), before)
        self.assertFalse(Path(str(self.csv) + '.bak').exists())

    def test_format_switch_during_csv_preparation_does_not_save_using_old_layout(self):
        grid = Api.csv_get(dict(path=[str(self.csv)], schema=['job.xml']))
        before = self.csv.read_bytes()
        read_grid = core.read_csv_grid

        def switch_layout(*args, **kwargs):
            result = read_grid(*args, **kwargs)
            self.format.write_text('<TableFormat><HeaderLines>0</HeaderLines>'
                '<CellId>A</CellId><CalcRadius>C</CalcRadius></TableFormat>', encoding='utf-8')
            return result

        with patch.object(core, 'read_csv_grid', side_effect=switch_layout):
            result = Api.csv_column(dict(path=str(self.csv), schema='job.xml', column='CalcRadius', value='300',
                revision=grid['revision'], format_revision=grid['format_revision']))
        self.assertEqual(result.get('code'), 'FILE_CONFLICT', result)
        self.assertEqual(self.csv.read_bytes(), before)
        self.assertFalse(Path(str(self.csv) + '.bak').exists())

    def test_param_write_retains_values_in_success_response(self):
        revision = core.read_schema_document('job.xml')[1]['revision']
        result = Api.param_write(dict(schema='job.xml', tag='Actual', value='13', revision=revision))
        self.assertTrue(result['ok'], result)
        self.assertEqual(result.get('values', {}).get('Actual'), '13')

    def test_xml_success_revision_describes_committed_bytes_even_if_file_changes_after_save(self):
        original = self.schema.read_bytes()
        expected = original.replace(b'<Actual>12</Actual>', b'<Actual>13</Actual>')
        atomic_write = core.atomic_write

        def external_edit_after_save(*args, **kwargs):
            revision = atomic_write(*args, **kwargs)
            self.schema.write_bytes(expected.replace(b'<Actual>13</Actual>', b'<Actual>99</Actual>'))
            return revision

        with patch.object(core, 'atomic_write', side_effect=external_edit_after_save):
            result = Api.param_write(dict(schema='job.xml', tag='Actual', value='13',
                revision=hashlib.sha256(original).hexdigest()))
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['revision'], hashlib.sha256(expected).hexdigest())
        self.assertNotEqual(result['revision'], core.file_revision(self.schema))

    def test_csv_success_revision_describes_committed_bytes_even_if_file_changes_after_save(self):
        grid = Api.csv_get(dict(path=[str(self.csv)], schema=['job.xml']))
        expected = b'Cell ID,CalcRadius\r\na,300\r\nb,300\r\n'
        atomic_write = core.atomic_write

        def external_edit_after_save(*args, **kwargs):
            revision = atomic_write(*args, **kwargs)
            self.csv.write_bytes(b'Cell ID,CalcRadius\r\na,999\r\n')
            return revision

        with patch.object(core, 'atomic_write', side_effect=external_edit_after_save):
            result = Api.csv_column(dict(path=str(self.csv), schema='job.xml', column='CalcRadius', value='300',
                revision=grid['revision'], format_revision=grid['format_revision']))
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['revision'], hashlib.sha256(expected).hexdigest())
        self.assertNotEqual(result['revision'], core.file_revision(self.csv))


if __name__ == '__main__':
    unittest.main()
