import hashlib
import importlib
import inspect
from pathlib import Path
import os
import stat
import sys
import tempfile
import unittest
import warnings
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))


class FileSafetyTests(unittest.TestCase):
    def setUp(self):
        try:
            self.safety = importlib.import_module('file_safety')
        except ModuleNotFoundError:
            self.fail('file_safety API is not implemented')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'config.xml'
        self.target.write_bytes(b'original')

    def test_revision_identifies_content_and_missing_file(self):
        self.assertEqual(self.safety.file_revision(self.target), hashlib.sha256(b'original').hexdigest())
        self.assertEqual(self.safety.file_revision(self.root / 'absent'), 'missing')

    def test_repeated_backup_saves_keep_each_previous_version(self):
        revision = self.safety.atomic_write(self.target, b'second', backup=True)
        self.assertEqual(revision, hashlib.sha256(b'second').hexdigest())
        self.safety.atomic_write(self.target, b'third', backup=True)
        self.assertEqual(self.target.read_bytes(), b'third')
        self.assertEqual(self.target.with_suffix('.xml.bak').read_bytes(), b'second')
        versions = list((self.root / '.lishuttle-history').iterdir())
        self.assertEqual(len(versions), 2)
        self.assertEqual({p.read_bytes() for p in versions}, {b'original', b'second'})

    def test_temporary_write_error_preserves_original_and_existing_backup(self):
        backup = self.target.with_suffix('.xml.bak')
        backup.write_bytes(b'previous backup')
        with patch.object(self.safety.os, 'fsync', side_effect=OSError('temporary write failed')):
            with self.assertRaisesRegex(OSError, 'temporary write failed'):
                self.safety.atomic_write(self.target, b'replacement', backup=True)
        self.assertEqual(self.target.read_bytes(), b'original')
        self.assertEqual(backup.read_bytes(), b'previous backup')
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_target_replace_error_preserves_original_and_existing_backup(self):
        backup = self.target.with_suffix('.xml.bak')
        backup.write_bytes(b'previous backup')
        with patch.object(self.safety.os, 'replace', side_effect=OSError('replace failed')):
            with self.assertRaisesRegex(OSError, 'replace failed'):
                self.safety.atomic_write(self.target, b'replacement', backup=True)
        self.assertEqual(self.target.read_bytes(), b'original')
        self.assertEqual(backup.read_bytes(), b'previous backup')
        self.assertFalse(any((self.root / '.lishuttle-history').glob('*')))

    def test_backup_replace_error_rolls_back_target_and_preserves_history(self):
        self.safety.atomic_write(self.target, b'second', backup=True)
        backup = self.target.with_suffix('.xml.bak')
        versions = {p.name: p.read_bytes() for p in (self.root / '.lishuttle-history').iterdir()}
        real_replace = self.safety.os.replace

        def replace(source, destination):
            if Path(destination) == backup:
                raise OSError('backup replace failed')
            return real_replace(source, destination)

        with patch.object(self.safety.os, 'replace', side_effect=replace):
            with self.assertRaisesRegex(OSError, 'backup replace failed'):
                self.safety.atomic_write(self.target, b'third', backup=True)
        self.assertEqual(self.target.read_bytes(), b'second')
        self.assertEqual(backup.read_bytes(), b'original')
        self.assertEqual({p.name: p.read_bytes() for p in (self.root / '.lishuttle-history').iterdir()}, versions)

    def test_expected_revision_conflict_does_not_write_or_back_up(self):
        with self.assertRaises(self.safety.FileConflict):
            self.safety.atomic_write(self.target, b'new', backup=True, expected_revision='stale')
        self.assertEqual(self.target.read_bytes(), b'original')
        self.assertFalse(self.target.with_suffix('.xml.bak').exists())

    def test_revision_is_checked_again_after_preparing_temporary_file(self):
        expected = self.safety.file_revision(self.target)
        real_fsync = self.safety.os.fsync

        def external_edit(fd):
            result = real_fsync(fd)
            self.target.write_bytes(b'external edit')
            return result

        with patch.object(self.safety.os, 'fsync', side_effect=external_edit):
            with self.assertRaises(self.safety.FileConflict):
                self.safety.atomic_write(self.target, b'new', backup=True, expected_revision=expected)
        self.assertEqual(self.target.read_bytes(), b'external edit')
        self.assertFalse(self.target.with_suffix('.xml.bak').exists())

    def test_revision_is_checked_immediately_before_commit_after_snapshotting(self):
        expected = self.safety.file_revision(self.target)
        real_copy = self.safety.shutil.copy2

        def external_edit(source, destination, *args, **kwargs):
            result = real_copy(source, destination, *args, **kwargs)
            if Path(source) == self.target:
                self.target.write_bytes(b'edit during snapshot')
            return result

        with patch.object(self.safety.shutil, 'copy2', side_effect=external_edit):
            with self.assertRaises(self.safety.FileConflict):
                self.safety.atomic_write(self.target, b'new', expected_revision=expected)
        self.assertEqual(self.target.read_bytes(), b'edit during snapshot')

    def test_outer_write_conflict_preserves_edit_during_outer_snapshot(self):
        self._assert_outer_snapshot_conflict_preserves_external(copy=False)

    def test_outer_copy_conflict_preserves_edit_during_outer_snapshot(self):
        self._assert_outer_snapshot_conflict_preserves_external(copy=True)

    def _assert_outer_snapshot_conflict_preserves_external(self, copy):
        source = self.root / 'replacement.dat'
        source.write_bytes(b'new resource')
        real_copy = self.safety.shutil.copy2
        snapshots = 0

        def external_edit(src, dst, *args, **kwargs):
            nonlocal snapshots
            result = real_copy(src, dst, *args, **kwargs)
            if Path(src) == self.target and Path(dst).suffix == '.snapshot':
                snapshots += 1
                if snapshots == 2:
                    self.target.write_bytes(b'external edit during outer snapshot')
            return result

        with patch.object(self.safety.shutil, 'copy2', side_effect=external_edit):
            with self.assertRaises(self.safety.FileConflict):
                with self.safety.FileTransaction() as transaction:
                    if copy:
                        transaction.copy(source, self.target, backup=True)
                    else:
                        transaction.write(self.target, b'new', backup=True)
        self.assertEqual(self.target.read_bytes(), b'external edit during outer snapshot')
        self.assertFalse(Path(str(self.target) + '.bak').exists())
        self.assertFalse(any((self.root / '.lishuttle-history').glob('*')))

    def test_later_write_conflict_preserves_external_edit_and_prior_recovery(self):
        real_copy = self.safety.shutil.copy2

        def external_edit(src, dst, *args, **kwargs):
            result = real_copy(src, dst, *args, **kwargs)
            if Path(src) == self.target and Path(dst).suffix == '.snapshot':
                self.target.write_bytes(b'external edit after earlier write')
            return result

        with self.assertRaises(self.safety.FileConflict) as caught:
            with self.safety.FileTransaction() as transaction:
                transaction.write(self.target, b'first write')
                with patch.object(self.safety.shutil, 'copy2', side_effect=external_edit):
                    transaction.write(self.target, b'second write')
        self.assertEqual(self.target.read_bytes(), b'external edit after earlier write')
        self.assertTrue(Path(caught.exception.recovery_dir).is_dir())
        self.assertIn(caught.exception.recovery_dir, str(caught.exception))
        self.assertTrue(any(p.read_bytes() == b'original'
                            for p in Path(caught.exception.recovery_dir).glob('*.snapshot')))
        self.safety.shutil.rmtree(caught.exception.recovery_dir)

    def test_early_revision_conflict_after_prior_write_preserves_external_edit(self):
        with self.assertRaises(self.safety.FileConflict) as caught:
            with self.safety.FileTransaction() as transaction:
                revision = transaction.write(self.target, b'first write')
                self.target.write_bytes(b'external edit before next write')
                transaction.write(self.target, b'second write', expected_revision=revision)
        self.assertEqual(self.target.read_bytes(), b'external edit before next write')
        self.assertTrue(Path(caught.exception.recovery_dir).is_dir())
        self.safety.shutil.rmtree(caught.exception.recovery_dir)

    def test_history_creation_never_overwrites_existing_version(self):
        self.safety.atomic_write(self.target, b'second', backup=True)
        existing = next((self.root / '.lishuttle-history').iterdir())
        before = existing.read_bytes()
        with patch.object(self.safety, '_history_path', return_value=existing):
            with self.assertRaises(FileExistsError):
                self.safety.atomic_write(self.target, b'third', backup=True)
        self.assertEqual(self.target.read_bytes(), b'second')
        self.assertEqual(existing.read_bytes(), before)

    def test_backup_history_works_when_hard_links_are_unavailable(self):
        with patch.object(self.safety.os, 'link', side_effect=OSError('hard links unsupported')):
            self.safety.atomic_write(self.target, b'second', backup=True)
        self.assertEqual(self.target.read_bytes(), b'second')
        self.assertEqual(Path(str(self.target) + '.bak').read_bytes(), b'original')
        self.assertEqual([p.read_bytes() for p in (self.root / '.lishuttle-history').iterdir()], [b'original'])

    def test_history_fallback_does_not_overwrite_an_existing_version(self):
        self.safety.atomic_write(self.target, b'second', backup=True)
        existing = next((self.root / '.lishuttle-history').iterdir())
        before = existing.read_bytes()
        with patch.object(self.safety, '_history_path', return_value=existing), \
                patch.object(self.safety.os, 'link', side_effect=OSError('hard links unsupported')):
            with self.assertRaises(FileExistsError):
                self.safety.atomic_write(self.target, b'third', backup=True)
        self.assertEqual(self.target.read_bytes(), b'second')
        self.assertEqual(existing.read_bytes(), before)

    def test_transaction_restores_overwritten_files_and_removes_new_files(self):
        new_file = self.root / 'new.xml'
        with self.assertRaisesRegex(OSError, 'later operation'):
            with self.safety.FileTransaction() as transaction:
                transaction.touch(self.target)
                self.target.write_bytes(b'changed')
                transaction.write(new_file, b'created')
                raise OSError('later operation')
        self.assertEqual(self.target.read_bytes(), b'original')
        self.assertFalse(new_file.exists())

    def test_transaction_rollback_includes_backups_and_new_history(self):
        self.safety.atomic_write(self.target, b'second', backup=True)
        backup = self.target.with_suffix('.xml.bak')
        versions = {p.name: p.read_bytes() for p in (self.root / '.lishuttle-history').iterdir()}
        with self.assertRaisesRegex(OSError, 'abort'):
            with self.safety.FileTransaction() as transaction:
                transaction.write(self.target, b'third', backup=True)
                raise OSError('abort')
        self.assertEqual(self.target.read_bytes(), b'second')
        self.assertEqual(backup.read_bytes(), b'original')
        self.assertEqual({p.name: p.read_bytes() for p in (self.root / '.lishuttle-history').iterdir()}, versions)

    def test_first_write_failure_leaves_no_new_target_or_temporary(self):
        target = self.root / 'first.xml'
        with patch.object(self.safety.os, 'replace', side_effect=OSError('first replace failed')):
            with self.assertRaisesRegex(OSError, 'first replace failed'):
                self.safety.atomic_write(target, b'new')
        self.assertFalse(target.exists())
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_transaction_copy_failure_restores_previous_copy(self):
        source = self.root / 'source.dat'
        source.write_bytes(b'resource')
        second = self.root / 'second.dat'
        second.write_bytes(b'old second')
        real_copy = self.safety.shutil.copy2

        def copy(src, dst, *args, **kwargs):
            if Path(src) == source and 'second.dat' in Path(dst).name:
                raise OSError('second resource failed')
            return real_copy(src, dst, *args, **kwargs)

        with patch.object(self.safety.shutil, 'copy2', side_effect=copy):
            with self.assertRaisesRegex(OSError, 'second resource failed'):
                with self.safety.FileTransaction() as transaction:
                    transaction.copy(source, self.target)
                    transaction.copy(source, second)
        self.assertEqual(self.target.read_bytes(), b'original')
        self.assertEqual(second.read_bytes(), b'old second')

    def test_copy_backup_keeps_previous_versions_without_reading_whole_resource(self):
        self.assertIn('backup', inspect.signature(self.safety.FileTransaction.copy).parameters)
        source = self.root / 'resource.dat'
        source.write_bytes(b'resource v2')
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('whole resource read')):
            with self.safety.FileTransaction() as transaction:
                transaction.copy(source, self.target, backup=True)
        source.write_bytes(b'resource v3')
        with self.safety.FileTransaction() as transaction:
            transaction.copy(source, self.target, backup=True)
        self.assertEqual(self.target.read_bytes(), b'resource v3')
        self.assertEqual(Path(str(self.target) + '.bak').read_bytes(), b'resource v2')
        versions = list((self.root / '.lishuttle-history').iterdir())
        self.assertEqual(len(versions), 2)
        self.assertEqual({p.read_bytes() for p in versions}, {b'original', b'resource v2'})

    def test_copy_backup_rollback_restores_backup_and_removes_new_history(self):
        self.assertIn('backup', inspect.signature(self.safety.FileTransaction.copy).parameters)
        source = self.root / 'resource.dat'
        source.write_bytes(b'replacement')
        backup = Path(str(self.target) + '.bak')
        backup.write_bytes(b'previous backup')
        with self.assertRaisesRegex(OSError, 'abort copy'):
            with self.safety.FileTransaction() as transaction:
                transaction.copy(source, self.target, backup=True)
                raise OSError('abort copy')
        self.assertEqual(self.target.read_bytes(), b'original')
        self.assertEqual(backup.read_bytes(), b'previous backup')
        self.assertFalse(any((self.root / '.lishuttle-history').glob('*')))

    def test_copy_history_does_not_share_storage_with_mutable_backup(self):
        source = self.root / 'resource.dat'
        source.write_bytes(b'replacement')
        with self.safety.FileTransaction() as transaction:
            transaction.copy(source, self.target, backup=True)
        backup = Path(str(self.target) + '.bak')
        backup.write_bytes(b'edited backup')
        versions = list((self.root / '.lishuttle-history').iterdir())
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0].read_bytes(), b'original')
        self.assertEqual(self.target.read_bytes(), b'replacement')

    def test_copy_history_preparation_error_keeps_destination_and_backup(self):
        source = self.root / 'resource.dat'
        source.write_bytes(b'replacement')
        backup = Path(str(self.target) + '.bak')
        backup.write_bytes(b'previous backup')
        prepare_copy = self.safety._prepare_copy

        def fail_history(path, original):
            if Path(path).parent.name == '.lishuttle-history':
                raise OSError('history write failed')
            return prepare_copy(path, original)

        with patch.object(self.safety, '_prepare_copy', side_effect=fail_history):
            with self.assertRaisesRegex(OSError, 'history write failed'):
                with self.safety.FileTransaction() as transaction:
                    transaction.copy(source, self.target, backup=True)
        self.assertEqual(self.target.read_bytes(), b'original')
        self.assertEqual(backup.read_bytes(), b'previous backup')
        self.assertFalse(any((self.root / '.lishuttle-history').glob('*')))
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_copy_backup_replace_error_restores_target_and_original_backup(self):
        self.assertIn('backup', inspect.signature(self.safety.FileTransaction.copy).parameters)
        source = self.root / 'resource.dat'
        source.write_bytes(b'replacement')
        backup = Path(str(self.target) + '.bak')
        backup.write_bytes(b'previous backup')
        real_replace = self.safety.os.replace

        def replace(src, dst):
            if Path(dst) == backup:
                raise OSError('copy backup failed')
            return real_replace(src, dst)

        with patch.object(self.safety.os, 'replace', side_effect=replace):
            with self.assertRaisesRegex(OSError, 'copy backup failed'):
                with self.safety.FileTransaction() as transaction:
                    transaction.copy(source, self.target, backup=True)
        self.assertEqual(self.target.read_bytes(), b'original')
        self.assertEqual(backup.read_bytes(), b'previous backup')
        self.assertFalse(any((self.root / '.lishuttle-history').glob('*')))

    def test_copy_accepts_a_read_only_source(self):
        source = self.root / 'readonly.dat'
        source.write_bytes(b'readonly resource')
        source.chmod(stat.S_IREAD)
        try:
            with self.safety.FileTransaction() as transaction:
                transaction.copy(source, self.target, backup=True)
            self.assertEqual(self.target.read_bytes(), b'readonly resource')
        finally:
            source.chmod(stat.S_IREAD | stat.S_IWRITE)
            self.target.chmod(stat.S_IREAD | stat.S_IWRITE)

    def test_transaction_rolls_back_a_copied_read_only_resource(self):
        source = self.root / 'readonly.dat'
        source.write_bytes(b'readonly resource')
        source.chmod(stat.S_IREAD)
        try:
            with self.assertRaisesRegex(OSError, 'later resource failed'):
                with self.safety.FileTransaction() as transaction:
                    transaction.copy(source, self.target, backup=True)
                    raise OSError('later resource failed')
            self.assertEqual(self.target.read_bytes(), b'original')
            self.assertFalse(Path(str(self.target) + '.bak').exists())
        finally:
            source.chmod(stat.S_IREAD | stat.S_IWRITE)
            self.target.chmod(stat.S_IREAD | stat.S_IWRITE)

    def test_transaction_removes_a_new_read_only_resource_on_rollback(self):
        source = self.root / 'readonly.dat'
        source.write_bytes(b'readonly resource')
        source.chmod(stat.S_IREAD)
        new_target = self.root / 'new.dat'
        try:
            with self.assertRaisesRegex(OSError, 'abort new copy'):
                with self.safety.FileTransaction() as transaction:
                    transaction.copy(source, new_target)
                    raise OSError('abort new copy')
            self.assertFalse(new_target.exists())
        finally:
            source.chmod(stat.S_IREAD | stat.S_IWRITE)
            if new_target.exists():
                new_target.chmod(stat.S_IREAD | stat.S_IWRITE)

    def test_transaction_can_discard_a_read_only_snapshot(self):
        self.target.chmod(stat.S_IREAD)
        try:
            with self.safety.FileTransaction() as transaction:
                transaction.touch(self.target)
            self.assertFalse(Path(transaction.recovery_dir).exists())
            self.assertEqual(self.target.read_bytes(), b'original')
        finally:
            self.target.chmod(stat.S_IREAD | stat.S_IWRITE)

    def test_committed_write_is_successful_when_snapshot_cleanup_is_denied(self):
        transaction = self.safety.FileTransaction()
        transaction.write(self.target, b'committed', backup=True)
        self.addCleanup(self.safety._discard_snapshots, transaction.recovery_dir)
        with patch.object(self.safety, '_discard_snapshots', side_effect=PermissionError('snapshot busy')):
            with self.assertWarnsRegex(RuntimeWarning, 'snapshot busy') as caught:
                try:
                    transaction.commit()
                except OSError as error:
                    self.fail(f'Cleanup must not report a committed save as failed: {error}')
        self.assertIn(transaction.recovery_dir, str(caught.warning))
        self.assertTrue(Path(transaction.recovery_dir).is_dir())
        self.assertEqual(self.target.read_bytes(), b'committed')
        self.assertEqual(Path(str(self.target) + '.bak').read_bytes(), b'original')
        self.assertEqual([p.read_bytes() for p in (self.root / '.lishuttle-history').iterdir()], [b'original'])
        transaction.rollback()
        self.assertEqual(self.target.read_bytes(), b'committed')

    def test_snapshot_cleanup_denial_does_not_mask_original_rollback_cause(self):
        transaction = self.safety.FileTransaction()
        transaction.touch(self.target)
        self.addCleanup(self.safety._discard_snapshots, transaction.recovery_dir)
        with patch.object(self.safety, '_discard_snapshots', side_effect=PermissionError('snapshot busy')):
            with self.assertWarnsRegex(RuntimeWarning, 'snapshot busy'):
                with self.assertRaisesRegex(OSError, 'later operation failed'):
                    with transaction:
                        self.target.write_bytes(b'changed')
                        raise OSError('later operation failed')
        self.assertEqual(self.target.read_bytes(), b'original')

    def test_cleanup_warning_cannot_fail_commit_under_warnings_as_errors(self):
        transaction = self.safety.FileTransaction()
        transaction.touch(self.target)
        self.target.write_bytes(b'committed')
        self.addCleanup(self.safety._discard_snapshots, transaction.recovery_dir)
        with warnings.catch_warnings():
            warnings.simplefilter('error', RuntimeWarning)
            with patch.object(self.safety, '_discard_snapshots', side_effect=PermissionError('snapshot busy')):
                transaction.commit()
        transaction.rollback()
        self.assertEqual(self.target.read_bytes(), b'committed')

    def test_committed_atomic_save_is_successful_when_temporary_cleanup_is_denied(self):
        self._assert_committed_temporary_cleanup_denial(copy=False)

    def test_committed_copy_is_successful_when_temporary_cleanup_is_denied(self):
        self._assert_committed_temporary_cleanup_denial(copy=True)

    def _assert_committed_temporary_cleanup_denial(self, copy):
        source = self.root / 'resource.dat'
        source.write_bytes(b'committed')
        real_unlink = self.safety._unlink_file
        retained = []

        def busy_history_temporary(path):
            path = Path(path)
            if path.parent.name == '.lishuttle-history' and path.suffix == '.tmp' and path.exists():
                retained.append(path)
                self.addCleanup(real_unlink, path)
                raise PermissionError('temporary busy')
            return real_unlink(path)

        with patch.object(self.safety, '_unlink_file', side_effect=busy_history_temporary):
            with self.assertWarnsRegex(RuntimeWarning, 'temporary busy') as caught:
                try:
                    if copy:
                        with self.safety.FileTransaction() as transaction:
                            transaction.copy(source, self.target, backup=True)
                    else:
                        revision = self.safety.atomic_write(self.target, b'committed', backup=True)
                        self.assertEqual(revision, hashlib.sha256(b'committed').hexdigest())
                except OSError as error:
                    self.fail(f'Temporary cleanup must not fail a committed update: {error}')
        self.assertTrue(retained)
        self.assertIn(str(retained[0]), str(caught.warning))
        self.assertEqual(self.target.read_bytes(), b'committed')
        self.assertEqual(Path(str(self.target) + '.bak').read_bytes(), b'original')

    def test_rollback_failure_exposes_recovery_files_and_original_cause(self):
        transaction = self.safety.FileTransaction()
        with self.assertRaises(self.safety.FileRollbackError) as caught:
            with transaction:
                transaction.touch(self.target)
                self.target.write_bytes(b'changed')
                with patch.object(self.safety.os, 'replace', side_effect=OSError('restore denied')):
                    transaction.rollback()
        self.assertIn('restore denied', str(caught.exception))
        self.assertTrue(Path(caught.exception.recovery_dir).is_dir())
        self.assertTrue(any(p.read_bytes() == b'original' for p in Path(caught.exception.recovery_dir).iterdir()))
        # The explicit failure leaves snapshots for recovery; this test owns them.
        self.safety.shutil.rmtree(caught.exception.recovery_dir)

    def test_rollback_cleanup_failure_reports_all_errors_and_recovery_directory(self):
        transaction = self.safety.FileTransaction()
        transaction.touch(self.target)
        self.target.write_bytes(b'changed')
        with patch.object(self.safety.os, 'replace', side_effect=OSError('restore failed')), \
                patch.object(self.safety, '_unlink_file', side_effect=OSError('temporary cleanup failed')):
            with self.assertRaises(self.safety.FileRollbackError) as caught:
                transaction.rollback()
        self.assertTrue(Path(caught.exception.recovery_dir).is_dir())
        self.assertEqual(len(caught.exception.errors), 2)
        self.assertIn('restore failed', str(caught.exception))
        self.assertIn('temporary cleanup failed', str(caught.exception))
        transaction.rollback()
        self.assertEqual(self.target.read_bytes(), b'original')


if __name__ == '__main__':
    unittest.main()
