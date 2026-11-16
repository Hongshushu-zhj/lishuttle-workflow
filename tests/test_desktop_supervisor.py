"""Exercise bootstrap/control pipes with disposable service state only."""
import importlib.util
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


class DesktopLifecycleTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt','Windows Job assignment failure')
    def test_failed_job_assignment_kills_suspended_child_and_closes_handles(self):
        sys.path.insert(0,str(ROOT/'platform/backend'))
        from desktop_supervisor import ServiceProcess
        killed = []
        process = Mock(_handle=123,returncode=None)
        process.poll.return_value = None
        process.kill.side_effect = lambda:killed.append(True)
        for stream in (process.stdin,process.stdout,process.stderr):
            stream.closed = False
        def wait(timeout=None):
            if not killed:
                raise TimeoutError('unowned suspended child must be killed directly before waiting')
            self.assertIsNotNone(timeout,'construction-failure wait must be bounded')
            process.returncode = 1
            return 1
        process.wait.side_effect = wait
        kernel = SimpleNamespace(AssignProcessToJobObject=Mock(return_value=False),
                                 TerminateJobObject=Mock(return_value=True),CloseHandle=Mock())
        def job(owner):
            owner.job = 456
            owner.kernel = kernel
            owner.ctypes = SimpleNamespace(WinError=lambda code:OSError('assignment refused'),get_last_error=lambda:5)
        with patch.object(ServiceProcess,'_windows_job',job),patch('desktop_supervisor.subprocess.Popen',return_value=process):
            with self.assertRaisesRegex(OSError,'assignment refused'):
                ServiceProcess(['fixture-only'],ROOT)
        process.kill.assert_called_once()
        process.wait.assert_called_once()
        kernel.TerminateJobObject.assert_not_called()
        kernel.CloseHandle.assert_called_once_with(456)
        for stream in (process.stdin,process.stdout,process.stderr):
            stream.close.assert_called_once()

    def test_owned_service_pipe_and_job_cleanup(self):
        sys.path.insert(0,str(ROOT/'platform/backend'))
        self.assertIsNotNone(importlib.util.find_spec('desktop_supervisor'), 'native supervisor is required')
        from desktop_supervisor import ServiceProcess
        owner = ServiceProcess([sys.executable,'-u','-c','import sys;print(sys.stdin.readline().strip(),flush=True)'],ROOT)
        self.addCleanup(owner.close)
        owner.proc.stdin.write(b'fixture\n')
        owner.proc.stdin.flush()
        self.assertEqual(owner.proc.stdout.readline().strip(),b'fixture')
        self.assertEqual(owner.proc.wait(timeout=5),0)

    def test_owner_close_terminates_only_owned_descendant_tree(self):
        sys.path.insert(0,str(ROOT/'platform/backend'))
        self.assertIsNotNone(importlib.util.find_spec('desktop_supervisor'), 'native supervisor is required')
        from desktop_supervisor import ServiceProcess
        from run_history import _pid_alive
        code = ('import subprocess,sys,time;'
                'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);'
                'print(p.pid,flush=True);time.sleep(60)')
        owner = ServiceProcess([sys.executable,'-u','-c',code],ROOT)
        self.addCleanup(owner.close)
        pid = int(owner.proc.stdout.readline().strip())
        self.assertTrue(_pid_alive(pid))
        owner.close()
        deadline = time.monotonic()+5
        while _pid_alive(pid) and time.monotonic()<deadline:
            threading.Event().wait(.025)
        self.assertFalse(_pid_alive(pid))

    def test_bootstrap_rejects_static_files_outside_installation(self):
        sys.path.insert(0,str(ROOT/'platform/backend'))
        self.assertIsNotNone(importlib.util.find_spec('desktop_entry'))
        import desktop_entry
        import io
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            resource = base/'resource'
            resource.mkdir()
            payload = dict(data_dir=str(base/'data'),resource_root=str(resource),static_dir=str(base),session_secret='a'*48,cookie_name='fixture')
            with self.assertRaises(ValueError):
                desktop_entry.read_bootstrap(io.StringIO(json.dumps(payload)+'\n'))

    def spawn(self, entry='desktop_entry.py'):
        path = ROOT / 'platform/backend' / entry
        self.assertTrue(path.is_file(), 'supervised desktop entry is required')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        resource = root/'resource'
        static = resource/'static'
        static.mkdir(parents=True)
        (static / 'index.html').write_text('temporary desktop fixture')
        proc = subprocess.Popen([sys.executable,'-u',str(path)],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
        def cleanup():
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
            for pipe in (proc.stdin,proc.stdout,proc.stderr):
                if pipe and not pipe.closed:
                    pipe.close()
        self.addCleanup(cleanup)
        messages = queue.Queue()
        def read():
            for line in proc.stdout:
                messages.put(line)
        threading.Thread(target=read,daemon=True).start()
        bootstrap = dict(data_dir=str(root/'data'),static_dir=str(static),resource_root=str(resource),session_secret='fixture-'+'a'*48,cookie_name='fixture_session')
        proc.stdin.write(json.dumps(bootstrap)+'\n')
        proc.stdin.flush()
        return proc,messages

    def message(self,messages):
        return json.loads(messages.get(timeout=12))

    def test_entry_bootstrap_activity_and_graceful_shutdown(self):
        proc,messages = self.spawn()
        ready = self.message(messages)
        self.assertEqual(ready['type'],'ready')
        self.assertRegex(ready['origin'],r'^http://127\.0\.0\.1:[0-9]+$')
        proc.stdin.write('{"type":"activity","request_id":"fixture"}\n')
        proc.stdin.flush()
        activity = self.message(messages)
        self.assertEqual((activity['type'],activity['request_id'],activity['busy']),('activity','fixture',False))
        self.assertNotIn('session_secret',json.dumps(activity))
        proc.stdin.write('{"type":"shutdown","request_id":"close"}\n')
        proc.stdin.flush()
        self.assertEqual(self.message(messages),dict(type='shutdown',request_id='close',status='stopped'))
        self.assertEqual(proc.wait(timeout=12),0)

    def test_entry_eof_stops_service(self):
        proc,messages = self.spawn()
        self.assertEqual(self.message(messages)['type'],'ready')
        proc.stdin.close()
        self.assertEqual(proc.wait(timeout=12),0)

    def test_supervisor_relays_control_and_stops_on_eof(self):
        proc,messages = self.spawn('desktop_supervisor.py')
        self.assertEqual(self.message(messages)['type'],'ready')
        proc.stdin.write('{"type":"activity","request_id":"owner"}\n')
        proc.stdin.flush()
        self.assertEqual(self.message(messages)['request_id'],'owner')
        proc.stdin.close()
        self.assertEqual(proc.wait(timeout=15),0)


if __name__ == '__main__':
    unittest.main()
