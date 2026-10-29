from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core
from server import Api


class RuntimeCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / 'engine'
        self.runtime = self.project / 'build/Bin/runtimelibrary'
        self.runtime.mkdir(parents=True)
        self.jobs = self.root / 'jobs'
        self.jobs.mkdir()
        self.env = dict(PROJECT_DIR=self.project.as_posix(), BUILD_SUBDIR='build', EXE_NAME='lishuttle.exe')
        self.archives = self.root / 'docs/runtime-config-archives'
        self.patches = [patch.object(core, 'load_env', return_value=self.env),
                        patch.object(core, 'JOBS_DIR', str(self.jobs)),
                        patch.object(core, 'ROOT', str(self.root))]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.generated('current')

    def generated(self, name, source='source.xml'):
        xml = self.runtime / (name + '.xml')
        xml.write_text(f'<RuntimeSchema name="{name}"><SceneSettingsPath>scene.xml</SceneSettingsPath></RuntimeSchema>', encoding='utf-8')
        job = self.job_path(name)
        job.parent.mkdir(parents=True, exist_ok=True)
        job.write_text(f'# 由平台生成，可手工编辑后用脚本复跑\nJOB_NAME="{name}"\nSCHEMA_NAME="${{JOB_NAME}}.xml"\n'
                       f'PLATFORM_PROJECT_DIR="{self.env["PROJECT_DIR"]}"\nPLATFORM_BUILD_SUBDIR="{self.env["BUILD_SUBDIR"]}"\n'
                       'PLATFORM_JOB_SCOPE="build-v1"\n', encoding='utf-8')
        manifest = dict(job_name=name, job_file=job.as_posix(), schema_source=source,
                        project_config=self.env, run=dict(schema_names=[xml.name], exe_dir=self.runtime.parent.as_posix()))
        Path(str(xml) + '.manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        return xml

    def job_path(self, name):
        from runtime_cleanup import build_scope
        return self.jobs / build_scope(self.env) / f'web-{name}.env'

    def preview(self, keep='current.xml'):
        return Api.cleanup_configs(dict(keep_schema=keep))

    def apply(self, plan, keep='current.xml'):
        return Api.cleanup_configs(dict(keep_schema=keep, token=plan['token'], apply=True))

    def test_archives_only_owned_history_preserves_current_manual_and_results(self):
        old = self.generated('old')
        self.generated('current')
        Path(str(old) + '.bak').write_text('old backup')
        manual = self.runtime / 'manual.xml'
        manual.write_text('<RuntimeSchema name="manual"/>')
        scene = self.runtime / 'scene.xml'
        scene.write_text('<SceneSettings/>')
        plan = self.preview()
        self.assertIn(old.as_posix(), [f['path'] for f in plan['files']])
        result = self.apply(plan)
        self.assertTrue(result['ok'])
        self.assertFalse(old.exists())
        self.assertTrue((self.runtime / 'current.xml').exists())
        self.assertTrue(manual.exists() and scene.exists())
        archive = Path(result['archive'])
        self.assertTrue((archive / 'restore.json').is_file())
        self.assertTrue(any(f.name == 'old.xml' for f in archive.rglob('*')))
        self.assertFalse(self.job_path('old').exists())
        self.assertEqual(self.preview()['files'], [])

    def test_source_references_and_manual_launch_references_are_protected(self):
        old = self.generated('source')
        self.generated('current', source=old.as_posix())
        manual_used = self.generated('manual-used')
        launch = self.project / '.vs/launch.vs.json'
        launch.parent.mkdir()
        launch.write_text(json.dumps(dict(configurations=[dict(name='manual', args=['-c', manual_used.name])])), encoding='utf-8')
        self.assertEqual(self.preview()['files'], [])
        self.assertTrue(old.exists() and manual_used.exists())

    def test_stale_preview_cannot_move_changed_files(self):
        old = self.generated('old')
        plan = self.preview()
        old.write_text('<RuntimeSchema name="changed"/>')
        result = self.apply(plan)
        self.assertIn('error', result)
        self.assertTrue(old.exists())

    def test_foreign_project_forged_job_and_source_xml_are_never_candidates(self):
        old = self.generated('foreign')
        mp = Path(str(old) + '.manifest.json')
        data = json.loads(mp.read_text())
        data['project_config']['PROJECT_DIR'] = str(self.root / 'another')
        mp.write_text(json.dumps(data))
        unknown = self.generated('unknown')
        self.job_path('unknown').write_text('# handwritten\nJOB_NAME=unknown')
        self.assertEqual(self.preview()['files'], [])
        self.assertTrue(old.exists() and unknown.exists())

    def test_cleanup_prunes_only_archived_platform_launch_entries(self):
        self.generated('old')
        self.generated('current')
        core.sync_vs_launch(self.env, 'old.xml', 'pl', '1', 'outdoor')
        core.sync_vs_launch(self.env, 'current.xml', 'pl', '1', 'outdoor')
        result = self.apply(self.preview())
        self.assertTrue(result['ok'])
        text = (self.project / '.vs/launch.vs.json').read_text(encoding='utf-8')
        self.assertNotIn('old.xml', text)
        self.assertIn('current.xml', text)

    def test_running_process_blocks_preview_and_apply(self):
        with patch.dict(core.RUNNER.sessions, {10000: {'status': 'running'}}, clear=True):
            self.assertIn('error', self.preview())

    def test_archive_failure_rolls_back_files(self):
        old = self.generated('old')
        plan = self.preview()
        import runtime_cleanup
        real_move = runtime_cleanup.shutil.move
        count = 0
        def move(source, destination):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('归档不可写')
            return real_move(source, destination)
        with patch.object(runtime_cleanup.shutil, 'move', side_effect=move):
            result = self.apply(plan)
        self.assertIn('error', result)
        self.assertTrue(old.exists())
        self.assertTrue(Path(str(old) + '.manifest.json').exists())
        self.assertTrue(self.job_path('old').exists())

    def test_new_reference_after_preview_invalidates_cleanup(self):
        old = self.generated('old')
        plan = self.preview()
        (self.runtime / 'manual.xml').write_text(f'<RuntimeSchema><Include>{old.name}</Include></RuntimeSchema>')
        self.assertIn('error', self.apply(plan))
        self.assertTrue(old.exists())

    def test_without_current_ui_task_keeps_latest_manifest(self):
        self.generated('older')
        latest = self.generated('latest')
        plan = self.preview(keep='')
        self.assertEqual(plan['keep_schema'], latest.name)
        self.assertNotIn(latest.as_posix(), [f['path'] for f in plan['files']])

    def test_build_outside_project_is_rejected(self):
        self.env['BUILD_SUBDIR'] = '../external'
        self.assertIn('error', self.preview())

    def test_shared_job_overwritten_by_another_build_is_not_archived(self):
        self.generated('old')
        job = self.job_path('old')
        job.write_text(job.read_text(encoding='utf-8').replace('PLATFORM_BUILD_SUBDIR="build"',
                                                             'PLATFORM_BUILD_SUBDIR="build-release"'), encoding='utf-8')
        plan = self.preview()
        self.assertNotIn(job.as_posix(), [f['path'] for f in plan['files']])
        self.assertTrue(self.apply(plan)['ok'])
        self.assertTrue(job.exists())

    def test_cleanup_keeps_same_schema_launch_for_another_build(self):
        self.generated('old')
        other = dict(self.env, BUILD_SUBDIR='build-release')
        core.sync_vs_launch(other, 'old.xml', 'pred', '1', 'outdoor')
        self.assertTrue(self.apply(self.preview())['ok'])
        text = (self.project / '.vs/launch.vs.json').read_text(encoding='utf-8')
        self.assertIn('old.xml', text)
        self.assertIn('build-release/Bin', text)

    def test_legacy_shared_job_is_retained_even_when_last_generated_by_this_build(self):
        old = self.generated('old')
        scoped = self.job_path('old')
        legacy = self.jobs / 'web-old.env'
        scoped.replace(legacy)
        manifest_path = Path(str(old) + '.manifest.json')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['job_file'] = legacy.as_posix()
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        sibling = self.project / 'build-release/Bin/runtimelibrary'
        sibling.mkdir(parents=True)
        (sibling / 'old.xml.manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        plan = self.preview()
        self.assertNotIn(legacy.as_posix(), [f['path'] for f in plan['files']])
        self.assertTrue(self.apply(plan)['ok'])
        self.assertTrue(legacy.exists())


if __name__ == '__main__':
    unittest.main()
