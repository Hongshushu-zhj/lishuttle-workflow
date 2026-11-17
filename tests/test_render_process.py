"""Renderer ownership must permit bounded failure and safe desktop shutdown."""
import os
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))


class RenderProcessTests(unittest.TestCase):
    def controller(self):
        from render_process import RenderController
        controller = RenderController()
        self.addCleanup(controller.shutdown)
        return controller

    def test_child_input_is_eof_and_stdout_is_utf8(self):
        controller = self.controller()
        code = 'import sys; assert sys.stdin.read() == ""; print("renderer ready")'
        result = controller.run([sys.executable, '-B', '-c', code], cwd=Path.cwd(),
                                env=dict(os.environ), timeout=3)
        self.assertEqual(result.returncode, 0)
        self.assertIn('renderer ready', result.stdout)

    def test_timeout_stops_child_and_controller_can_run_again(self):
        controller = self.controller()
        with self.assertRaises(subprocess.TimeoutExpired):
            controller.run([sys.executable, '-B', '-c', 'import time;time.sleep(60)'],
                           cwd=Path.cwd(), env=dict(os.environ), timeout=.25)
        result = controller.run([sys.executable, '-B', '-c', 'print("retry ready")'],
                                cwd=Path.cwd(), env=dict(os.environ), timeout=3)
        self.assertEqual(result.returncode, 0)

    def test_shutdown_cancels_active_renderer_and_rejects_later_start(self):
        from render_process import RenderCancelled
        controller = self.controller()
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / 'started'
            errors = []
            def run():
                try:
                    code = 'from pathlib import Path;import sys,time;Path(sys.argv[1]).write_text("ready");time.sleep(60)'
                    controller.run([sys.executable, '-B', '-c', code, str(marker)],
                                   cwd=temporary, env=dict(os.environ), timeout=120)
                except Exception as exc:
                    errors.append(exc)
            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            deadline = time.monotonic() + 5
            while not marker.is_file() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(marker.is_file(), errors)
            controller.shutdown()
            thread.join(5)
            self.assertFalse(thread.is_alive(), 'shutdown must release the assembly request')
            self.assertEqual(len(errors), 1, errors)
            self.assertIsInstance(errors[0], RenderCancelled)
            with self.assertRaises(RenderCancelled):
                controller.run([sys.executable, '-c', 'print("must not start")'],
                               cwd=temporary, env=dict(os.environ), timeout=3)

    def test_desktop_shutdown_drains_assembly_after_rolling_back_its_transaction(self):
        import core
        import desktop_entry
        controller = self.controller()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            resource = root / 'resource'
            static = resource / 'static'
            static.mkdir(parents=True)
            (static / 'index.html').write_text('fixture')
            target, marker = root / 'assembly.xml', root / 'renderer-started'
            target.write_bytes(b'previous complete configuration')
            secret = 's' * 64
            results, events, request_errors = [], [], []
            request_thread = None
            create_server = desktop_entry.create_server

            def render(_):
                try:
                    with core.FileTransaction() as transaction:
                        transaction.write(target, b'partial new configuration')
                        controller.run([sys.executable, '-B', '-c',
                            'from pathlib import Path;import sys,time;Path(sys.argv[1]).write_text("ready");time.sleep(60)',
                            str(marker)], cwd=root, env=dict(os.environ), timeout=120)
                    return dict(generated=True)
                except ValueError:
                    return dict(generated=False, assembly_status='rolled_back')

            def listener(static, session_secret, cookie_name, routes):
                return create_server(static, session_secret, cookie_name,
                                     {('POST', 'fixture_render'): render})

            def emit(message):
                nonlocal request_thread
                events.append(message)
                if message.get('type') != 'ready':
                    return
                def request():
                    try:
                        req = urllib.request.Request(message['origin'] + '/api/fixture_render', data=b'{}',
                            headers={'Origin': message['origin'], 'Cookie': 'fixture=' + secret,
                                     'Content-Type': 'application/json'})
                        with urllib.request.urlopen(req, timeout=10) as response:
                            results.append(json.load(response))
                    except Exception as exc:
                        request_errors.append(exc)
                request_thread = threading.Thread(target=request, daemon=True)
                request_thread.start()
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(marker.exists(), request_errors)

            bootstrap = dict(data_dir=str(root / 'data'), resource_root=str(resource),
                             static_dir=str(static), session_secret=secret, cookie_name='fixture')
            class ProtocolOutput:
                def write(self, data):
                    emit(json.loads(data))
                    return len(data)
                def flush(self):
                    pass
            control = io.StringIO(json.dumps(bootstrap) + '\n' +
                                  json.dumps(dict(type='shutdown', request_id='close-active-assembly')) + '\n')
            with patch.dict(os.environ), patch.object(sys, 'stdin', control), \
                    patch.object(sys, 'stdout', ProtocolOutput()), \
                    patch.object(desktop_entry, 'create_server', side_effect=listener), \
                    patch.object(core, 'RUNNER', SimpleNamespace(shutdown=lambda: None)), \
                    patch.object(core, 'shutdown_renderers', side_effect=controller.shutdown):
                codes = []
                main_thread = threading.Thread(target=lambda: codes.append(desktop_entry.main()), daemon=True)
                main_thread.start()
                main_thread.join(7)
                completed = not main_thread.is_alive()
                # A failed regression still cleans its owned fixture process.
                controller.shutdown()
                main_thread.join(5)
                if request_thread:
                    request_thread.join(5)
            self.assertTrue(completed, 'desktop shutdown waited on a blocked assembly request')
            self.assertEqual(codes, [0], events)
            self.assertFalse(request_errors, request_errors)
            self.assertEqual(results, [dict(generated=False, assembly_status='rolled_back')])
            self.assertEqual(target.read_bytes(), b'previous complete configuration')
            self.assertIn(dict(type='shutdown', request_id='close-active-assembly', status='stopped'), events)

    @unittest.skipUnless(os.name == 'nt', 'Windows Job termination must drain descendant handles')
    def test_completed_renderer_waits_for_descendant_exit_before_returning(self):
        import ctypes
        from managed_process import ManagedProcess
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.WaitForSingleObject.restype = ctypes.c_ulong
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handles = []
        controller = self.controller()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target, marker = root / 'output.xml', root / 'descendant-pid'
            target.write_bytes(b'configuration before rollback')

            class ObservedProcess(ManagedProcess):
                child_handle = None

                def terminate(self):
                    if self.child_handle is None and marker.exists():
                        self.child_handle = kernel.OpenProcess(0x100000, False, int(marker.read_text()))
                        if not self.child_handle:
                            raise ctypes.WinError(ctypes.get_last_error())
                        handles.append(self.child_handle)
                    return super().terminate()

            child = ('from pathlib import Path;import os,sys,time;'
                     'held=open(sys.argv[1],"rb");'
                     'Path(sys.argv[2]).write_text(str(os.getpid()));time.sleep(60)')
            parent = ('from pathlib import Path;import subprocess,sys,time;'
                      'subprocess.Popen([sys.executable,"-B","-c",sys.argv[1],sys.argv[2],sys.argv[3]],'
                      'stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);'
                      'marker=Path(sys.argv[3]);deadline=time.monotonic()+3\n'
                      'while not marker.exists() and time.monotonic()<deadline:time.sleep(.001)\n'
                      'assert marker.exists();print("renderer complete")')
            try:
                with patch('render_process.ManagedProcess', ObservedProcess):
                    result = controller.run([sys.executable, '-B', '-c', parent, child,
                                             str(target), str(marker)],
                                            cwd=root, env=dict(os.environ), timeout=5)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(len(handles), 1)
                self.assertEqual(kernel.WaitForSingleObject(handles[0], 0), 0,
                                 'renderer returned before its descendant released its file handles')
                replacement = root / 'restored.xml'
                replacement.write_bytes(b'original configuration')
                os.replace(replacement, target)
            finally:
                for handle in handles:
                    kernel.WaitForSingleObject(handle, 5000)
                    kernel.CloseHandle(handle)
