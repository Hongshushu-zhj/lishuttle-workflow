"""Shared layout parsing and conservative editor header validation."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
from engineering_format import cell_layout, grid_layout
import preflight


class EngineeringFormatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bin = Path(self.temp.name)

    def format(self, body, encoding='utf-8'):
        (self.bin / 'cellformat.xml').write_bytes(body.encode(encoding))

    def test_gb18030_format_uses_declared_single_header(self):
        self.format('<?xml version="1.0" encoding="GB2312"?>\n'
                    '<!-- 工参格式 -->\n<TableFormat><HeaderLines>1</HeaderLines>'
                    '<CellId>A</CellId><CalcRadius>B</CalcRadius></TableFormat>', 'gb18030')
        layout = cell_layout(self.bin)
        self.assertTrue(layout['explicit'], layout)
        self.assertEqual(layout['header_lines'], 1)
        self.assertEqual(layout['columns']['CalcRadius'], 1)

    def test_empty_format_is_read_only_instead_of_raising(self):
        self.format('')
        layout = grid_layout([['Cell ID', 'CalcRadius'], ['a', '100']], self.bin)
        self.assertFalse(layout['editable'], layout)

    def test_malformed_existing_format_does_not_enable_header_fallback(self):
        self.format('<TableFormat><HeaderLines>oops</HeaderLines></TableFormat>')
        layout = grid_layout([['Cell ID', 'CalcRadius'], ['a', '100']], self.bin)
        self.assertFalse(layout['editable'], layout)
        self.assertIn('cellformat.xml', layout['error'])

    def test_data_value_matching_one_label_does_not_hide_first_record(self):
        rows = [['Cell ID', 'CalcRadius'], ['Antenna', '100'], ['b', '200']]
        layout = grid_layout(rows)
        self.assertEqual(layout['header_lines'], 1)
        self.assertTrue(layout['editable'], layout)
        self.assertEqual(rows[layout['header_lines']:][0], ['Antenna', '100'])

    def test_duplicate_column_aliases_are_read_only(self):
        layout = grid_layout([['Cell ID', 'CalcRadius', '计算半径'], ['a', '100', '200']])
        self.assertFalse(layout['editable'], layout)

    def test_explicit_header_count_cannot_hide_a_data_record(self):
        self.format('<TableFormat><HeaderLines>2</HeaderLines>'
                    '<CellId>A</CellId><CalcRadius>B</CalcRadius></TableFormat>')
        layout = grid_layout([['Cell ID', 'CalcRadius'], ['a', '100'], ['b', '200']], self.bin)
        self.assertFalse(layout['editable'], layout)

    def test_single_header_indoor_is_read_only_with_fixed_two_header_loader(self):
        header = [''] * 32
        for index, label in {0: 'AP ID', 2: 'Cell ID', 3: 'Floor', 4: 'x', 5: 'y',
                             10: 'Antenna', 13: 'Max Power (dBm)'}.items():
            header[index] = label
        data = ['0'] * 32
        data[0], data[2], data[10] = 'ap1', 'c1', 'omni'
        layout = grid_layout([header, data], indoor=True)
        self.assertFalse(layout['editable'], layout)
        self.assertIn('表头行数', layout['error'])

    def test_short_id_label_and_english_radius_header_remain_supported(self):
        rows = [['ID', '半径'], ['Cell ID', 'Main Calculation Radius (m)'], ['a', '100']]
        layout = grid_layout(rows)
        self.assertTrue(layout['editable'], layout)
        self.assertEqual(layout['header_lines'], 2)
        self.assertEqual(layout['columns']['CalcRadius'], 1)

    def test_indoor_preflight_and_editor_use_the_same_fixed_layout(self):
        import csv
        header = [''] * 32
        for index, label in {0: 'AP ID', 2: 'Cell ID', 3: 'Floor', 4: 'x', 5: 'y',
                             6: 'Height (m)', 10: 'Antenna', 13: 'Max Power (dBm)'}.items():
            header[index] = label
        data = ['1'] * 32
        for index, value in {0: 'ap1', 2: 'c1', 10: 'omni',
                             17: 'LiShuttleIndoorModel_1', 31: 'LTE-FDD'}.items():
            data[index] = value
        path = self.bin / 'indoor.csv'
        with path.open('w', encoding='utf-8', newline='') as output:
            csv.writer(output).writerows([header, header, data])
        issues = []
        info = preflight._engineering(str(path), 'indoor', lambda *args: issues.append(args), self.bin)
        layout = grid_layout([header, header, data], indoor=True)
        self.assertTrue(layout['editable'], layout)
        self.assertEqual(info['format']['columns'], layout['columns'])
        self.assertEqual(issues, [])

    def test_preflight_and_editor_share_whitespace_normalized_configuration(self):
        self.format('<TableFormat><HeaderLines> 1 </HeaderLines>'
                    '<CellId> A </CellId><CalcRadius> B </CalcRadius>'
                    '<EPRE> C </EPRE></TableFormat>')
        issues = []
        columns, headers = preflight._cell_columns(self.bin, lambda *args: issues.append(args))
        layout = cell_layout(self.bin)
        self.assertEqual((columns, headers), (layout['columns'], layout['header_lines']))
        self.assertEqual(columns['CalcRadius'], 1)
        self.assertEqual(issues, [])

    def test_zero_headers_and_two_bilingual_headers_are_supported(self):
        self.format('<TableFormat><HeaderLines>0</HeaderLines>'
                    '<CellId>A</CellId><CalcRadius>B</CalcRadius></TableFormat>')
        zero = grid_layout([['a', '100'], ['b', '200']], self.bin)
        self.assertTrue(zero['editable'], zero)
        self.assertEqual(zero['header_lines'], 0)
        two = grid_layout([['小区ID', '计算半径'], ['Cell ID', 'CalcRadius'], ['a', '100']])
        self.assertTrue(two['editable'], two)
        self.assertEqual(two['header_lines'], 2)

    def test_existing_format_checks_all_known_parameter_positions(self):
        self.format('<TableFormat><HeaderLines>1</HeaderLines>'
                    '<CellId>A</CellId><CalcRadius>B</CalcRadius>'
                    '<EPRE>D</EPRE></TableFormat>')
        layout = grid_layout([['Cell ID', 'CalcRadius', 'EPRE per antenna port'],
                              ['a', '100', '14']], self.bin)
        self.assertFalse(layout['editable'], layout)

    def outdoor_csv(self, header_lines):
        import csv
        header = [''] * 35
        for index, label in {0: 'Cell ID', 2: 'Site ID', 4: 'Longitude', 5: 'Latitude',
            8: 'Height (m)', 9: 'Azimuth', 10: 'Mechanical Downtilt (°)',
            11: 'Additional Electrical Downtilt (°)', 12: 'Antenna',
            13: 'Number of Transmission Antennas', 14: 'Number of Reception Antennas',
            15: 'Max Power (dBm)', 16: 'EPRE per antenna port', 18: 'Channel Number',
            19: 'Main Propagation Model', 23: 'Main Calculation Radius (m)', 34: 'Cell Type'}.items():
            header[index] = label
        first = ['0'] * 35
        for index, value in {0: 'c1', 2: 's1', 4: '119', 5: '26', 8: '20',
            12: 'omni', 13: '4', 14: '4', 15: '40', 16: '14', 18: '1300',
            19: 'LiShuttleModel_1', 23: '100', 34: 'NR'}.items():
            first[index] = value
        second = first.copy()
        second[0] = 'c2'
        path = self.bin / 'outdoor.csv'
        rows = [header.copy() for _ in range(header_lines)] + [first, second]
        with path.open('w', encoding='utf-8', newline='') as output:
            csv.writer(output).writerows(rows)
        return path, rows

    def test_explicit_zero_one_two_headers_preserve_same_preflight_and_editor_record_counts(self):
        for headers in (0, 1, 2):
            with self.subTest(headers=headers):
                self.format(f'<TableFormat><HeaderLines>{headers}</HeaderLines></TableFormat>')
                path, rows = self.outdoor_csv(headers)
                issues = []
                info = preflight._engineering(str(path), 'outdoor', lambda *args: issues.append(args), self.bin)
                layout = grid_layout(rows, self.bin)
                self.assertEqual(issues, [])
                self.assertEqual(info['rows'], 2)
                self.assertEqual(info['ids'], ['c1', 'c2'])
                self.assertEqual(len(rows[layout['header_lines']:]), info['rows'])

    def test_default_two_headers_reports_a_single_header_file_instead_of_silently_skipping_first_record(self):
        path, rows = self.outdoor_csv(1)
        issues = []
        info = preflight._engineering(str(path), 'outdoor', lambda *args: issues.append(args), self.bin)
        layout = grid_layout(rows, self.bin)
        self.assertEqual(layout['header_lines'], 1)
        self.assertEqual(info['format']['header_lines'], 2)
        self.assertTrue(any(issue[:2] == ('error', 'ENGINEERING_HEADER_COUNT') for issue in issues), issues)


if __name__ == '__main__':
    unittest.main()
