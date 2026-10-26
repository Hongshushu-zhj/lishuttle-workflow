import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'platform/backend'))
from project_config import FIELDS, ProjectStore, validate_operation
from project_workflow import describe_build, prepare_build, required_issues, sync_executable
import core
from server import Api


class ProjectWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.project=self.root/'project'
        (self.project/'LiShuttle').mkdir(parents=True)
        (self.project/'CMakeLists.txt').write_text('project(suite)')
        (self.project/'LiShuttle/CMakeLists.txt').write_text('project(suite)\nadd_executable(myengine main.cpp)')
        presets={'version':3,'configurePresets':[
            {'name':'win-debug','generator':'Ninja','binaryDir':'${sourceDir}/out/build/${presetName}',
             'cacheVariables':{'CMAKE_BUILD_TYPE':'Debug'}},
            {'name':'win-release','generator':'Ninja','binaryDir':'${sourceDir}/out/build/${presetName}',
             'cacheVariables':{'CMAKE_BUILD_TYPE':'RelWithDebInfo'}}]}
        (self.project/'CMakePresets.json').write_text(json.dumps(presets))
        for path in ('ThirdPart/Dll/Debug','ThirdPart/Dll/Release','ThirdPart/Config/runtimelibrary'):
            (self.project/path).mkdir(parents=True)
        (self.project/'ThirdPart/Config/runtimelibrary/runtimeschema.xml').write_text('<RuntimeSchema/>')
        self.store=ProjectStore(self.root/'local-win.env')
        self.env=self.store.select(self.project)

    def test_cli_case_setting_is_removed_and_old_values_backed_up(self):
        self.assertNotIn('CASE_ROOT',FIELDS)
        data=json.loads(self.store.file.read_text())
        data['profiles'][data['active']]['values']['CASE_ROOT']='old/case'
        self.store.file.write_text(json.dumps(data))
        self.assertNotIn('CASE_ROOT',self.store.load())
        self.assertTrue(Path(str(self.store.file)+'.retired-fields.bak').is_file())

    def test_debug_release_plan_does_not_claim_nonexistent_build_directory(self):
        status=describe_build(self.env)
        self.assertEqual(set(status['modes']),{'debug','release'})
        release=status['presets']['win-release']
        self.assertFalse(release['directory_exists'])
        self.assertFalse(release['built'])
        values=prepare_build(self.env,'win-debug')
        self.assertEqual(values['BUILD_SUBDIR'],'out/build/win-debug')
        self.assertEqual(values['DLL_SRC'],'ThirdPart/Dll/Debug')
        self.assertEqual(values['EXE_NAME'],'myengine.exe')
        self.assertFalse((self.project/'out').exists())
        with self.assertRaises(ValueError):
            prepare_build(self.env,'../../outside')

    def test_compile_does_not_require_executable_before_first_build(self):
        env=dict(self.env,PRESET='win-debug',BUILD_SUBDIR='out/build/win-debug',CMAKE='cmake',NINJA='ninja',VCVARS='vcvars')
        validate_operation(env,'build')

    def test_required_field_issues_have_focus_targets_and_ignore_optional_items(self):
        issues=required_issues(self.env,'render')
        keys={i['key'] for i in issues}
        self.assertIn('OUT_ROOT',keys)
        self.assertNotIn('DT_ROOT',keys)
        self.assertNotIn('INSTALL_SUBDIR',keys)
        self.assertNotIn('CASE_ROOT',keys)
        self.assertTrue(all(i['target'] and i['section'] and i['message'] for i in issues))

    def test_actual_executable_is_refreshed_after_build_without_manual_name(self):
        values=prepare_build(self.env,'win-release')
        values['EXE_NAME']=''
        self.store.save(values)
        binary=self.project/values['BUILD_SUBDIR']/'Bin'
        binary.mkdir(parents=True)
        (binary/'myengine.exe').write_bytes(b'fixture, not executed')
        env=sync_executable(self.store)
        self.assertEqual(env['EXE_NAME'],'myengine.exe')
        self.assertTrue(describe_build(env)['built'])

    def test_status_refresh_uses_request_project_after_active_switch(self):
        values=prepare_build(self.env,'win-release')
        self.store.save(values)
        pinned=self.store.load()
        other=self.root/'other'
        other.mkdir()
        self.store.select(other)
        with patch.object(core,'ENV_FILE',str(self.store.env_file)),patch.object(core,'load_env',return_value=pinned):
            response=Api.build_status({})
        self.assertNotIn('error',response)
        self.assertEqual(response['build_values']['PRESET'],'win-release')

    def test_compile_api_pins_selected_mode_and_does_not_require_output_data(self):
        tools={}
        for key in ('CMAKE','NINJA','VCVARS'):
            path=self.root/key
            path.write_text('tool fixture, not executed')
            tools[key]=path.as_posix()
        self.store.save_machine(tools)
        with patch.object(core,'ENV_FILE',str(self.store.env_file)),patch.object(core,'start_toolkit',return_value=(9,'build.bat')):
            response=Api.toolkit({'step':'build','preset':'win-debug'})
            self.assertNotIn('error',response)
            self.assertEqual(response['build_values']['PRESET'],'win-debug')
            self.assertEqual(self.store.load()['BUILD_SUBDIR'],'out/build/win-debug')
            self.assertEqual(self.store.load()['OUT_ROOT'],'')


if __name__=='__main__': unittest.main()
