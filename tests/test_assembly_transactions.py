"""Assembly must preserve the last complete configuration after controlled errors."""
from contextlib import ExitStack
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core
import render_schema as renderer
from server import Api


class AssemblyTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'build/Bin'
        self.xml = self.bin / 'runtimelibrary/job.xml'
        self.xml.parent.mkdir(parents=True)
        self.xml.write_text('<RuntimeSchema name="old"><PathlossDirectory>old</PathlossDirectory></RuntimeSchema>')
        self.task_dir = self.root / 'task'
        self.task_dir.mkdir()
        self.task = dict(name='task', dir=self.task_dir.as_posix(), has_antennas=True,
                         txts=[], engineering_file='engineering.csv')
        self.env = dict(PROJECT_DIR=self.root.as_posix(), BUILD_SUBDIR='build', CONFIG_SRC='config',
                        EXE_NAME='test.exe', MAP_ROOT=self.root.as_posix(), OUT_ROOT=self.root.as_posix())
        sample = self.root / 'config/runtimelibrary/runtimeschema.xml'
        sample.parent.mkdir(parents=True)
        sample.write_text('<RuntimeSchema name="sample"><EngineeringFilePath>sample.csv</EngineeringFilePath>'
                          '<PathlossDirectory>outputs</PathlossDirectory></RuntimeSchema>')

    def api_context(self, render):
        stack = ExitStack()
        stack.enter_context(patch.object(core, 'load_env', return_value=self.env))
        stack.enter_context(patch.object(core, 'scan_tasks', return_value=([self.task], 'tasks')))
        stack.enter_context(patch.object(core, 'validate_engineering', return_value='engineering.csv'))
        stack.enter_context(patch.object(core, 'JOBS_DIR', str(self.root / 'jobs')))
        stack.enter_context(patch.object(core, 'ensure_runtime_resources', return_value={}))
        stack.enter_context(patch.object(core, 'run_render', side_effect=render))
        stack.enter_context(patch.object(core, 'sync_vs_launch', return_value={}))
        return stack

    def test_old_xml_and_fatal_render_never_copy_or_report_assembly(self):
        before = self.xml.read_bytes()
        with self.api_context(lambda job, **kw: dict(exit_code=1, output='fatal: invalid XML',
                              generated=False, status='failed', attempt_id='fatal')), \
                patch.object(core, 'assemble_files') as copy:
            result = Api.render(dict(job_name='job', task=self.task, copy_antennas=True))
        self.assertFalse(result['schema_ok'], result)
        copy.assert_not_called()
        self.assertIn('fatal: invalid XML', result['render_output'])
        self.assertEqual(self.xml.read_bytes(), before)
        self.assertEqual(list((self.root / 'jobs').rglob('*.env')), [])

    def test_fatal_render_reports_reverted_base_resources_and_restores_outputs(self):
        before = self.xml.read_bytes()
        manifest = Path(str(self.xml) + '.manifest.json')
        manifest.write_bytes(b'previous manifest')
        staged = self.bin / 'staged.dll'

        def stage(env, transaction):
            transaction.write(staged, b'new base resource')
            return dict(copied=[dict(file='staged.dll', to=str(staged))])

        def fatal(job, **kwargs):
            self.xml.write_bytes(b'partial new XML')
            manifest.write_bytes(b'partial new manifest')
            return dict(exit_code=1, output='fatal rendering', generated=False,
                        status='failed', attempt_id='failed-attempt')

        with self.api_context(fatal), patch.object(core, 'ensure_runtime_resources', side_effect=stage):
            result = Api.render(dict(job_name='job', task=self.task))

        self.assertEqual(result.get('assembly_status'), 'rolled_back')
        self.assertIn('已撤销', result['render_output'])
        self.assertEqual(self.xml.read_bytes(), before)
        self.assertEqual(manifest.read_bytes(), b'previous manifest')
        self.assertFalse(staged.exists())

    def render_success(self, path, **kwargs):
        transaction = kwargs.get('transaction')
        if transaction is not None:
            for target in (self.xml, Path(str(self.xml) + '.manifest.json')):
                if target.is_file():
                    transaction.copy(target, target, backup=True)
        with contextlib.redirect_stdout(io.StringIO()):
            code = renderer.do_render(self.env, renderer.read_env_file(path, 'job'),
                                      'test', path, 'env.env', attempt_id='current-attempt',
                                      backup_existing=transaction is None)
        return dict(exit_code=code, output='generated; missing input', generated=True,
                    status='missing_inputs' if code else 'ready', attempt_id='current-attempt')

    def test_missing_inputs_from_confirmed_generation_still_copy_resources(self):
        with self.api_context(self.render_success), patch.object(core, 'assemble_files', return_value=[]) as copy:
            result = Api.render(dict(job_name='job', task=self.task, city='city', copy_antennas=True))
        self.assertTrue(result['schema_ok'], result)
        self.assertTrue(result['generated'])
        self.assertEqual(result['render_status'], 'missing_inputs')
        self.assertEqual(result['assembly_status'], 'applied')
        copy.assert_called_once()

    def test_recovery_error_reports_snapshot_instead_of_claiming_full_rollback(self):
        from file_safety import FileRollbackError
        recovery = self.root / 'recovery-snapshots'
        recovery.mkdir()
        failure = FileRollbackError(recovery, [(str(self.xml), OSError('file is locked'))])
        with self.api_context(self.render_success), \
                patch.object(core, 'assemble_files', side_effect=failure):
            result = Api.render(dict(job_name='job', task=self.task, city='city', copy_antennas=True))
        self.assertFalse(result['schema_ok'])
        self.assertFalse(result['generated'])
        self.assertEqual(result['assembly_status'], 'recovery_required')
        self.assertEqual(result['recovery_dir'], str(recovery))
        self.assertIn('需核对恢复', result['render_output'])
        self.assertNotIn('[已撤销]', result['render_output'])

    def test_resource_failure_restores_xml_manifest_job_and_base_files(self):
        self._check_api_resource_failure(first_assembly=False)

    def test_first_assembly_failure_leaves_no_xml_manifest_job_or_resource(self):
        self._check_api_resource_failure(first_assembly=True)

    def _check_api_resource_failure(self, first_assembly):
        source = self.task_dir / 'antennas'
        source.mkdir()
        for name in ('a.txt', 'b.txt'):
            (source / name).write_bytes(b'new-' + name.encode())
        self.task.update(antenna_dir=str(source))
        destination = self.bin / 'antennas'
        if not first_assembly:
            destination.mkdir()
            (destination / 'a.txt').write_bytes(b'old-a')
            (destination / 'a.txt.bak').write_bytes(b'older-a')
            Path(str(self.xml) + '.manifest.json').write_bytes(b'old manifest')
            with patch.object(core, 'load_env', return_value=self.env), \
                    patch.object(core, 'validate_engineering', return_value='engineering.csv'), \
                    patch.object(core, 'JOBS_DIR', str(self.root / 'jobs')):
                core.build_job_env('job', 'pl', 'old-id', self.task, 'city', 'outdoor')
        else:
            self.xml.unlink()
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        original_copy = core.shutil.copy2
        count = 0

        def fail_second(src, dst, *args, **kwargs):
            nonlocal count
            if Path(src).parent == source:
                count += 1
                if count == 2:
                    raise OSError('second resource copy failed')
            return original_copy(src, dst, *args, **kwargs)

        def stage(env, transaction):
            transaction.write(self.bin / 'new-base.dll', b'base')
            return {}

        with self.api_context(self.render_success), \
                patch.object(core, 'ensure_runtime_resources', side_effect=stage), \
                patch.object(core.shutil, 'copy2', side_effect=fail_second):
            result = Api.render(dict(job_name='job', task=self.task, city='city',
                                     task_id='new-id', copy_antennas=True))
        self.assertIn('second resource copy failed', result['error'])
        self.assertFalse(result['schema_ok'])
        after = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(after, before)

    def test_second_resource_copy_failure_restores_all_touched_files(self):
        source = self.task_dir / 'antennas'
        source.mkdir()
        (source / 'a.txt').write_bytes(b'new-a')
        (source / 'b.txt').write_bytes(b'new-b')
        target = self.bin / 'antennas'
        target.mkdir()
        (target / 'a.txt').write_bytes(b'old-a')
        (target / 'a.txt.bak').write_bytes(b'older-a')
        self.task.update(antenna_dir=str(source))
        original_copy = core.shutil.copy2
        count = 0

        def fail_second(src, dst, *args, **kwargs):
            nonlocal count
            if Path(src).parent == source:
                count += 1
                if count == 2:
                    raise OSError('second resource copy failed')
            return original_copy(src, dst, *args, **kwargs)

        with patch.object(core.shutil, 'copy2', side_effect=fail_second):
            with self.assertRaisesRegex(OSError, 'second resource'):
                core.assemble_files(self.task, self.env, groups=('antenna',))
        self.assertEqual((target / 'a.txt').read_bytes(), b'old-a')
        self.assertEqual((target / 'a.txt.bak').read_bytes(), b'older-a')
        self.assertFalse((target / 'b.txt').exists())


class RenderReceiptTests(unittest.TestCase):
    """Run the actual Python renderer with temporary configuration, never an engine."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(PROJECT_DIR=self.root.as_posix(), CONFIG_SRC='config', BUILD_SUBDIR='build',
                        EXE_NAME='test.exe', MAP_ROOT=self.root.as_posix(), OUT_ROOT=self.root.as_posix())
        self.sample = self.root / 'config/runtimelibrary/runtimeschema.xml'
        self.sample.parent.mkdir(parents=True)
        self.sample.write_text('<RuntimeSchema name="sample"><EngineeringFilePath>sample.csv</EngineeringFilePath></RuntimeSchema>')
        self.job = self.root / 'job.env'
        self.job.write_text('JOB_NAME="job"\nSCHEMA_NAME="job.xml"\nFUNC="pl"\nCITY="city"\n'
                            'ENGINEERING_FILE="missing.csv"\nPOLYGON_FILE="area.txt"\n')
        self.snapshot = self.root / 'snapshot.json'
        self.snapshot.write_text(json.dumps(self.env), encoding='utf-8')
        self.xml = self.root / 'build/Bin/runtimelibrary/job.xml'

    def render(self):
        with patch.object(core, 'load_env', return_value=self.env), \
                patch.object(core, 'write_snapshot', return_value=str(self.snapshot)):
            return core.run_render(str(self.job))

    def test_identical_xml_uses_unique_attempt_and_accepts_missing_inputs(self):
        first = self.render()
        xml = self.xml.read_bytes()
        second = self.render()
        self.assertTrue(first['generated'], first)
        self.assertTrue(second['generated'], second)
        self.assertEqual(second['status'], 'missing_inputs')
        self.assertEqual(second['exit_code'], 1)
        self.assertEqual(self.xml.read_bytes(), xml)
        self.assertNotEqual(first['attempt_id'], second['attempt_id'])
        self.assertEqual(len(second['outputs']), 2)

    def test_old_xml_plus_fatal_subprocess_has_no_valid_receipt(self):
        self.render()
        before = self.xml.read_bytes()
        self.sample.write_text('<invalid XML')
        result = self.render()
        self.assertEqual(result['exit_code'], 1)
        self.assertFalse(result['generated'])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.xml.read_bytes(), before)

    def test_api_owned_sample_regeneration_backs_up_both_targets_and_can_roll_back(self):
        self.render()
        manifest = Path(str(self.xml) + '.manifest.json')
        originals = (self.xml.read_bytes(), manifest.read_bytes())
        with patch.object(core, 'load_env', return_value=self.env), \
                patch.object(core, 'write_snapshot', return_value=str(self.snapshot)):
            with core.FileTransaction() as transaction:
                transaction.touch(self.xml)
                transaction.touch(manifest)
                generation = core.run_render(str(self.job), transaction=transaction)
                self.assertTrue(generation['generated'], generation)
        self.assertTrue(Path(str(self.xml) + '.bak').is_file(), 'API XML overwrite must keep a backup')
        self.assertTrue(Path(str(manifest) + '.bak').is_file(), 'API manifest overwrite must keep a backup')
        self.assertEqual(Path(str(self.xml) + '.bak').read_bytes(), originals[0])
        self.assertEqual(Path(str(manifest) + '.bak').read_bytes(), originals[1])
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch.object(core, 'load_env', return_value=self.env), \
                patch.object(core, 'write_snapshot', return_value=str(self.snapshot)):
            with self.assertRaisesRegex(OSError, 'later assembly failure'):
                with core.FileTransaction() as transaction:
                    transaction.touch(self.xml)
                    transaction.touch(manifest)
                    generation = core.run_render(str(self.job), transaction=transaction)
                    self.assertTrue(generation['generated'], generation)
                    raise OSError('later assembly failure')
        self.assertEqual({p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}, before)

    def test_changed_xml_or_manifest_is_rejected_even_with_current_attempt(self):
        real_run = core.subprocess.run
        for suffix in ('', '.manifest.json'):
            with self.subTest(suffix=suffix):
                def tamper(*args, **kwargs):
                    process = real_run(*args, **kwargs)
                    Path(str(self.xml) + suffix).write_bytes(b'tampered')
                    return process
                with patch.object(core.subprocess, 'run', side_effect=tamper):
                    result = self.render()
                self.assertFalse(result['generated'], result)

    def test_replayed_attempt_and_incomplete_target_set_are_rejected(self):
        real_run = core.subprocess.run
        for mode in ('attempt', 'targets'):
            with self.subTest(mode=mode):
                def tamper(arguments, **kwargs):
                    process = real_run(arguments, **kwargs)
                    receipt_path = Path(arguments[arguments.index('--receipt') + 1])
                    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
                    if mode == 'attempt':
                        receipt['attempt_id'] = 'previous-attempt'
                    else:
                        receipt['outputs'].pop()
                    receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
                    return process
                with patch.object(core.subprocess, 'run', side_effect=tamper):
                    result = self.render()
                self.assertFalse(result['generated'], result)

    def test_non_object_generation_proofs_are_rejected_without_request_failure(self):
        real_run = core.subprocess.run
        for mode in ('null_receipt', 'list_receipt', 'null_generation'):
            with self.subTest(mode=mode):
                def tamper(arguments, **kwargs):
                    import hashlib
                    process = real_run(arguments, **kwargs)
                    receipt_path = Path(arguments[arguments.index('--receipt') + 1])
                    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
                    if mode == 'null_generation':
                        manifest_path = Path(str(self.xml) + '.manifest.json')
                        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                        manifest['generation'] = None
                        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
                        for item in receipt['outputs']:
                            if Path(item['path']) == manifest_path:
                                item['revision'] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
                    else:
                        receipt = None if mode == 'null_receipt' else []
                    receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
                    return process
                with patch.object(core.subprocess, 'run', side_effect=tamper):
                    result = self.render()
                self.assertFalse(result['generated'], result)
                self.assertEqual(result['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
