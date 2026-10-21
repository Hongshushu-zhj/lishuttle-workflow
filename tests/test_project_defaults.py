from pathlib import Path
import sys
import tempfile
import unittest
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core
from server import Api


class ProjectDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / '任意项目名'
        self.project.mkdir()
        (self.project / 'CMakeLists.txt').write_text('project(LiShuttle)')
        (self.project / 'LiShuttle').mkdir()
        header = self.project / 'SwanUtility/incl/LiShuttleTypes.h'
        header.parent.mkdir(parents=True)
        header.write_text('#define PM_CALIBRATION_SERVICE "cali"')
        self.config = self.project / 'ThirdPart/Config'
        (self.config / 'runtimelibrary').mkdir(parents=True)
        (self.config / 'config').mkdir()
        (self.config / 'config/scenesettings.xml').write_text('<Scene/>')
        (self.config / 'runtimelibrary/runtimeschema.xml').write_text(
            '<RuntimeSchema><SceneSettingsPath>../scenesettings.xml</SceneSettingsPath>'
            '<EngineeringFilePath>../old.csv</EngineeringFilePath>'
            '<CpuLoad>80</CpuLoad></RuntimeSchema>')
        self.env = dict(PROJECT_DIR=str(self.project), CONFIG_SRC='ThirdPart/Config',
                        BUILD_SUBDIR='out/build/custom', EXE_NAME='lishuttle.exe')
        self.registry = self.root / 'projects.json'
        for name, value in [('load_env', lambda: self.env), ('PROJECTS_FILE', str(self.registry))]:
            p = patch.object(core, name, value, create=True); p.start(); self.addCleanup(p.stop)

    def test_content_validation_and_manual_registry(self):
        result = core.validate_project(str(self.project))
        self.assertTrue(result['ok'])
        self.assertIn('CMakePresets.json', ' '.join(result['warnings']))
        other = self.root / 'Lab20990101'; other.mkdir()
        (other / 'CMakePresets.json').write_text('{}')
        self.assertFalse(core.validate_project(str(other))['ok'])
        with patch.object(core, 'save_env_keys') as save:
            core.add_project(str(self.project))
            core.add_project(str(self.project))
        self.assertEqual(core.scan_projects()[0], [self.project.as_posix()])
        self.assertEqual(len(__import__('json').loads(self.registry.read_text(encoding='utf-8'))['projects']), 1)

    def test_missing_current_parent_does_not_break_listing(self):
        self.env['PROJECT_DIR'] = str(self.root / 'missing' / 'old')
        self.assertEqual(core.scan_projects()[0], [(self.root / 'missing/old').as_posix()])

    def test_registry_normalizes_equivalent_paths(self):
        import json
        self.registry.write_text(json.dumps({'projects': [str(self.project) + '/.', str(self.project)]}), encoding='utf-8')
        self.assertEqual(core.scan_projects()[0], [self.project.as_posix()])

    def test_defaults_only_use_existing_project_resources(self):
        defaults = core.thirdpart_defaults()
        self.assertEqual(defaults['SceneSettingsPath']['value'],
                         (self.config / 'config/scenesettings.xml').as_posix())
        self.assertTrue(defaults['SceneSettingsPath']['available'])
        self.assertFalse(defaults['EngineeringFilePath']['available'])
        self.assertEqual(defaults['CpuLoad']['value'], '80')

    def test_default_write_backups_and_preserves_other_fields(self):
        dest = self.project / 'out/build/custom/Bin/runtimelibrary/job.xml'
        dest.parent.mkdir(parents=True)
        original = b'\xef\xbb\xbf<RuntimeSchema>\r\n<!--keep--><SceneSettingsPath></SceneSettingsPath><CpuLoad>17</CpuLoad></RuntimeSchema>'
        dest.write_bytes(original)
        res = Api.param_default(dict(schema='job.xml', tag='SceneSettingsPath'))
        self.assertTrue(res['ok'])
        self.assertEqual(Path(str(dest) + '.bak').read_bytes(), original)
        self.assertEqual(dest.read_bytes(), original.replace(b'<SceneSettingsPath></SceneSettingsPath>',
            ('<SceneSettingsPath>' + (self.config / 'config/scenesettings.xml').as_posix() + '</SceneSettingsPath>').encode()))
        before = dest.read_bytes()
        self.assertFalse(Api.param_default(dict(schema='job.xml', tag='EngineeringFilePath'))['ok'])
        self.assertEqual(dest.read_bytes(), before)

    def test_missing_resource_is_revalidated_at_click(self):
        (self.config / 'config/scenesettings.xml').unlink()
        res = Api.param_default(dict(schema='job.xml', tag='SceneSettingsPath'))
        self.assertFalse(res['ok'])

    def test_self_closing_field_and_xml_characters(self):
        dest = self.project / 'out/build/custom/Bin/runtimelibrary/job.xml'
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b'<RuntimeSchema><SceneSettingsPath /></RuntimeSchema>')
        ok, _ = core.write_schema_param('job.xml', 'SceneSettingsPath', '/data/a&b.xml')
        self.assertTrue(ok)
        self.assertIn(b'a&amp;b.xml', dest.read_bytes())
        self.assertEqual(core.read_schema('job.xml')[1]['SceneSettingsPath'], '/data/a&b.xml')

    def test_stale_project_write_is_rejected(self):
        res = Api.param_default(dict(schema='job.xml', tag='CpuLoad', _project='/old-project'))
        self.assertFalse(res['ok'])
        self.assertIn('项目已切换', res['message'])

    def test_project_switch_waits_for_default_write(self):
        entered = threading.Event()
        release = threading.Event()
        switched = threading.Event()
        original_defaults = core.thirdpart_defaults
        def defaults():
            value = original_defaults()
            entered.set()
            if not release.wait(3):
                raise RuntimeError('test timeout')
            return value
        target = self.project / 'out/build/custom/Bin/runtimelibrary/job.xml'
        target.parent.mkdir(parents=True)
        target.write_text('<RuntimeSchema><CpuLoad>99</CpuLoad></RuntimeSchema>')
        with patch.object(core, 'thirdpart_defaults', defaults), \
             patch.object(core, 'save_env_keys', side_effect=lambda **kw: switched.set()), \
             patch.object(Api, 'state', return_value={}):
            writer = threading.Thread(target=lambda: Api.param_default(dict(schema='job.xml', tag='CpuLoad')))
            switch = threading.Thread(target=lambda: Api.select_project(dict(path=str(self.project))))
            writer.start()
            try:
                self.assertTrue(entered.wait(3))
                switch.start()
                self.assertFalse(switched.wait(.1))
            finally:
                release.set()
                writer.join(3)
                if switch.ident is not None:
                    switch.join(3)
            self.assertTrue(switched.is_set())
        self.assertIn('<CpuLoad>80</CpuLoad>', target.read_text())


if __name__ == '__main__':
    unittest.main()
