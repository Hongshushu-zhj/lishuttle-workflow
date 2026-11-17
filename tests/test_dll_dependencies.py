import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'platform/backend'))
from project_config import ProjectStore
from project_workflow import prepare_build
from dll_dependencies import resolve_dll, compare_dlls, sync_dlls
from run_guard import RuntimeGuard, RuntimeBusy


class DllTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / 'engine'
        self.project.mkdir()
        presets = [{'name': name, 'generator': 'Ninja', 'binaryDir': '${sourceDir}/out/' + name,
                    'cacheVariables': {'CMAKE_BUILD_TYPE': kind}}
                   for name, kind in [('debug', 'Debug'), ('release', 'Release'), ('info', 'RelWithDebInfo'), ('small', 'MinSizeRel')]]
        (self.project / 'CMakePresets.json').write_text(json.dumps({'version': 3, 'configurePresets': presets}))
        self.store = ProjectStore(self.root / 'local.env')
        self.env = self.store.select(self.project)
        for mode in ('Debug', 'Release'):
            (self.project / 'ThirdPart/Dll' / mode).mkdir(parents=True)
        self.env = self.store.save(dict(PRESET='release', BUILD_SUBDIR='out/release', DLL_ROOT='ThirdPart/Dll'))

    def test_root_and_build_type_share_one_resolver_including_release_variants(self):
        for preset, mode in [('debug', 'Debug'), ('release', 'Release'), ('info', 'Release'), ('small', 'Release')]:
            values = prepare_build(self.env, preset)
            self.assertEqual(values['DLL_ROOT'], 'ThirdPart/Dll')
            self.assertEqual(values['DLL_SRC'], 'ThirdPart/Dll/' + mode)
        custom = self.root / '外部 DLL'
        (custom / 'Debug').mkdir(parents=True)
        values = prepare_build(self.env, 'debug', {'DLL_ROOT': str(custom)})
        self.assertEqual(values['DLL_SRC'], custom.as_posix() + '/Debug')
        self.assertTrue(resolve_dll(dict(self.env, **values))['exists'])

    def test_legacy_paths_migrate_with_slashes_case_relative_and_absolute(self):
        for legacy, expected in [('ThirdPart\\Dll\\..\\Dll\\dEbUg\\', 'ThirdPart/Dll'),
                                 (str(self.root / 'custom') + '\\RELEASE\\', (self.root / 'custom').as_posix())]:
            saved = self.store.save({'DLL_ROOT': '', 'DLL_SRC': legacy})
            self.assertEqual(saved['DLL_ROOT'], expected)
            self.assertEqual(saved['DLL_SRC'], expected + '/Release')
        self.assertEqual(self.store.load()['DLL_ROOT'], (self.root / 'custom').as_posix())

    def test_old_profiles_migrate_on_read_and_preserve_custom_leaf(self):
        data = json.loads(self.store.file.read_text())
        values = data['profiles'][data['active']]['values']
        values.pop('DLL_ROOT')
        values['DLL_SRC'] = '../external/Debug'
        self.store.file.write_text(json.dumps(data))
        migrated = self.store.load()
        self.assertEqual(migrated['DLL_ROOT'], '../external')
        self.assertEqual(migrated['DLL_SRC'], '../external/Release')
        saved = self.store.save({'DLL_ROOT': '', 'DLL_SRC': '../vendor/bin64'})
        self.assertEqual(saved['DLL_SRC'], '../vendor/bin64')
        self.assertTrue(resolve_dll(saved)['compatibility'])
        self.assertEqual(prepare_build(saved, 'debug')['DLL_SRC'], '../vendor/bin64')

    def test_read_only_legacy_migration_never_changes_store_or_creates_backup(self):
        data = json.loads(self.store.file.read_text())
        values = data['profiles'][data['active']]['values']
        values.pop('DLL_ROOT')
        values['DLL_SRC'] = 'ThirdPart/Dll/Debug'
        self.store.file.write_text(json.dumps(data))
        original = self.store.file.read_bytes()
        before = {str(path) for path in self.root.rglob('*')}
        loaded = self.store.load(read_only=True)
        self.assertEqual(loaded['DLL_ROOT'], 'ThirdPart/Dll')
        self.assertEqual(loaded['DLL_SRC'], 'ThirdPart/Dll/Release')
        self.assertEqual(self.store.file.read_bytes(), original)
        self.assertEqual({str(path) for path in self.root.rglob('*')}, before)

    def test_missing_preset_migration_is_stable_across_repeated_loads(self):
        data = json.loads(self.store.file.read_text())
        values = data['profiles'][data['active']]['values']
        values.pop('DLL_ROOT')
        values.update(PRESET='', DLL_SRC='ThirdPart/Dll/Debug')
        self.store.file.write_text(json.dumps(data))
        first = self.store.load()
        persisted = self.store.file.read_bytes()
        for _ in range(3):
            current = self.store.load()
            self.assertEqual(current['PROJECT_PROFILE_REVISION'], first['PROJECT_PROFILE_REVISION'])
            self.assertEqual(self.store.file.read_bytes(), persisted)

    def test_custom_relative_root_and_windows_drive_root_normalization(self):
        custom = self.project / 'vendor/版本 DLL'
        (custom / 'Release').mkdir(parents=True)
        saved = self.store.save({'DLL_ROOT': '', 'DLL_SRC': 'vendor\\版本 DLL\\Release\\'})
        self.assertEqual(saved['DLL_ROOT'], 'vendor/版本 DLL')
        self.assertEqual(saved['DLL_SRC'], 'vendor/版本 DLL/Release')
        self.assertEqual(resolve_dll(dict(saved, DLL_ROOT='Z:/', DLL_SRC=''), 'Debug')['source'], 'Z:/Debug')

    def test_single_mode_leaf_migrates_to_project_root_and_follows_preset(self):
        (self.project / 'Release').mkdir()
        for legacy in ('Debug', './Debug/', 'RELEASE\\'):
            saved = self.store.save({'DLL_ROOT': '', 'DLL_SRC': legacy})
            self.assertEqual(saved['DLL_ROOT'], '.')
            self.assertEqual(saved['DLL_SRC'], 'Release')
            self.assertFalse(resolve_dll(saved)['compatibility'])
            self.assertEqual(prepare_build(saved, 'debug')['DLL_SRC'], 'Debug')

    def test_missing_mode_never_falls_back_to_other_directory(self):
        root = self.root / 'release-only'
        (root / 'Release').mkdir(parents=True)
        values = prepare_build(self.env, 'debug', {'DLL_ROOT': str(root)})
        resolved = resolve_dll(dict(self.env, **values))
        self.assertFalse(resolved['exists'])
        self.assertEqual(resolved['source'], root.as_posix() + '/Debug')
        self.assertIn('Debug', resolved['message'])

    def test_root_is_restored_per_project_and_draft_does_not_persist_implicitly(self):
        prepared = prepare_build(self.env, 'debug', {'DLL_ROOT': '../custom'})
        self.assertEqual(prepared['DLL_ROOT'], '../custom')
        self.assertEqual(self.store.load()['DLL_ROOT'], 'ThirdPart/Dll')
        other = self.root / 'other'
        other.mkdir()
        self.store.select(other)
        self.store.save({'DLL_ROOT': '../other-vendor'})
        self.assertEqual(self.store.select(self.project)['DLL_ROOT'], 'ThirdPart/Dll')

    def fixture_sync(self):
        source = self.project / 'ThirdPart/Dll/Release'
        binary = self.project / 'out/release/Bin'
        binary.mkdir(parents=True)
        (binary / 'engine.exe').write_bytes(b'fixture executable, never executed')
        for name, value in [('same.dll', b'same'), ('different.DLL', b'new'), ('missing.dll', b'new missing'),
                            ('config.xml', b'new XML'), ('model.dat', b'new model')]:
            (source / name).write_bytes(value)
        for name, value in [('same.dll', b'same'), ('different.DLL', b'old'), ('unknown.dll', b'keep'),
                            ('config.xml', b'old XML'), ('model.dat', b'old model')]:
            (binary / name).write_bytes(value)
        return source, binary

    def test_diff_is_read_only_and_explicit_sync_only_updates_dll_with_backup(self):
        source, binary = self.fixture_sync()
        before = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob('*'))
        diff = compare_dlls(self.env)
        self.assertEqual(diff['counts'], {'same': 1, 'different': 1, 'missing': 1})
        self.assertEqual(before, sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob('*')))
        runtime = RuntimeGuard()
        result = sync_dlls(self.env, runtime, {'bin_dir': str(binary)}, diff['revision'])
        self.assertEqual(result['updated'], 2)
        self.assertEqual((binary / 'different.DLL').read_bytes(), b'new')
        self.assertEqual((binary / 'different.DLL.bak').read_bytes(), b'old')
        self.assertEqual((binary / 'missing.dll').read_bytes(), b'new missing')
        self.assertEqual((binary / 'config.xml').read_bytes(), b'old XML')
        self.assertEqual((binary / 'model.dat').read_bytes(), b'old model')
        self.assertEqual((binary / 'unknown.dll').read_bytes(), b'keep')
        self.assertEqual(compare_dlls(self.env)['counts']['same'], 3)

    def test_sync_rolls_back_partial_failure_and_respects_runtime_lock(self):
        _, binary = self.fixture_sync()
        runtime = RuntimeGuard()
        from file_safety import FileTransaction
        original = FileTransaction.copy
        calls = []
        def failed_copy(transaction, source, destination, **kwargs):
            calls.append(destination)
            if len(calls) == 2:
                raise OSError('fixture interruption')
            return original(transaction, source, destination, **kwargs)
        with patch.object(FileTransaction, 'copy', failed_copy), self.assertRaises(OSError):
            sync_dlls(self.env, runtime, {'bin_dir': str(binary)})
        self.assertEqual((binary / 'different.DLL').read_bytes(), b'old')
        self.assertFalse((binary / 'missing.dll').exists())
        self.assertFalse((binary / 'different.DLL.bak').exists())
        with runtime.operation('fixture busy') as token:
            runtime.bind(token, 1)
        with self.assertRaises(RuntimeBusy):
            sync_dlls(self.env, runtime, {'bin_dir': str(binary)})
        runtime.release(token)

    def test_stale_diff_rejected_before_replacement(self):
        source, binary = self.fixture_sync()
        diff = compare_dlls(self.env)
        (source / 'missing.dll').write_bytes(b'changed after preview')
        with self.assertRaisesRegex(ValueError, '变化'):
            sync_dlls(self.env, RuntimeGuard(), {'bin_dir': str(binary)}, diff['revision'])
        self.assertEqual((binary / 'different.DLL').read_bytes(), b'old')

    def test_sync_rejects_backup_directory_links_before_touching_bin(self):
        _, binary = self.fixture_sync()
        import dll_dependencies
        original = dll_dependencies._is_link
        with patch.object(dll_dependencies, '_is_link', side_effect=lambda path:
                          path == binary / '.lishuttle-history' or original(path)):
            with self.assertRaisesRegex(ValueError, '链接'):
                sync_dlls(self.env, RuntimeGuard(), {'bin_dir': str(binary)})
        self.assertEqual((binary / 'different.DLL').read_bytes(), b'old')
        self.assertFalse((binary / 'different.DLL.bak').exists())

    def test_cross_process_resource_owner_blocks_sync_before_mutation(self):
        _, binary = self.fixture_sync()
        owner, contender = RuntimeGuard(), RuntimeGuard()
        with owner.operation('fixture owner') as token:
            owner.acquire_resources(token, {'bin_dir': str(binary)})
            with self.assertRaises(RuntimeBusy):
                sync_dlls(self.env, contender, {'bin_dir': str(binary)})
        self.assertEqual((binary / 'different.DLL').read_bytes(), b'old')

    def test_external_edit_during_copy_survives_while_earlier_replacements_roll_back(self):
        source, binary = self.fixture_sync()
        import file_safety
        prepare = file_safety._prepare_copy
        def external_edit(destination, original):
            result = prepare(destination, original)
            if Path(destination) == binary / 'missing.dll':
                (binary / 'missing.dll').write_bytes(b'external edit')
            return result
        with patch.object(file_safety, '_prepare_copy', external_edit), self.assertRaises(file_safety.FileConflict):
            sync_dlls(self.env, RuntimeGuard(), {'bin_dir': str(binary)})
        self.assertEqual((binary / 'different.DLL').read_bytes(), b'old')
        self.assertEqual((binary / 'missing.dll').read_bytes(), b'external edit')

    def test_source_changes_during_copy_restore_target_instead_of_retaining_unapproved_bytes(self):
        source, binary = self.fixture_sync()
        import file_safety
        prepare = file_safety._prepare_copy
        def mutate_live_source(destination, original):
            if Path(destination) == binary / 'different.DLL':
                (source / 'different.DLL').write_bytes(b'unapproved source mutation')
            return prepare(destination, original)
        with patch.object(file_safety, '_prepare_copy', mutate_live_source), self.assertRaises(ValueError):
            sync_dlls(self.env, RuntimeGuard(), {'bin_dir': str(binary)})
        self.assertEqual((binary / 'different.DLL').read_bytes(), b'old')
        self.assertFalse((binary / 'missing.dll').exists())
        self.assertFalse((binary / 'different.DLL.bak').exists())

    def test_target_edit_during_source_snapshot_is_never_adopted_and_overwritten(self):
        source, binary = self.fixture_sync()
        import dll_dependencies
        from file_safety import FileConflict
        copy = dll_dependencies.shutil.copy2
        def edit_target_while_snapshotting(original, destination, *args, **kwargs):
            result = copy(original, destination, *args, **kwargs)
            if Path(original) == source / 'missing.dll':
                (binary / 'missing.dll').write_bytes(b'external during snapshot')
            return result
        with patch.object(dll_dependencies.shutil, 'copy2', edit_target_while_snapshotting), self.assertRaises(FileConflict):
            sync_dlls(self.env, RuntimeGuard(), {'bin_dir': str(binary)})
        self.assertEqual((binary / 'missing.dll').read_bytes(), b'external during snapshot')
        self.assertEqual((binary / 'different.DLL').read_bytes(), b'old')
        self.assertFalse((binary / 'missing.dll.bak').exists())

    def test_external_edit_to_already_updated_dll_is_preserved_on_later_failure(self):
        _, binary = self.fixture_sync()
        from file_safety import FileTransaction, FileConflict
        original = FileTransaction.copy
        calls = []
        def external_edit(transaction, source, destination, **kwargs):
            calls.append(destination)
            if len(calls) == 2:
                (binary / 'different.DLL').write_bytes(b'external newer edit')
                raise OSError('fixture later failure')
            return original(transaction, source, destination, **kwargs)
        with patch.object(FileTransaction, 'copy', external_edit), self.assertRaises(FileConflict) as raised:
            sync_dlls(self.env, RuntimeGuard(), {'bin_dir': str(binary)})
        self.assertEqual((binary / 'different.DLL').read_bytes(), b'external newer edit')
        self.assertTrue(raised.exception.recovery_dir)
        # The retained original snapshot is deliberate recovery evidence.
        import shutil
        shutil.rmtree(raised.exception.recovery_dir)

    def test_empty_sources_missing_program_and_overlapping_directories_are_actionable(self):
        source, binary = self.fixture_sync()
        empty = self.root / 'empty'
        empty.mkdir()
        with self.assertRaisesRegex(ValueError, '没有 DLL'):
            compare_dlls(dict(self.env, DLL_ROOT='', DLL_SRC=str(empty)))
        with self.assertRaisesRegex(ValueError, '互相包含'):
            compare_dlls(dict(self.env, DLL_ROOT='', DLL_SRC=str(binary.parent)))
        (binary / 'engine.exe').unlink()
        with self.assertRaisesRegex(ValueError, '没有程序'):
            compare_dlls(self.env)


if __name__ == '__main__':
    unittest.main()
