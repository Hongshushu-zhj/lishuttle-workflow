import inspect
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
from managed_process import ManagedProcess


@unittest.skipUnless(os.name == 'nt', 'Windows Job Object and MSVC helper lifecycle')
class BuildProcessReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='build helper-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.toolchain = self.root / 'Visual Studio'
        self.bin = self.toolchain / 'VC/Tools/MSVC/14.44.35207/bin/Hostx64/x64'
        self.bin.mkdir(parents=True)

    def start(self, helper_name='mspdbsrv.exe', build=True, trusted=True, worker=False):
        helper = (self.bin if trusted else self.root / 'untrusted') / helper_name
        helper.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(os.environ['SystemRoot']) / 'System32/cmd.exe', helper)
        # A controlled process with an inherited output handle. It performs no
        # compilation and exits only when the owning test's Job is reclaimed.
        daemon = self.root / 'helper.bat'
        daemon.write_text('@echo off\n:wait\ngoto wait\n', encoding='ascii')
        release = self.root / 'release-worker'
        product = self.root / 'worker-finished'
        worker_source = self.root / 'worker.py'
        worker_source.write_text(
            'from pathlib import Path\nimport sys,time\n'
            'while not Path(sys.argv[1]).exists(): time.sleep(.02)\n'
            'Path(sys.argv[2]).write_text("finished")\n', encoding='utf-8')
        source = self.root / 'root.py'
        source.write_text(
            'import subprocess,sys\nfrom pathlib import Path\n'
            f'p=subprocess.Popen([{str(helper)!r},"/d","/q","/c",{str(daemon)!r}],'
            'stdout=sys.stdout,stderr=sys.stderr)\n'
            f'Path({str(self.root / "helper.pid")!r}).write_text(str(p.pid))\n'
            + (f'subprocess.Popen([sys.executable,{str(worker_source)!r},{str(release)!r},{str(product)!r}],'
               'stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n' if worker else '')
            + 'print("BUILD_LOG_COMPLETE",flush=True)\n', encoding='utf-8')
        # The legacy implementation lacks the opt-in. Running it unchanged
        # first reproduces EOF/Job retention rather than a signature failure.
        options = {}
        if build and 'build_toolchain_root' in inspect.signature(ManagedProcess).parameters:
            options['build_toolchain_root'] = str(self.toolchain)
        tree = ManagedProcess([sys.executable, '-u', str(source)], str(self.root), **options)
        done = threading.Event()
        lines, outcome = [], []
        def consume():
            try:
                lines.extend(line.strip() for line in tree.proc.stdout)
                outcome.append(tree.wait())
            finally:
                done.set()
        reader = threading.Thread(target=consume, daemon=True)
        reader.start()
        def cleanup():
            tree.terminate()
            reader.join(5)
            tree.proc.stdout.close()
            tree.close()
        self.addCleanup(cleanup)
        self.assertEqual(tree.proc.wait(timeout=5), 0)
        return tree, done, lines, outcome, release, product

    def test_completed_build_reaps_its_pdb_helper_and_releases_output_eof(self):
        tree, done, lines, outcome, _, _ = self.start()
        self.assertTrue(done.wait(2), 'root已退出，但MSVC辅助进程占住日志EOF和Job')
        self.assertEqual(outcome, [0])
        self.assertIn('BUILD_LOG_COMPLETE', lines)
        self.assertFalse(tree.active())

    def test_completed_build_reaps_its_telemetry_helper(self):
        _, done, _, outcome, _, _ = self.start(helper_name='vctip.exe')
        self.assertTrue(done.wait(2), '编译遥测辅助进程不应无限占住已结束编译')
        self.assertEqual(outcome, [0])

    def test_real_worker_keeps_job_owned_even_after_root_and_completion_log(self):
        tree, done, _, outcome, release, product = self.start(worker=True)
        self.assertFalse(done.wait(.25), '仍有真实工作进程时不能回收Job')
        self.assertTrue(tree.active())
        self.assertFalse(product.exists())
        release.touch()
        self.assertTrue(done.wait(2), '真实工作结束后才允许回收辅助进程')
        self.assertTrue(product.exists())
        self.assertEqual(outcome, [0])

    def test_non_build_keeps_identical_helpers_until_explicit_cancel(self):
        tree, done, _, _, _, _ = self.start(build=False)
        self.assertFalse(done.wait(.25))
        self.assertTrue(tree.active())

    def test_same_process_name_outside_the_selected_toolchain_is_not_reaped(self):
        tree, done, _, _, _, _ = self.start(trusted=False)
        self.assertFalse(done.wait(.25))
        self.assertTrue(tree.active())

    def test_compiler_process_itself_is_never_treated_as_persistent_helper(self):
        tree, done, _, _, _, _ = self.start(helper_name='cl.exe')
        self.assertFalse(done.wait(.25))
        self.assertTrue(tree.active())

    def test_reclaiming_one_build_leaves_another_job_helpers_alive(self):
        other, other_done, _, _, _, _ = self.start(helper_name='vctip.exe', build=False)
        tree, done, _, _, _, _ = self.start(helper_name='mspdbsrv.exe')
        self.assertTrue(done.wait(2))
        self.assertFalse(tree.active())
        self.assertFalse(other_done.is_set())
        self.assertTrue(other.active(), '不能全局按辅助进程名终止其他Job')

    def test_helper_identity_query_failure_is_visible_and_never_releases_early(self):
        with patch.object(ManagedProcess, '_windows_process_image', side_effect=OSError('fixture query failure')):
            tree, done, _, _, _, _ = self.start()
            self.assertFalse(done.wait(.25))
            self.assertTrue(tree.active())
            self.assertIn('fixture query failure', tree.cleanup_error)
        self.assertTrue(done.wait(2))
        self.assertEqual(tree.cleanup_error, '', '查询恢复并完成收尾后清除暂时错误')


if __name__ == '__main__':
    unittest.main()
