"""Exercise root selection through real API/config boundaries using fake engines."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'platform/backend')]
import core
from project_config import ProjectStore
from run_guard import RuntimeGuard
from server import Api


class BuildTargetApiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / 'engine'
        (self.project / 'LiShuttle').mkdir(parents=True)
        (self.project / 'CMakeLists.txt').write_text('project(fixture)')
        (self.project / 'LiShuttle/CMakeLists.txt').write_text('add_executable(lishuttle main.cpp)')
        presets = []
        for mode in ('Debug', 'Release'):
            name = mode.lower()
            presets.append(dict(name=name, generator='Ninja', binaryDir='${sourceDir}/build/' + name,
                                cacheVariables={'CMAKE_BUILD_TYPE': mode}))
            binary = self.project / 'build' / name / 'Bin'
            binary.mkdir(parents=True)
            (binary / 'lishuttle.exe').write_bytes(b'fixture only, never executed')
            source = self.project / 'ThirdPart/Dll' / mode
            source.mkdir(parents=True)
            (source / 'dependency.dll').write_bytes(mode.encode())
        (self.project / 'CMakePresets.json').write_text(json.dumps(dict(version=3, configurePresets=presets)))
        self.store = ProjectStore(self.root / 'local-win.env')
        self.store.select(self.project)
        self.store.save(dict(PRESET='release', BUILD_SUBDIR='build/release', EXE_NAME='lishuttle.exe',
                             DLL_ROOT='ThirdPart/Dll'))
        self.guard = RuntimeGuard()
        for item in (patch.object(core, 'ENV_FILE', str(self.store.env_file)),
                     patch.object(core, 'RUNTIME', self.guard)):
            item.start()
            self.addCleanup(item.stop)

    def payload(self, **values):
        env = self.store.load(read_only=True)
        return dict(_project=env['PROJECT_DIR'], _revision=env['PROJECT_PROFILE_REVISION'], **values)

    def test_preview_resolves_debug_without_saving_the_release_selection(self):
        before = self.store.file.read_bytes()
        result = Api.preview_build_target(self.payload(preset='debug', values={'DLL_ROOT': 'ThirdPart/Dll'}))
        self.assertEqual(result['build_values']['DLL_SRC'], 'ThirdPart/Dll/Debug')
        self.assertEqual(self.store.file.read_bytes(), before)

    def test_apply_existing_persists_root_preset_and_resolved_source_together(self):
        result = Api.apply_build_target(self.payload(preset='debug', values={'DLL_ROOT': 'ThirdPart/Dll'}))
        self.assertNotIn('error', result)
        env = self.store.load(read_only=True)
        self.assertEqual((env['PRESET'], env['BUILD_SUBDIR'], env['DLL_SRC']),
                         ('debug', 'build/debug', 'ThirdPart/Dll/Debug'))

    def test_sync_only_changes_dlls_and_rejects_a_stale_difference(self):
        binary = self.project / 'build/release/Bin'
        config = binary / 'runtimelibrary/job.xml'
        config.parent.mkdir()
        config.write_bytes(b'edited runtime XML\r\n')
        stamp = config.stat().st_mtime_ns
        comparison = Api.dll_status(self.payload())
        self.assertEqual(comparison['counts']['missing'], 1)
        result = Api.dll_sync(self.payload(revision=comparison['revision']))
        self.assertNotIn('error', result)
        self.assertEqual((binary / 'dependency.dll').read_bytes(), b'Release')
        self.assertEqual(config.read_bytes(), b'edited runtime XML\r\n')
        self.assertEqual(config.stat().st_mtime_ns, stamp)
        (binary / 'dependency.dll').write_bytes(b'user update')
        stale = Api.dll_sync(self.payload(revision=comparison['revision']))
        self.assertIn('error', stale)
        self.assertEqual((binary / 'dependency.dll').read_bytes(), b'user update')

    def test_old_project_revision_cannot_apply_a_new_target(self):
        payload = self.payload(preset='debug')
        self.store.save({'OUT_ROOT': str(self.root / 'outputs')})
        response = Api.apply_build_target(payload)
        self.assertIn('error', response)
        self.assertEqual(self.store.load(read_only=True)['PRESET'], 'release')


if __name__ == '__main__':
    unittest.main()
