from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core
from resource_lock import ResourceLease
from run_guard import RuntimeGuard, RuntimeBusy
from server import Api


class IndoorSourceLockTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name) / 'same-project'
        self.project.mkdir()
        self.source = self.project / 'Propagation/Frame/src/PathLossofIndoorEngine.cpp'
        self.source.parent.mkdir(parents=True)
        self.original = (b'#if false\n'
            b'std::string filePath = m_calcParams.pathlossDirectory + "/building.txt";\n'
            b'pBuilding->Export(filePath.c_str());\n#endif\n')
        self.source.write_bytes(self.original)
        self.first = {'project': str(self.project), 'source_project': str(self.project),
                      'bin_dir': str(self.project / 'build-a/Bin'),
                      'out_dir': str(self.project / 'out-a')}
        self.second = {'project': str(self.project), 'source_project': str(self.project),
                       'bin_dir': str(self.project / 'build-b/Bin'),
                       'out_dir': str(self.project / 'out-b')}

    def test_same_source_project_conflicts_across_distinct_binary_and_output_directories(self):
        first, second = RuntimeGuard(), RuntimeGuard()
        with first.operation('build-a', self.first) as a:
            first.acquire_resources(a, self.first)
            with second.operation('enable-source', self.second) as b:
                with self.assertRaises(RuntimeBusy) as caught:
                    second.acquire_resources(b, self.second)
                self.assertTrue(caught.exception.owner['external'])
        self.assertFalse(first.snapshot()['busy'])
        self.assertFalse(second.snapshot()['busy'])

    def test_source_project_is_opt_in_for_regular_run_resources(self):
        first, second = RuntimeGuard(), RuntimeGuard()
        context_a = {key: value for key, value in self.first.items() if key != 'source_project'}
        context_b = {key: value for key, value in self.second.items() if key != 'source_project'}
        with first.operation('run-a', context_a) as a, second.operation('run-b', context_b) as b:
            first.acquire_resources(a, context_a)
            second.acquire_resources(b, context_b)
            self.assertTrue(first.snapshot()['busy'])
            self.assertTrue(second.snapshot()['busy'])

    def test_other_instance_project_source_lease_blocks_enable_before_writing(self):
        env = {'PROJECT_DIR': str(self.project), 'BUILD_SUBDIR': 'build-b',
               'OUT_ROOT': str(self.project / 'out-b')}
        guard = RuntimeGuard()
        with patch.object(core, 'RUNTIME', guard), patch.object(core, 'load_env', return_value=env):
            status = Api.indoor_building_export({})
            with ResourceLease([self.project], owner={'label': 'other configuration build'}):
                response = Api.enable_indoor_building_export({'revision': status['revision']})
        self.assertEqual(response.get('code'), 'RUNTIME_BUSY')
        self.assertTrue(response['runtime']['external'])
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse(Path(str(self.source) + '.bak').exists())

    def test_runtime_probe_reports_the_project_source_owner(self):
        env = {'PROJECT_DIR': str(self.project), 'BUILD_SUBDIR': 'build-b',
               'OUT_ROOT': str(self.project / 'out-b')}
        with patch.object(core, 'RUNTIME', RuntimeGuard()), \
                ResourceLease([self.project], owner={'label': 'other configuration build'}):
            state = core.runtime_state(env)
        self.assertTrue(state['busy'])
        self.assertTrue(state['external'])


if __name__ == '__main__':
    unittest.main()
