from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import project_config


@unittest.skipUnless(os.name == 'nt', 'Windows stage entrypoint')
class StageRuntimePreservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / '临时项目 with spaces'
        self.config = self.root / '外部配置 with spaces'
        self.dll = self.root / '外部动态库 with spaces'
        self.bin = self.project / 'out/Debug/Bin'
        self.runtime = self.bin / 'runtimelibrary'
        self.runtime.mkdir(parents=True)
        (self.config / 'runtimelibrary/nested').mkdir(parents=True)
        (self.config / 'config').mkdir()
        self.dll.mkdir()
        (self.bin / 'fixture.exe').write_bytes(b'fixture only; never executed')
        self.env = dict(PROJECT_DIR=self.project.as_posix(), BUILD_SUBDIR='out/Debug',
                        EXE_NAME='fixture.exe', CONFIG_SRC=self.config.as_posix(),
                        DLL_SRC=self.dll.as_posix())
        self.snapshot = project_config.write_snapshot(self.env, self.root / 'snapshots')

    def stage(self):
        result = subprocess.run(['cmd', '/d', '/c', 'scripts\\stage_local.bat'], cwd=ROOT,
            env=dict(os.environ, LISHUTTLE_CONFIG_SNAPSHOT=self.snapshot),
            capture_output=True, timeout=30)
        output = (result.stdout + result.stderr).decode('gbk', errors='replace')
        self.assertEqual(result.returncode, 0, output)

    def source(self, relative, content):
        path = self.config / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        os.utime(path, ns=(2_000_000_000_000_000_000, 2_000_000_000_000_000_000))
        return path

    def test_existing_runtime_xml_bytes_and_mtime_survive_real_stage(self):
        kept = {}
        for relative in ('saved.xml', 'RuntimeSchema.XML', 'nested/indoor.xml'):
            destination = self.runtime / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            content = b'\xef\xbb\xbf<RuntimeSchema name="tuned">\r\n<!-- keep -->\r\n<Unknown>7</Unknown></RuntimeSchema>\r\n'
            destination.write_bytes(content)
            os.utime(destination, ns=(1_500_000_000_000_000_000, 1_500_000_000_000_000_000))
            kept[destination] = (content, destination.stat().st_mtime_ns)
            self.source('runtimelibrary/' + relative, b'<RuntimeSchema name="default"/>')
        (self.config / 'config/cellformat.xml').write_bytes(b'<CellFormat/>')

        self.stage()

        for destination, (content, modified) in kept.items():
            with self.subTest(schema=destination.name):
                self.assertEqual(destination.read_bytes(), content)
                self.assertEqual(destination.stat().st_mtime_ns, modified)

    def test_missing_runtime_xml_is_seeded_byte_for_byte(self):
        expected = b'\xef\xbb\xbf<RuntimeSchema name="seed">\r\n<!-- original -->\r\n</RuntimeSchema>\r\n'
        for relative in ('runtimeschema.xml', 'nested/indoorruntimeschema.xml'):
            self.source('runtimelibrary/' + relative, expected)
        (self.config / 'config/cellformat.xml').write_bytes(b'<CellFormat/>')

        self.stage()

        self.assertEqual((self.runtime / 'runtimeschema.xml').read_bytes(), expected)
        self.assertEqual((self.runtime / 'nested/indoorruntimeschema.xml').read_bytes(), expected)

    def test_dll_source_preserves_runtime_xml_and_seeds_missing_xml(self):
        existing = self.runtime / 'saved.xml'
        content = b'\xef\xbb\xbf<RuntimeSchema name="tuned">\r\n<!-- preserve -->\r\n</RuntimeSchema>'
        existing.write_bytes(content)
        before = existing.stat().st_mtime_ns
        dll_runtime = self.dll / 'runtimelibrary'
        dll_runtime.mkdir()
        (dll_runtime / 'saved.xml').write_bytes(b'<RuntimeSchema name="dll-default"/>')
        seed = b'<RuntimeSchema name="dll-seed"/>\r\n'
        (dll_runtime / 'dll-seed.xml').write_bytes(seed)
        (dll_runtime / 'data.bin').write_bytes(b'updated runtime data from DLL source')
        (self.runtime / 'data.bin').write_bytes(b'old')
        self.source('config/cellformat.xml', b'<CellFormat/>')

        self.stage()

        self.assertEqual(existing.read_bytes(), content)
        self.assertEqual(existing.stat().st_mtime_ns, before)
        self.assertEqual((self.runtime / 'dll-seed.xml').read_bytes(), seed)
        self.assertEqual((self.runtime / 'data.bin').read_bytes(), b'updated runtime data from DLL source')

    def test_stage_still_updates_dll_and_other_configuration_resources(self):
        self.source('config/cellformat.xml', b'<CellFormat>updated</CellFormat>')
        self.source('models/model.xml', b'<Model>updated</Model>')
        self.source('runtimelibrary/data.bin', b'updated runtime binary data')
        for relative in ('cellformat.xml', 'config/cellformat.xml', 'models/model.xml',
                         'runtimelibrary/data.bin', 'sample.dll'):
            destination = self.bin / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b'old')
        dll_content = b'updated DLL fixture; never executed'
        (self.dll / 'sample.dll').write_bytes(dll_content)

        self.stage()

        self.assertEqual((self.bin / 'cellformat.xml').read_bytes(), b'<CellFormat>updated</CellFormat>')
        self.assertEqual((self.bin / 'config/cellformat.xml').read_bytes(), b'<CellFormat>updated</CellFormat>')
        self.assertEqual((self.bin / 'models/model.xml').read_bytes(), b'<Model>updated</Model>')
        self.assertEqual((self.runtime / 'data.bin').read_bytes(), b'updated runtime binary data')
        self.assertEqual((self.bin / 'sample.dll').read_bytes(), dll_content)


if __name__ == '__main__':
    unittest.main()
