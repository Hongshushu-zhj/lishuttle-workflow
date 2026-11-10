"""Content-version and engineering-grid editor regression tests."""
import hashlib
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from server import Api, Handler


class SafeEditorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.csv = self.root / 'cells.csv'
        self.schema = self.root / 'build/Bin/runtimelibrary/job.xml'
        self.schema.parent.mkdir(parents=True)
        self.schema.write_bytes(('<RuntimeSchema name="job"><EngineeringFilePath>' +
            self.csv.as_posix() + '</EngineeringFilePath><DefaultCalcRadius>800</DefaultCalcRadius>' +
            '<Actual>12</Actual><!-- keep --></RuntimeSchema>').encode())
        self.csv.write_bytes(b'Cell ID,CalcRadius\r\na,100\r\nb,200\r\n')
        env = dict(PROJECT_DIR=self.root.as_posix(), BUILD_SUBDIR='build', EXE_NAME='engine.exe',
                   CONFIG_SRC='config', MAP_ROOT='', OUT_ROOT='', DT_ROOT='')
        patcher = patch.object(core, 'load_env', return_value=env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def params(self):
        return Api.params({'schema': ['job.xml'], 'func': ['pl']})

    def test_xml_revisions_reject_missing_and_stale_writes(self):
        revision = self.params()['revision']
        before = self.schema.read_bytes()
        self.assertEqual(Api.param_write(dict(schema='job.xml', tag='Actual', value='13'))['code'], 'REVISION_REQUIRED')
        self.assertEqual(Api.param_write(dict(schema='job.xml', tag='Actual', value='13', revision='old'))['code'], 'FILE_CONFLICT')
        self.assertEqual(self.schema.read_bytes(), before)
        self.assertFalse(Path(str(self.schema) + '.bak').exists())
        result = Api.param_write(dict(schema='job.xml', tag='Actual', value='13', revision=revision))
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['revision'], hashlib.sha256(self.schema.read_bytes()).hexdigest())
        self.assertEqual(Path(str(self.schema) + '.bak').read_bytes(), before)

    def test_single_header_csv_round_trip_and_column_change(self):
        grid = Api.csv_get({'path': [str(self.csv)]})
        self.assertEqual(grid['header_lines'], 1)
        self.assertEqual(grid['rows'], [['a', '100'], ['b', '200']])
        body = dict(path=str(self.csv), revision=grid['revision'], format_revision=grid['format_revision'],
                    header_rows=grid['header_rows'], header_lines=1, rows=[['a', '110'], ['b', '200']])
        saved = Api.csv_save(body)
        self.assertTrue(saved['ok'], saved)
        self.assertEqual(Api.csv_save(body)['code'], 'FILE_CONFLICT')
        self.assertEqual(self.csv.read_bytes(), b'Cell ID,CalcRadius\r\na,110\r\nb,200\r\n')
        changed = Api.csv_column(dict(path=str(self.csv), column='CalcRadius', value='125',
                                      revision=saved['revision'], format_revision=grid['format_revision']))
        self.assertTrue(changed['ok'], changed)
        self.assertEqual(core.read_csv_grid(str(self.csv))['rows'], [['a', '125'], ['b', '125']])

    def test_explicit_zero_headers_updates_first_record(self):
        fmt = self.schema.parent.parent / 'cellformat.xml'
        fmt.write_text('<TableFormat><HeaderLines>0</HeaderLines><CellId>A</CellId><CalcRadius>B</CalcRadius></TableFormat>')
        self.csv.write_bytes(b'a,100\r\nb,200\r\n')
        grid = core.read_csv_grid(str(self.csv), bin_dir=fmt.parent)
        self.assertEqual(grid['header_rows'], [])
        self.assertEqual(grid['rows'], [['a', '100'], ['b', '200']])
        result = Api.csv_column(dict(path=str(self.csv), column='CalcRadius', value='150', column_index=1,
                                     revision=grid['revision'], format_revision=grid['format_revision'],
                                     schema='job.xml'))
        self.assertTrue(result['ok'], result)
        self.assertEqual(self.csv.read_bytes(), b'a,150\r\nb,150\r\n')

    def test_radius_rejects_xml_source_switch(self):
        loaded = self.params()
        self.schema.write_bytes(self.schema.read_bytes().replace(b'cells.csv', b'other.csv'))
        other = self.root / 'other.csv'
        other.write_bytes(b'Cell ID,CalcRadius\r\na,999\r\n')
        result = Api.param_write(dict(schema='job.xml', tag='DefaultCalcRadius', value='150',
            revision=loaded['revision'], source_revision=loaded['param_sources']['DefaultCalcRadius']['revision'],
            format_revision=loaded['param_sources']['DefaultCalcRadius']['format_revision']))
        self.assertEqual(result['code'], 'FILE_CONFLICT')
        self.assertEqual(other.read_bytes(), b'Cell ID,CalcRadius\r\na,999\r\n')

    def test_csv_requires_versions_and_rejects_external_edit_without_backup(self):
        grid = Api.csv_get({'path': [str(self.csv)]})
        body = dict(path=str(self.csv), column='CalcRadius', value='150')
        self.assertEqual(Api.csv_column(body)['code'], 'REVISION_REQUIRED')
        self.csv.write_bytes(b'Cell ID,CalcRadius\r\na,900\r\n')
        body.update(revision=grid['revision'], format_revision=grid['format_revision'])
        self.assertEqual(Api.csv_column(body)['code'], 'FILE_CONFLICT')
        self.assertEqual(self.csv.read_bytes(), b'Cell ID,CalcRadius\r\na,900\r\n')
        self.assertFalse(Path(str(self.csv) + '.bak').exists())

    def test_format_change_rejects_old_grid_save(self):
        fmt = self.schema.parent.parent / 'cellformat.xml'
        fmt.write_text('<TableFormat><HeaderLines>1</HeaderLines><CellId>A</CellId><CalcRadius>B</CalcRadius></TableFormat>')
        grid = Api.csv_get({'path': [str(self.csv)], 'schema': ['job.xml']})
        fmt.write_text('<TableFormat><HeaderLines>0</HeaderLines><CellId>A</CellId><CalcRadius>B</CalcRadius></TableFormat>')
        before = self.csv.read_bytes()
        result = Api.csv_save(dict(path=str(self.csv), schema='job.xml', revision=grid['revision'],
            format_revision=grid['format_revision'], header_rows=grid['header_rows'], header_lines=1, rows=grid['rows']))
        self.assertEqual(result['code'], 'FILE_CONFLICT')
        self.assertEqual(self.csv.read_bytes(), before)

    def test_default_restore_obeys_xml_revision(self):
        revision = self.params()['revision']
        with patch.object(core, 'thirdpart_defaults', return_value={'Actual': dict(available=True, value='99', source='sample')}):
            self.assertEqual(Api.param_default(dict(schema='job.xml', tag='Actual'))['code'], 'REVISION_REQUIRED')
            self.schema.write_bytes(self.schema.read_bytes().replace(b'>12<', b'>15<'))
            result = Api.param_default(dict(schema='job.xml', tag='Actual', revision=revision))
        self.assertEqual(result['code'], 'FILE_CONFLICT')
        self.assertIn(b'>15<', self.schema.read_bytes())

    def test_csv_encoding_and_bom_preserved_on_column_save(self):
        for enc in ('utf-8', 'utf-8-sig', 'gb18030'):
            with self.subTest(encoding=enc):
                self.csv.write_bytes('Cell ID,CalcRadius,Note\r\na,100,中文\r\n'.encode(enc))
                grid = Api.csv_get({'path': [str(self.csv)]})
                result = Api.csv_column(dict(path=str(self.csv), column='CalcRadius', value='150',
                    revision=grid['revision'], format_revision=grid['format_revision']))
                self.assertTrue(result['ok'], result)
                self.assertEqual(self.csv.read_bytes(), 'Cell ID,CalcRadius,Note\r\na,150,中文\r\n'.encode(enc))

    def test_http_reports_missing_revision_and_conflict_without_mutation(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        before = self.schema.read_bytes()
        for revision, status, code in ((None, 400, 'REVISION_REQUIRED'), ('old', 409, 'FILE_CONFLICT')):
            body = dict(schema='job.xml', tag='Actual', value='99')
            if revision is not None:
                body['revision'] = revision
            request = Request(f'http://127.0.0.1:{server.server_port}/api/param_write',
                              data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
            with self.assertRaises(HTTPError) as caught:
                urlopen(request, timeout=3)
            with caught.exception as response:
                self.assertEqual(response.code, status)
                self.assertEqual(json.load(response)['code'], code)
        self.assertEqual(self.schema.read_bytes(), before)

    def test_duplicate_arbitrary_column_names_refuse_ambiguous_column_edit(self):
        self.csv.write_bytes(b'Cell ID,CalcRadius,Note,Note\r\na,100,first,second\r\n')
        before = self.csv.read_bytes()
        grid = Api.csv_get({'path': [str(self.csv)]})
        result = Api.csv_column(dict(path=str(self.csv), column='Note', value='overwritten',
            revision=grid['revision'], format_revision=grid['format_revision']))
        self.assertFalse(result['ok'], result)
        self.assertEqual(self.csv.read_bytes(), before)

    def test_malformed_csv_does_not_prevent_loading_xml_or_allow_rewrite(self):
        self.csv.write_bytes(b'Cell ID,CalcRadius\r\na,"100\r\nb,200\r\n')
        before = self.csv.read_bytes()
        grid = Api.csv_get({'path': [str(self.csv)]})
        self.assertIn('error', grid)
        params = self.params()
        self.assertEqual(params['values']['Actual'], '12')
        self.assertFalse(params['param_sources']['DefaultCalcRadius']['editable'])
        result = Api.csv_save(dict(path=str(self.csv), revision=hashlib.sha256(before).hexdigest(),
            format_revision='missing', header_rows=[['Cell ID', 'CalcRadius']], header_lines=1, rows=[['a', '150']]))
        self.assertFalse(result['ok'], result)
        self.assertEqual(self.csv.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
