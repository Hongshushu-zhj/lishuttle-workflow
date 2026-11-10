from pathlib import Path
import hashlib
import importlib
import json
import os
import sys
import tempfile
import unittest
import warnings
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
try:
    history_module = importlib.import_module('run_history')
except ModuleNotFoundError:
    history_module = None


class RunHistoryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(history_module, 'persistent run history module is required')
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.history_root = self.root / 'history'
        self.history = history_module.RunHistory(self.history_root)

    def fixture(self, sid=123, project='project-a'):
        binary = self.root / 'bin'
        schema = binary / 'runtimelibrary/task.xml'
        schema.parent.mkdir(parents=True, exist_ok=True)
        schema.write_text('<RuntimeSchema name="task"/>', encoding='utf-8')
        Path(str(schema) + '.manifest.json').write_text('{"attempt":"one"}', encoding='utf-8')
        context = {'project': project, 'bin_dir': str(binary), 'schema_name': 'task.xml',
                   'task_name': 'task', 'project_config': {'name': 'original'}}
        record = self.history.create(sid, 'fixture', context, ['engine', 'task.xml'], str(binary),
                                     baseline={'files': {}})
        return record, context, schema

    def artifact(self, relative='output/product.dat', data=b'valid product'):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def result(self, *paths, digest=None):
        return {'verdict': 'success', 'artifacts': {'status': 'valid', 'checked': [
                    {'path': str(p), 'size': p.stat().st_size,
                     'sha256': digest or hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]},
                'files': [{'path': str(p), 'rel': p.name, 'size': p.stat().st_size} for p in paths]}

    def test_reading_missing_store_does_not_create_directory(self):
        self.assertIsNone(self.history.get(123))
        self.assertEqual(self.history.list(), [])
        self.assertEqual(self.history.output(123)['code'], 'SESSION_NOT_FOUND')
        self.assertEqual(self.history.current(123)['status'], 'unconfirmed')
        self.assertFalse(self.history_root.exists())

    def test_create_pins_configuration_schema_and_manifest(self):
        record, context, schema = self.fixture()
        context['project_config']['name'] = 'changed'
        schema.write_text('replaced schema', encoding='utf-8')
        loaded = self.history.get(123)
        self.assertEqual(loaded['context']['project_config']['name'], 'original')
        snapshots = {f['kind']: f for f in loaded['snapshots']}
        self.assertEqual(Path(snapshots['schema']['archive_path']).read_text(encoding='utf-8'),
                         '<RuntimeSchema name="task"/>')
        self.assertEqual(json.loads(Path(snapshots['manifest']['archive_path']).read_text(encoding='utf-8')),
                         {'attempt': 'one'})
        self.assertEqual(loaded['status'], 'running')
        self.assertEqual(record['sid'], 123)

    def test_logs_are_incremental_and_readable_after_restart(self):
        self.fixture()
        self.history.append(123, '第一行')
        self.history.append(123, 'second line')
        reopened = history_module.RunHistory(self.history_root)
        output = reopened.output(123, since=1, limit=1)
        self.assertEqual(output['lines'], ['second line'])
        self.assertEqual(output['total'], 2)
        self.assertEqual(output['next'], 2)
        self.assertEqual(output['next_since'], 2)
        self.assertFalse(output['has_more'])
        self.assertEqual(output['status'], 'running')

    def test_finish_archives_products_without_moving_originals(self):
        self.fixture()
        product = self.artifact()
        result = self.result(product)
        record = self.history.finish(123, 'done', 0, result)
        result['verdict'] = 'tampered'
        self.assertEqual(record['archive']['status'], 'complete')
        self.assertEqual(Path(record['archive']['dir']), self.history_root / '123')
        self.assertEqual(record['result']['verdict'], 'success')
        self.assertEqual(len(record['archive']['files']), 1)
        self.assertEqual(Path(record['archive']['files'][0]['archive_path']).read_bytes(), b'valid product')
        self.assertTrue(product.exists())
        self.assertEqual(self.history.current(123)['status'], 'matched')
        product.write_bytes(b'new result')
        self.assertEqual(self.history.current(123)['status'], 'changed')
        product.unlink()
        self.assertEqual(self.history.current(123)['status'], 'missing')
        self.assertEqual(self.history.get(123)['result']['verdict'], 'success')

    def test_archive_hash_mismatch_never_claims_complete(self):
        self.fixture()
        product = self.artifact()
        record = self.history.finish(123, 'done', 0, self.result(product, digest='0' * 64))
        self.assertEqual(record['archive']['status'], 'incomplete')
        self.assertTrue(record['archive']['issues'])
        self.assertEqual(record['result']['verdict'], 'success')
        self.assertNotEqual(self.history.current(123)['status'], 'matched')

    def test_archive_checksum_cannot_substitute_for_validation_checksum(self):
        self.fixture()
        product = self.artifact(data=b'replaced before archive')
        report = {'verdict': 'success', 'files': [{'path': str(product), 'rel': product.name}],
                  'artifacts': {'status': 'valid', 'checked': [{'path': str(product)}]}}
        record = self.history.finish(123, 'done', 0, report)
        self.assertEqual(record['archive']['status'], 'complete')
        self.assertTrue(record['archive']['files'][0]['sha256'])
        self.assertEqual(self.history.current(123)['status'], 'unconfirmed',
                         '归档时产生的摘要不能冒充当时验证摘要')
        self.assertEqual(self.history.current(123)['files'][0]['status'], 'unconfirmed')

    def test_archive_missing_product_keeps_conclusion_and_marks_incomplete(self):
        self.fixture()
        product = self.artifact()
        result = self.result(product)
        product.unlink()
        record = self.history.finish(123, 'done', 0, result)
        self.assertEqual(record['archive']['status'], 'incomplete')
        self.assertEqual(record['result']['verdict'], 'success')

    def test_archive_copy_failure_keeps_record_and_conclusion(self):
        self.fixture()
        product = self.artifact()
        with patch.object(history_module.RunHistory, '_copy_file', side_effect=OSError('locked')):
            record = self.history.finish(123, 'done', 0, self.result(product))
        self.assertEqual(record['archive']['status'], 'incomplete')
        self.assertEqual(self.history.get(123)['result']['verdict'], 'success')

    def test_products_with_same_basename_have_separate_archives(self):
        self.fixture()
        first = self.artifact('first/result.xml', b'first')
        second = self.artifact('second/result.xml', b'second')
        record = self.history.finish(123, 'done', 0, self.result(first, second))
        paths = [Path(f['archive_path']) for f in record['archive']['files']]
        self.assertEqual(len(set(paths)), 2)
        self.assertEqual({p.read_bytes() for p in paths}, {b'first', b'second'})
        for path in paths:
            self.assertTrue(path.is_relative_to(self.history_root))

    def test_finished_record_cannot_be_replaced_by_later_products(self):
        self.fixture()
        product = self.artifact(data=b'first run')
        original = self.history.finish(123, 'done', 0, self.result(product))
        product.write_bytes(b'later replacement')
        again = self.history.finish(123, 'done', 1, {'verdict': 'failed'})
        self.assertEqual(again, original)
        self.assertEqual(Path(again['archive']['files'][0]['archive_path']).read_bytes(), b'first run')

    def test_missing_selected_schema_is_recorded_as_incomplete_archive(self):
        self.history.create(123, 'missing schema', {'schema_path': str(self.root / 'missing.xml')},
                            ['engine'], str(self.root))
        record = self.history.finish(123, 'done', 0, {'verdict': 'unconfirmed'})
        self.assertEqual(record['archive']['status'], 'incomplete')
        self.assertTrue(record['snapshot_issues'])

    def test_large_console_page_returns_total_and_next_without_loading_all_lines(self):
        self.fixture()
        for line in range(25):
            self.history.append(123, str(line))
        page = self.history.output(123, since=4, limit=3)
        self.assertEqual(page['lines'], ['4', '5', '6'])
        self.assertEqual(page['total'], 25)
        self.assertEqual(page['next'], 7)
        self.assertTrue(page['has_more'])
        self.assertEqual(self.history.output(123, since=50, limit=3)['next'], 25)

    def test_pages_do_not_repeat_or_omit_lines_appended_between_polls(self):
        self.fixture()
        for line in range(6):
            self.history.append(123, str(line))
        first = self.history.output(123, limit=4)
        for line in range(6, 9):
            self.history.append(123, str(line))
        second = self.history.output(123, since=first['next_since'], limit=4)
        third = self.history.output(123, since=second['next_since'], limit=4)
        self.assertEqual(first['lines'] + second['lines'] + third['lines'], [str(n) for n in range(9)])

    def test_owner_liveness_handles_current_and_missing_processes(self):
        self.assertTrue(history_module._pid_alive(os.getpid()))
        self.assertFalse(history_module._pid_alive(0))
        self.assertFalse(history_module._pid_alive(None))

    def test_only_changed_engine_logs_are_attributed_to_this_run(self):
        binary = self.root / 'bin'
        binary.mkdir()
        old = binary / 'uplan.log'
        old.write_text('earlier run', encoding='utf-8')
        self.fixture()
        unchanged = self.history.finish(123, 'done', 0, {'verdict': 'unconfirmed'})
        self.assertFalse([f for f in unchanged['archive']['files'] if f['kind'] == 'engine_log'])
        self.fixture(124)
        old.write_text('this run', encoding='utf-8')
        changed = self.history.finish(124, 'done', 0, {'verdict': 'unconfirmed'})
        logs = [f for f in changed['archive']['files'] if f['kind'] == 'engine_log']
        self.assertEqual(len(logs), 1)
        self.assertEqual(Path(logs[0]['archive_path']).read_text(encoding='utf-8'), 'this run')
        self.assertEqual(logs[0]['attribution'], 'changed_during_run')

    def test_dead_owner_becomes_interrupted_without_false_conclusion(self):
        self.fixture()
        with patch.object(history_module, '_pid_alive', return_value=False):
            record = history_module.RunHistory(self.history_root).get(123)
        self.assertEqual(record['status'], 'interrupted')
        self.assertEqual(record['result']['verdict'], 'unconfirmed')
        self.assertIsNone(record['exit'])
        self.assertEqual(self.history.get(123)['status'], 'interrupted')

    def test_live_owner_is_not_marked_interrupted(self):
        self.fixture()
        with patch.object(history_module, '_pid_alive', return_value=True):
            record = history_module.RunHistory(self.history_root).get(123)
        self.assertEqual(record['status'], 'running')

    def test_interrupted_history_remains_readable_when_recovery_cannot_be_saved(self):
        self.fixture()
        with patch.object(history_module, '_pid_alive', return_value=False), \
                patch.object(self.history, '_write', side_effect=OSError('read-only history')):
            record = self.history.get(123)
        self.assertEqual(record['status'], 'interrupted')
        self.assertEqual(record['result']['verdict'], 'unconfirmed')
        self.assertFalse(record['recovery_persisted'])
        self.assertIn('read-only history', record['internal_error'])

    def test_metadata_cleanup_failure_does_not_report_committed_replace_as_failed(self):
        target = self.root / 'saved.json'
        with patch.object(Path, 'unlink', side_effect=PermissionError('cleanup locked')), \
                warnings.catch_warnings():
            warnings.simplefilter('error', RuntimeWarning)
            history_module._atomic_json(target, {'committed': True})
        self.assertEqual(json.loads(target.read_text(encoding='utf-8')), {'committed': True})

    def test_copy_cleanup_failure_does_not_report_committed_archive_as_failed(self):
        source = self.artifact()
        target = self.root / 'archived.dat'
        with patch.object(Path, 'unlink', side_effect=PermissionError('cleanup locked')), \
                warnings.catch_warnings():
            warnings.simplefilter('error', RuntimeWarning)
            fingerprint = self.history._copy_file(source, target)
        self.assertEqual(target.read_bytes(), source.read_bytes())
        self.assertEqual(fingerprint['sha256'], hashlib.sha256(source.read_bytes()).hexdigest())

    def test_list_is_project_filtered_newest_first_and_paginated(self):
        self.fixture(123, 'first')
        self.fixture(124, 'second')
        self.fixture(125, 'first')
        self.assertEqual([r['sid'] for r in self.history.list(project='first')], [125, 123])
        self.assertEqual([r['sid'] for r in self.history.list(limit=1, offset=1)], [124])

    def test_unsafe_or_duplicate_session_identifier_cannot_overwrite_history(self):
        self.fixture()
        for sid in ('../outside', '..', 'a/b', 'a\\b', '', -1):
            with self.subTest(sid=sid), self.assertRaises(ValueError):
                self.history.create(sid, 'bad', {}, [], str(self.root))
        with self.assertRaises(FileExistsError):
            self.history.create(123, 'duplicate', {}, [], str(self.root))
        self.assertEqual(self.history.get(123)['label'], 'fixture')

    def test_corrupt_or_misdirected_metadata_is_ignored_without_changing_other_record(self):
        self.fixture(123)
        self.fixture(124)
        original = self.history.get(124)
        metadata = self.history_root / '123/session.json'
        metadata.write_text('{broken', encoding='utf-8')
        self.assertIsNone(self.history.get(123))
        self.assertEqual([r['sid'] for r in self.history.list()], [124])
        misdirected = dict(original, owner_pid=0)
        metadata.write_text(json.dumps(misdirected), encoding='utf-8')
        self.assertIsNone(self.history.get(123))
        self.assertEqual(self.history.get(124), original)


if __name__ == '__main__':
    unittest.main()
