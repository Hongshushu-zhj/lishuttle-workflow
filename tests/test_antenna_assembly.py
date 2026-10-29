from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core
from server import Api


class AntennaAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime_xml = self.root / "job.xml"
        self.runtime_xml.write_text('<RuntimeSchema name="job"><PathlossDirectory>outputs</PathlossDirectory></RuntimeSchema>', encoding="utf-8")
        self.tasks = self.root / 'tasks'
        self.task = self.tasks / 'task'
        self.task.mkdir(parents=True)
        self.env = dict(GONGCAN_ROOT=str(self.tasks), PROJECT_DIR=self.root.as_posix(),
                        BUILD_SUBDIR='build', CONFIG_SRC='config')

    def create(self, directory):
        folder = self.task / directory
        (folder / 'nested').mkdir(parents=True)
        (folder / 'antenna.xml').write_text('<AntennaSettings/>')
        (folder / 'beam.txt').write_bytes(b'beam-data')
        (folder / 'nested/beam.txt').write_bytes(b'nested-data')
        with patch.object(core, 'load_env', return_value=self.env):
            return core.scan_tasks()[0][0]

    def test_both_directory_names_copy_full_tree_and_backup(self):
        for name in ('antenna', 'antennas'):
            with self.subTest(name=name):
                task = self.create(name)
                destination = self.root / 'build/Bin/antennas'
                destination.mkdir(parents=True, exist_ok=True)
                (destination / 'beam.txt').write_bytes(b'previous')
                actions = core.assemble_files(task, self.env, groups=('antenna',))
                self.assertEqual((destination / 'beam.txt').read_bytes(), b'beam-data')
                self.assertEqual((destination / 'beam.txt.bak').read_bytes(), b'previous')
                self.assertEqual((destination / 'nested/beam.txt').read_bytes(), b'nested-data')
                self.assertEqual((destination / 'antenna.xml').read_text(), '<AntennaSettings/>')
                self.assertFalse((self.root / 'build/Bin/models').exists())
                self.assertTrue(actions)

    def test_disabled_antenna_group_keeps_existing_files_untouched(self):
        task = self.create('antenna')
        destination = self.root / 'build/Bin/antennas'
        destination.mkdir(parents=True)
        (destination / 'antenna.xml').write_bytes(b'keep')
        core.assemble_files(task, self.env, groups=())
        self.assertEqual((destination / 'antenna.xml').read_bytes(), b'keep')
        self.assertFalse((destination / 'beam.txt').exists())

    def test_scanner_only_reports_available_antenna_files(self):
        with patch.object(core, 'load_env', return_value=self.env):
            self.assertFalse(core.scan_tasks()[0][0]['has_antennas'])
        (self.task / 'antennas').mkdir()
        with patch.object(core, 'load_env', return_value=self.env):
            self.assertFalse(core.scan_tasks()[0][0]['has_antennas'])
        (self.task / 'antennas/beam.txt').write_text('data')
        with patch.object(core, 'load_env', return_value=self.env):
            self.assertTrue(core.scan_tasks()[0][0]['has_antennas'])

    def test_existing_schema_can_independently_assemble_antennas(self):
        task = self.create('antenna')
        preview = dict(token='token', runtime_name='name', out_dir='out', changes=[], warnings=[])
        with patch.object(core, 'scan_tasks', return_value=([task], str(self.tasks))), \
                patch.object(core, 'preview_task_schema', return_value=preview), \
                patch.object(core, 'build_job_env', return_value='job.env'), \
                patch.object(core, 'run_render', return_value=(0, '')), \
                patch.object(core, 'ensure_runtime_resources', return_value={}), \
                patch.object(core, 'schema_path', return_value=str(self.runtime_xml)), \
                patch.object(core, 'load_env', return_value=self.env), \
                patch.object(core, 'assemble_files', return_value=[]) as assemble:
            body = dict(job_name='job', task=task, use_existing_schema=True,
                        preview_token='token', copy_antennas=True, copy_files=False)
            Api.render(body)
            assemble.assert_called_once_with(task, self.env, groups=('antenna',))
            assemble.reset_mock()
            Api.render(dict(body, copy_antennas=False))
            assemble.assert_not_called()
            task['has_antennas'] = False
            Api.render(body)
            assemble.assert_not_called()


if __name__ == '__main__':
    unittest.main()
