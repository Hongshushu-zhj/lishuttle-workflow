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

    def default_param(self, **body):
        _, document = core.read_schema_document(body.get('schema', 'job.xml'))
        return Api.param_default(dict(body, revision=document['revision'] if document else 'missing'))

    def write_target(self, fields):
        target = self.project / 'out/build/custom/Bin/runtimelibrary/job.xml'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('<RuntimeSchema>' + fields + '</RuntimeSchema>', encoding='utf-8')
        return target

    def write_indoor_sample(self, fields='<CpuLoad>40</CpuLoad>'):
        sample = self.config / 'runtimelibrary/indoorruntimeschema.xml'
        sample.write_text('<RuntimeSchema><MapFormat>indoor</MapFormat>' + fields + '</RuntimeSchema>',
                          encoding='utf-8')
        return sample

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

    def test_default_source_uses_actual_xml_scene_instead_of_requested_function(self):
        indoor_sample = self.write_indoor_sample()
        cases = [('<MapFormat>indoor</MapFormat>', 'pl', '40', indoor_sample),
                 ('<MapPath>maps/scene</MapPath>', 'predindoor', '80',
                  self.config / 'runtimelibrary/runtimeschema.xml'),
                 ('<MapFormat>PLANET</MapFormat><MapPath>unused</MapPath>',
                  'predindoor', '80', self.config / 'runtimelibrary/runtimeschema.xml')]
        for fields, func, value, sample in cases:
            with self.subTest(fields=fields):
                target = self.write_target(fields + '<CpuLoad>99</CpuLoad>')
                response = Api.params(dict(schema=['job.xml'], func=[func]))
                default = response['thirdpart_defaults']['CpuLoad']
                self.assertEqual(default['value'], value)
                self.assertEqual(default['source'], sample.as_posix())
                result = self.default_param(schema='job.xml', tag='CpuLoad', func=func)
                self.assertTrue(result['ok'], result)
                self.assertIn('<CpuLoad>' + value + '</CpuLoad>', target.read_text(encoding='utf-8'))

    def test_missing_or_invalid_indoor_sample_never_falls_back_to_outdoor_default(self):
        for contents in (None, '<RuntimeSchema>', '<Other><CpuLoad>22</CpuLoad></Other>',
                         '<RuntimeSchema><MapFormat>PLANET</MapFormat><CpuLoad>22</CpuLoad></RuntimeSchema>'):
            with self.subTest(contents=contents):
                sample = self.config / 'runtimelibrary/indoorruntimeschema.xml'
                if contents is None:
                    sample.unlink(missing_ok=True)
                else:
                    sample.write_text(contents, encoding='utf-8')
                target = self.write_target('<MapFormat>indoor</MapFormat><CpuLoad>99</CpuLoad>')
                before = target.read_bytes()
                response = Api.params(dict(schema=['job.xml'], func=['pl']))
                self.assertNotIn('CpuLoad', response['thirdpart_defaults'])
                result = self.default_param(schema='job.xml', tag='CpuLoad')
                self.assertFalse(result['ok'], result)
                self.assertEqual(target.read_bytes(), before)
                self.assertFalse(Path(str(target) + '.bak').exists())

    def test_duplicate_and_structured_sample_defaults_are_disabled_and_explained(self):
        self.write_indoor_sample('<DefaultUEHeight>1</DefaultUEHeight>'
                                 '<DefaultUEHeight>1.5</DefaultUEHeight>'
                                 '<CpuLoad><Value>40</Value></CpuLoad>')
        target = self.write_target('<MapFormat>indoor</MapFormat><DefaultUEHeight>9</DefaultUEHeight>'
                                   '<CpuLoad>99</CpuLoad>')
        before = target.read_bytes()
        response = Api.params(dict(schema=['job.xml'], func=['pl']))
        for tag, reason in (('DefaultUEHeight', '重复'), ('CpuLoad', '结构化')):
            with self.subTest(tag=tag):
                default = response['thirdpart_defaults'][tag]
                self.assertFalse(default['available'])
                self.assertIn(reason, default['reason'])
                result = self.default_param(schema='job.xml', tag=tag)
                self.assertFalse(result['ok'], result)
                self.assertIn(reason, result['message'])
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse(Path(str(target) + '.bak').exists())

    def test_restore_reloads_actual_xml_scene_and_preserves_revision_conflict(self):
        self.write_indoor_sample()
        target = self.write_target('<MapFormat>PLANET</MapFormat><CpuLoad>99</CpuLoad>')
        loaded = Api.params(dict(schema=['job.xml'], func=['pl']))
        self.assertEqual(loaded['thirdpart_defaults']['CpuLoad']['value'], '80')
        target.write_bytes(target.read_bytes().replace(b'PLANET', b'indoor'))
        before = target.read_bytes()
        conflict = Api.param_default(dict(schema='job.xml', tag='CpuLoad', revision=loaded['revision']))
        self.assertEqual(conflict['code'], 'FILE_CONFLICT')
        self.assertEqual(target.read_bytes(), before)
        result = self.default_param(schema='job.xml', tag='CpuLoad')
        self.assertTrue(result['ok'], result)
        self.assertIn('<CpuLoad>40</CpuLoad>', target.read_text(encoding='utf-8'))

    def test_default_write_backups_and_preserves_other_fields(self):
        dest = self.project / 'out/build/custom/Bin/runtimelibrary/job.xml'
        dest.parent.mkdir(parents=True)
        original = b'\xef\xbb\xbf<RuntimeSchema>\r\n<!--keep--><SceneSettingsPath></SceneSettingsPath><CpuLoad>17</CpuLoad></RuntimeSchema>'
        dest.write_bytes(original)
        res = self.default_param(schema='job.xml', tag='SceneSettingsPath')
        self.assertTrue(res['ok'])
        self.assertEqual(Path(str(dest) + '.bak').read_bytes(), original)
        self.assertEqual(dest.read_bytes(), original.replace(b'<SceneSettingsPath></SceneSettingsPath>',
            ('<SceneSettingsPath>' + (self.config / 'config/scenesettings.xml').as_posix() + '</SceneSettingsPath>').encode()))
        before = dest.read_bytes()
        self.assertFalse(self.default_param(schema='job.xml', tag='EngineeringFilePath')['ok'])
        self.assertEqual(dest.read_bytes(), before)

    def test_missing_resource_is_revalidated_at_click(self):
        (self.config / 'config/scenesettings.xml').unlink()
        res = self.default_param(schema='job.xml', tag='SceneSettingsPath')
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
        res = self.default_param(schema='job.xml', tag='CpuLoad', _project='/old-project')
        self.assertFalse(res['ok'])
        self.assertIn('项目已切换', res['message'])

    def test_project_switch_is_busy_during_default_write_then_can_retry(self):
        entered = threading.Event()
        release = threading.Event()
        switched = threading.Event()
        switch_results = []
        original_defaults = core.thirdpart_defaults
        def defaults(values=None):
            value = original_defaults(values)
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
            writer = threading.Thread(target=lambda: self.default_param(schema='job.xml', tag='CpuLoad'))
            switch = threading.Thread(target=lambda: switch_results.append(Api.select_project(dict(path=str(self.project)))))
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
            self.assertEqual(switch_results[0]['code'], 'RUNTIME_BUSY')
            self.assertFalse(switched.is_set())
            Api.select_project(dict(path=str(self.project)))
            self.assertTrue(switched.is_set())
        self.assertIn('<CpuLoad>80</CpuLoad>', target.read_text())


if __name__ == '__main__':
    unittest.main()
