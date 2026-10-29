"""Machine tools are shared, while projects and running snapshots stay isolated."""
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
from project_config import ProjectStore, project_id, write_snapshot, load_local
import core
from server import Api


class MachineConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ProjectStore(self.root / 'local-win.env')
        self.a, self.b = self.root / 'A', self.root / 'B'
        self.a.mkdir()
        self.b.mkdir()
        self.tools = {}
        for key, filename in [('VS_ROOT','vs'),('CMAKE','cmake.exe'),('NINJA','ninja.exe'),('VCVARS','vcvars64.bat')]:
            path = self.root / filename
            path.mkdir() if key == 'VS_ROOT' else path.write_text('installed tool')
            self.tools[key] = path.as_posix()

    def test_tools_saved_once_are_shared_but_project_settings_are_not(self):
        self.store.select(self.a)
        self.store.save(dict(self.tools, PRESET='A', OUT_ROOT='A/output'))
        b = self.store.select(self.b)
        for key,value in self.tools.items():
            self.assertEqual(b[key], value)
        self.assertEqual(b['PRESET'], '')
        self.assertEqual(b['OUT_ROOT'], '')
        data = json.loads(self.store.file.read_text())
        self.assertEqual(data['machine']['values'], self.tools)
        for profile in data['profiles'].values():
            self.assertFalse(set(self.tools) & set(profile['values']))

    def test_migration_uses_active_profile_and_preserves_original_backup(self):
        a, b = self.store._blank(self.a), self.store._blank(self.b)
        a['values'].update(self.tools)
        b['values'].update({key:'other-machine' for key in self.tools})
        old = dict(version=1,active=project_id(self.a),profiles={project_id(self.a):a,project_id(self.b):b})
        self.store.file.write_text(json.dumps(old))
        self.assertEqual(self.store.load()['CMAKE'], self.tools['CMAKE'])
        self.assertEqual(self.store.select(self.b)['CMAKE'], self.tools['CMAKE'])
        self.assertEqual(json.loads(Path(str(self.store.file)+'.machine.bak').read_text()), old)

    def test_machine_change_invalidates_all_projects_and_preserves_running_snapshot(self):
        self.store.select(self.a)
        self.store.save(self.tools)
        a = self.store.load()
        snapshot = write_snapshot(a, self.root / 'snapshots')
        self.store.select(self.b)
        self.store.save({'CMAKE':'custom/cmake.exe'})
        with self.assertRaisesRegex(ValueError,'变化'):
            self.store.save({'PRESET':'stale'},a['PROJECT_PROFILE_REVISION'],project=self.a)
        self.assertEqual(load_local(snapshot=snapshot)['CMAKE'], self.tools['CMAKE'])
        self.assertEqual(self.store.load(self.a)['CMAKE'],'custom/cmake.exe')

    def test_verified_detection_persists_tools_without_project_and_preserves_manual_choice(self):
        machine = {key:[value] for key,value in self.tools.items()}
        machine['toolchains']={self.tools['VS_ROOT']:self.tools}
        result = self.store.setup_machine(machine=machine)
        self.assertEqual(result['values'],self.tools)
        self.assertEqual(self.store.load(allow_empty=True)['CMAKE'],self.tools['CMAKE'])
        self.store.save_machine({'CMAKE':'custom/cmake.exe'})
        self.store.setup_machine(machine=machine)
        self.assertEqual(self.store.load(allow_empty=True)['CMAKE'],'custom/cmake.exe')

    def test_missing_tools_are_not_fabricated_and_noop_detection_keeps_revision(self):
        a = self.store.select(self.a)
        result = self.store.setup_machine(machine={'CMAKE':[str(self.root/'absent.exe')]})
        self.assertEqual(result['values']['CMAKE'],'')
        self.assertEqual(self.store.load()['PROJECT_PROFILE_REVISION'],a['PROJECT_PROFILE_REVISION'])

    def test_no_rescan_of_complete_toolchain_on_project_switch(self):
        self.store.save_machine(self.tools)
        with patch('project_detection.machine_tools', side_effect=AssertionError('should reuse configured tools')):
            self.store.setup_machine()
            self.store.select(self.a)
            self.store.select(self.b)
            self.store.setup_machine()

    def test_web_startup_persists_machine_tools_before_project_is_added(self):
        machine = {key:[value] for key,value in self.tools.items()}
        machine['toolchains']={self.tools['VS_ROOT']:self.tools}
        with patch.object(core, 'ENV_FILE', str(self.store.env_file)), \
                patch.object(core, 'PROJECTS_FILE', str(self.root/'projects.json')), \
                patch('project_detection.machine_tools', return_value=machine):
            state = Api.state({})
            self.assertEqual(state['machine_config'],self.tools)
            self.assertEqual(state['project'],'')
            self.assertEqual(self.store.load(allow_empty=True)['CMAKE'],self.tools['CMAKE'])
            changed = Api.save_machine_config({'values':{'CMAKE':'chosen/cmake.exe'}})
            self.assertEqual(changed['machine_config']['CMAKE'],'chosen/cmake.exe')
            rejected = Api.save_machine_config({'values':{'PRESET':'bad'}})
            self.assertIn('error',rejected)

    def test_cli_machine_configuration_does_not_require_an_engine_project(self):
        script_dir = self.root / 'scripts'
        script_dir.mkdir()
        source = Path(__file__).resolve().parents[1] / 'scripts/project_config.py'
        script = script_dir / 'project_config.py'
        script.write_bytes(source.read_bytes())
        result = subprocess.run([sys.executable,str(script),'--set-machine','CMAKE='+self.tools['CMAKE']],
                                capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['values']['CMAKE'],self.tools['CMAKE'])
        self.assertEqual(json.loads((self.root/'env/project-profiles.json').read_text())['active'],'')

    def test_machine_revision_guards_tabs_without_a_selected_project(self):
        initial = self.store.load(allow_empty=True)
        self.store.save_machine({'CMAKE':'chosen/cmake.exe'}, initial['MACHINE_CONFIG_REVISION'])
        before = self.store.file.read_bytes()
        with self.assertRaisesRegex(ValueError,'变化'):
            self.store.save_machine({'NINJA':'stale/ninja.exe'}, initial['MACHINE_CONFIG_REVISION'])
        self.assertEqual(before,self.store.file.read_bytes())

    def test_legacy_machine_values_import_without_a_project_directory(self):
        legacy = 'PROJECT_DIR=""\nCMAKE="chosen/cmake.exe"\nVCVARS="chosen/vcvars64.bat"\n'
        self.store.env_file.write_text(legacy)
        loaded = self.store.load(allow_empty=True)
        self.assertEqual(loaded['CMAKE'],'chosen/cmake.exe')
        self.assertEqual(loaded['VCVARS'],'chosen/vcvars64.bat')
        self.assertEqual(Path(str(self.store.env_file)+'.profiles.bak').read_text(),legacy)

    def test_windows_vs_path_matching_ignores_case_and_slash_style(self):
        other = self.root / 'OtherVS'
        other.mkdir()
        tools = {'VS_ROOT':other.as_posix()}
        for key in ('CMAKE','NINJA','VCVARS'):
            path = other / key
            path.write_text('tool')
            tools[key]=path.as_posix()
        machine={key:[self.tools[key],tools[key]] for key in tools}
        machine['toolchains']={self.tools['VS_ROOT']:self.tools,tools['VS_ROOT']:tools}
        selected = tools['VS_ROOT'].lower().replace('/','\\')
        self.store.save_machine({'VS_ROOT':selected})
        result = self.store.setup_machine(machine=machine)
        self.assertEqual(result['values']['VS_ROOT'],selected)
        self.assertEqual(result['values']['CMAKE'],tools['CMAKE'])


if __name__ == '__main__':
    unittest.main()
