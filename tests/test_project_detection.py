"""Read-only project configuration discovery, independent of other profiles."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
from project_detection import detect_project_config
from server import Api
import core


class ProjectDetectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project'
        self.root.mkdir()
        (self.root / 'LiShuttle').mkdir()
        (self.root / 'LiShuttle/CMakeLists.txt').write_text('project ("lishuttle")\nadd_executable(${PROJECT_NAME} main.cpp)')
        self.data = {'version':3, 'configurePresets':[
            dict(name='windows-base', hidden=True, generator='Ninja',
                 condition=dict(type='equals', lhs='${hostSystemName}', rhs='Windows'),
                 binaryDir='${sourceDir}/out/build/${presetName}', installDir='${sourceDir}/out/install/${presetName}'),
            dict(name='x64-debug', inherits='windows-base', cacheVariables={'CMAKE_BUILD_TYPE':'Debug'}),
            dict(name='x64-release', inherits='x64-debug', cacheVariables={'CMAKE_BUILD_TYPE':'RelWithDebInfo'}),
            dict(name='linux-release', binaryDir='${sourceDir}/linux',
                 condition=dict(type='equals', lhs='${hostSystemName}', rhs='Linux'))]}
        self.write_presets()
        for relative in ('ThirdPart/Config/runtimelibrary', 'ThirdPart/Dll/Release', 'ThirdPart/Dll/Debug'):
            (self.root / relative).mkdir(parents=True)
        (self.root / 'ThirdPart/Config/runtimelibrary/runtimeschema.xml').write_text('<RuntimeSchema/>')
        exe = self.root / 'out/build/x64-release/Bin/lishuttle.exe'
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b'existing executable')
        self.env = dict(PROJECT_DIR=self.root.as_posix(), PROJECT_PROFILE_ID='project', PROJECT_PROFILE_REVISION='1')

    def write_presets(self):
        (self.root / 'CMakePresets.json').write_text(json.dumps(self.data), encoding='utf-8')

    def detect(self, values=None):
        return detect_project_config(dict(self.env, **(values or {})), machine={})

    def test_existing_release_executable_selects_inherited_windows_preset(self):
        result = self.detect()
        self.assertEqual(result['values']['PRESET'], 'x64-release')
        self.assertEqual(result['values']['BUILD_SUBDIR'], 'out/build/x64-release')
        self.assertEqual(result['values']['INSTALL_SUBDIR'], 'out/install/x64-release')
        self.assertEqual(result['values']['EXE_NAME'], 'lishuttle.exe')
        self.assertEqual(result['values']['CONFIG_SRC'], 'ThirdPart/Config')
        self.assertEqual(result['values']['DLL_SRC'], 'ThirdPart/Dll/Release')
        self.assertEqual(set(result['presets']), {'x64-debug','x64-release'})
        self.assertEqual(result['presets']['x64-debug']['values']['DLL_SRC'], 'ThirdPart/Dll/Debug')
        self.assertIn('CMakePresets.json', result['fields']['BUILD_SUBDIR']['source'])

    def test_saved_custom_values_and_business_paths_are_preserved(self):
        result = self.detect(dict(PRESET='x64-debug', BUILD_SUBDIR='custom/debug', OUT_ROOT='D:/chosen/results', CMAKE='D:/custom/cmake.exe'))
        self.assertEqual(result['values']['PRESET'], 'x64-debug')
        self.assertEqual(result['values']['BUILD_SUBDIR'], 'custom/debug')
        self.assertEqual(result['values']['OUT_ROOT'], 'D:/chosen/results')
        self.assertEqual(result['values']['CMAKE'], 'D:/custom/cmake.exe')
        self.assertEqual(result['fields']['OUT_ROOT']['status'], 'saved')

    def test_missing_tools_and_business_paths_are_explained_not_invented(self):
        result = self.detect()
        self.assertEqual(result['values']['CMAKE'], '')
        self.assertEqual(result['values']['OUT_ROOT'], '')
        self.assertTrue(result['fields']['OUT_ROOT']['source'])
        self.assertEqual(result['fields']['CMAKE']['status'], 'missing')

    def test_detects_existing_sibling_data_directories_without_profile_inheritance(self):
        (self.root.parent / 'map/city/heights').mkdir(parents=True)
        (self.root.parent / 'map/city/heights/index.txt').write_text('map')
        for name in ('gongcan','case','pathloss'):
            (self.root.parent / name).mkdir()
        result = self.detect()
        self.assertEqual(result['values']['MAP_ROOT'], (self.root.parent / 'map').as_posix())
        self.assertEqual(result['values']['GONGCAN_ROOT'], (self.root.parent / 'gongcan').as_posix())
        self.assertEqual(result['values']['OUT_ROOT'], (self.root.parent / 'pathloss').as_posix())
        self.assertFalse((self.root / 'outputs').exists())

    def test_user_presets_include_and_multiple_inheritance(self):
        extra = self.root / 'cmake'
        extra.mkdir()
        (extra / 'base.json').write_text(json.dumps({'version':4,'configurePresets':[
            dict(name='extra-base', hidden=True, cacheVariables={'CMAKE_BUILD_TYPE':'Debug'})]}))
        (self.root / 'CMakeUserPresets.json').write_text(json.dumps({'version':4, 'include':['cmake/base.json'],
            'configurePresets':[dict(name='local-debug', inherits=['extra-base','windows-base'])]}))
        result = self.detect()
        self.assertEqual(result['presets']['local-debug']['values']['BUILD_SUBDIR'], 'out/build/local-debug')
        self.assertEqual(result['presets']['local-debug']['values']['DLL_SRC'], 'ThirdPart/Dll/Debug')

    def test_external_binary_dir_is_reported_as_incompatible(self):
        self.data['configurePresets'].append(dict(name='external', inherits='windows-base', binaryDir=str(self.root.parent/'external')))
        self.write_presets()
        result = self.detect()
        self.assertNotIn('external', result['presets'])
        self.assertTrue(any('external' in warning for warning in result['warnings']))

    def test_cycles_and_unknown_macros_do_not_create_fake_candidates(self):
        self.data['configurePresets'] += [dict(name='cycle', inherits='cycle'),
            dict(name='unknown', inherits='windows-base', binaryDir='${unknown}/build')]
        self.write_presets()
        result = self.detect()
        self.assertNotIn('cycle', result['presets'])
        self.assertNotIn('unknown', result['presets'])
        self.assertTrue(result['warnings'])

    def test_detection_does_not_write_files_or_execute_cmake(self):
        before = {str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch('subprocess.run', side_effect=AssertionError('must not execute project tools')):
            self.detect()
        self.assertEqual(before, {str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_verified_machine_candidates_are_returned_for_dropdowns(self):
        vs = self.root.parent / 'VS'
        values = {'VS_ROOT':vs.as_posix()}
        for key, filename in [('CMAKE','cmake.exe'),('NINJA','ninja.exe'),('VCVARS','vcvars64.bat')]:
            path=vs/filename
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b'tool')
            values[key]=path.as_posix()
        machine={k:[v] for k,v in values.items()}
        machine['toolchains']={vs.as_posix():values}
        result=detect_project_config(self.env,machine=machine)
        for key,value in values.items():
            self.assertEqual(result['values'][key],value)
            self.assertIn(value,[c['value'] for c in result['fields'][key]['candidates']])

    def test_api_is_revision_guarded_and_does_not_save_detection_draft(self):
        with patch.object(core,'load_env',return_value=self.env), patch.object(core,'save_env_keys') as save:
            result=Api.detect_project_config({})
            self.assertIn('fields',result)
            save.assert_not_called()
            stale=Api.detect_project_config({'_project':'/other'})
            self.assertIn('error',stale)

    def test_invalid_preset_shape_is_explained_without_losing_resource_detection(self):
        (self.root / 'CMakePresets.json').write_text('[]')
        result = self.detect()
        self.assertTrue(result['warnings'])
        self.assertEqual(result['values']['CONFIG_SRC'], 'ThirdPart/Config')

    def test_executable_target_can_differ_from_cmake_project_name(self):
        (self.root / 'LiShuttle/CMakeLists.txt').write_text('project(tool_suite)\nadd_executable(lishuttle main.cpp)')
        result = self.detect()
        self.assertEqual(result['values']['EXE_NAME'], 'lishuttle.exe')
        self.assertTrue(result['presets']['x64-release']['built'])

    def test_debug_preset_does_not_auto_select_release_dll_when_debug_dll_missing(self):
        (self.root / 'ThirdPart/Dll/Debug').rmdir()
        result = self.detect({'PRESET':'x64-debug'})
        self.assertEqual(result['values']['DLL_SRC'], '')
        self.assertEqual(result['fields']['DLL_SRC']['status'], 'choice')

    def test_saved_vs_selects_its_tools_when_tool_fields_are_blank(self):
        machine = {'toolchains':{}}
        for name in ('VS1', 'VS2'):
            root = self.root.parent / name
            root.mkdir()
            values = {'VS_ROOT':root.as_posix()}
            for key in ('CMAKE', 'NINJA', 'VCVARS'):
                path = root / key
                path.write_text('tool')
                values[key] = path.as_posix()
            machine['toolchains'][root.as_posix()] = values
            for key,value in values.items():
                machine.setdefault(key, []).append(value)
        selected = (self.root.parent / 'VS2').as_posix()
        result = detect_project_config(dict(self.env, VS_ROOT=selected), machine=machine)
        self.assertEqual(result['values']['CMAKE'], selected + '/CMAKE')


if __name__=='__main__':
    unittest.main()
