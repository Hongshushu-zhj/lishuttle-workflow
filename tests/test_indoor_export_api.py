from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core
from server import Api, ROUTES


class IndoorExportApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'Propagation/Frame/src/PathLossofIndoorEngine.cpp'
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b'#if false\nstd::string filePath = m_calcParams.pathlossDirectory + "/building.txt";\npBuilding->Export(filePath.c_str());\n#endif\n')
        self.env = {'PROJECT_DIR': str(self.root), 'BUILD_SUBDIR': 'build', 'OUT_ROOT': str(self.root / 'out')}
        env_patch = patch.object(core, 'load_env', return_value=self.env)
        env_patch.start()
        self.addCleanup(env_patch.stop)

    def test_status_and_enable_route_require_current_revision(self):
        self.assertTrue(hasattr(Api, 'indoor_building_export'), '缺少导出开关状态接口')
        status = Api.indoor_building_export({})
        self.assertFalse(status['enabled'])
        result = Api.enable_indoor_building_export({'revision': status['revision']})
        self.assertTrue(result['enabled'])
        self.assertTrue(result['requires_rebuild'])
        self.assertIn(b'#if true', self.source.read_bytes())
        self.assertIs(ROUTES[('POST', 'enable_indoor_building_export')], Api.enable_indoor_building_export)

    def test_missing_revision_and_conflict_never_overwrite_source(self):
        self.assertTrue(hasattr(Api, 'enable_indoor_building_export'), '缺少导出开关操作接口')
        status = Api.indoor_building_export({})
        self.assertEqual(Api.enable_indoor_building_export({})['code'], 'REVISION_REQUIRED')
        original = self.source.read_bytes() + b'// external edit\n'
        self.source.write_bytes(original)
        response = Api.enable_indoor_building_export({'revision': status['revision']})
        self.assertEqual(response['code'], 'FILE_CONFLICT')
        self.assertEqual(self.source.read_bytes(), original)

    def test_runtime_busy_rejects_source_change_before_config_read(self):
        self.assertTrue(hasattr(Api, 'enable_indoor_building_export'), '缺少导出开关操作接口')
        with core.RUNTIME.operation('fixture build'):
            # Different context/thread cannot re-enter this lease.
            import contextvars
            with patch.object(core, 'load_env', side_effect=AssertionError('must reject before read')):
                response = contextvars.Context().run(Api.enable_indoor_building_export, {})
        self.assertEqual(response['code'], 'RUNTIME_BUSY')


if __name__ == '__main__':
    unittest.main()
