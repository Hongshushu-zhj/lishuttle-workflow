from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core


class VisualStudioLaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / '任意项目'
        self.project.mkdir()
        self.env = dict(PROJECT_DIR=str(self.project), BUILD_SUBDIR='out/build/custom',
                        EXE_NAME='lishuttle.exe')
        self.path = self.project / '.vs/launch.vs.json'
        self.available = ['pl', 'pred', 'rays', 'dt', 'cali', 'acp', 'ai', 'scene',
                          'plindoor', 'predindoor', 'indoorrays', 'test']
        p = patch.object(core, 'scan_functions', return_value=self.available)
        p.start()
        self.addCleanup(p.stop)

    def generate(self, schema='ningde.xml', func='cali', kind='outdoor', task_id='1'):
        return core.sync_vs_launch(self.env, schema, func, task_id, kind)

    def test_generates_main_outdoor_functions_with_current_task_xml(self):
        self.assertTrue(callable(getattr(core, 'sync_vs_launch', None)),
                        '平台尚未提供 Visual Studio 启动项同步')
        result = self.generate()
        data = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(data['version'], '0.2.1')
        configs = data['configurations']
        self.assertEqual({c['args'][1] for c in configs}, set(self.available[:8]))
        for c in configs:
            self.assertEqual(c['args'][2:], ['-t', '1', '-c', 'ningde.xml'])
            self.assertEqual(c['project'], 'CMakeLists.txt')
            self.assertEqual(c['projectTarget'], 'lishuttle.exe (Bin\\lishuttle.exe)')
            self.assertEqual(c['program'], '${projectDir}/out/build/custom/Bin/lishuttle.exe')
            self.assertEqual(c['currentDir'], '${projectDir}/out/build/custom/Bin')
        self.assertEqual(result['path'], self.path.as_posix())

    def test_indoor_only_generates_indoor_functions(self):
        self.generate('indoor.xml', 'predindoor', 'indoor')
        configs = json.loads(self.path.read_text(encoding='utf-8'))['configurations']
        self.assertEqual({c['args'][1] for c in configs},
                         {'plindoor', 'predindoor', 'indoorrays'})

    def test_only_supported_functions_and_explicit_selected_function(self):
        with patch.object(core, 'scan_functions', return_value=['pl', 'cali', 'hybridrays']):
            self.generate(func='hybridrays', task_id='7')
        configs = json.loads(self.path.read_text(encoding='utf-8'))['configurations']
        self.assertEqual({c['args'][1] for c in configs}, {'pl', 'cali', 'hybridrays'})
        self.assertTrue(all(c['args'][3] == '7' for c in configs))

    def test_repeat_updates_managed_entries_keeps_custom_entries_and_other_tasks(self):
        self.generate()
        self.generate('other.xml', 'pl')
        data = json.loads(self.path.read_text(encoding='utf-8'))
        custom = dict(name='我的校正调试', args=['-f', 'cali', '-c', 'custom.xml'],
                      env={'CUSTOM': 'yes'})
        data['configurations'].append(custom)
        data['defaults'] = {'custom': 42}
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        original = self.path.read_bytes()
        self.env['BUILD_SUBDIR'] = 'out/build/new'
        self.generate(task_id='3')
        data = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertIn(custom, data['configurations'])
        self.assertEqual(data['defaults'], {'custom': 42})
        self.assertEqual(len(data['configurations']), 17)
        current = [c for c in data['configurations'] if c.get('args', [])[-1:] == ['ningde.xml']]
        self.assertTrue(all(c['args'][3] == '3' and '/new/Bin/' in c['program'] for c in current))
        self.assertEqual(Path(str(self.path) + '.bak').read_bytes(), original)
        before = self.path.read_bytes()
        self.generate(task_id='3')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(Path(str(self.path) + '.bak').read_bytes(), original)

    def test_jsonc_comments_trailing_commas_and_custom_text_are_preserved(self):
        self.path.parent.mkdir()
        source = '''{
  // VS 的手工配置
  "version": "0.2.1",
  "configurations": [
    /* 不改动此条 */ {"name":"custom", "url":"https://host/a//b", "args":[],},
  ],
  "defaults": {},
}'''
        self.path.write_text(source, encoding='utf-8-sig')
        self.generate()
        text = self.path.read_text(encoding='utf-8-sig')
        self.assertIn('// VS 的手工配置', text)
        self.assertIn('/* 不改动此条 */ {"name":"custom", "url":"https://host/a//b", "args":[],}', text)
        self.assertIn('"cali"', text)
        before = self.path.read_bytes()
        self.generate(task_id='2')
        self.assertIn('/* 不改动此条 */', self.path.read_text(encoding='utf-8-sig'))
        self.assertEqual(Path(str(self.path) + '.bak').read_bytes(), before)

    def test_invalid_existing_file_is_not_overwritten(self):
        self.path.parent.mkdir()
        for source in ['{broken', '{"configurations":{}}', '{"configurations":[42]}']:
            self.path.write_text(source, encoding='utf-8')
            with self.assertRaises(ValueError):
                self.generate()
            self.assertEqual(self.path.read_text(encoding='utf-8'), source)
            self.assertFalse(Path(str(self.path) + '.bak').exists())

    def test_existing_file_without_configurations_gets_array(self):
        self.path.parent.mkdir()
        self.path.write_text('{"version":"0.2.1", "defaults":{"env":{}},}', encoding='utf-8')
        self.generate()
        self.assertIn('"cali"', self.path.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
