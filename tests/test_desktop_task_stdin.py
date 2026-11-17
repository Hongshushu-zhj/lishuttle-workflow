"""Tasks must not inherit the desktop service's live lifecycle input pipe."""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
import json, os, sys, threading, time
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from core import Runner
from run_guard import RuntimeGuard

entered = threading.Event()
def control_reader():
    entered.set()
    os.read(sys.stdin.fileno(), 1)
threading.Thread(target=control_reader, daemon=True).start()
entered.wait()
# The host keeps this pipe open, exactly as the desktop lifecycle does.
time.sleep(.1)
runner = Runner(guard=RuntimeGuard())
request = json.loads(sys.argv[3])
sid = runner.start(request['command'], request['cwd'], 'fixture')
try:
    completed = runner.sessions[sid]['done_event'].wait(3)
    if not completed:
        runner.stop(sid)
        runner.sessions[sid]['done_event'].wait(3)
    result = runner.output(sid)
    print(json.dumps(dict(completed=completed, exit=result['exit'], lines=result['lines'],
                          busy=runner.guard.snapshot()['busy'])), flush=True)
finally:
    runner.shutdown()
'''


@unittest.skipUnless(os.name == 'nt', 'Windows inherited pipe startup regression')
class DesktopTaskStdinTests(unittest.TestCase):
    def run_under_live_control_pipe(self, command, cwd):
        process = subprocess.Popen(
            [sys.executable, '-B', '-u', '-c', HARNESS,
             str(ROOT / 'platform/backend'), str(ROOT / 'scripts'),
             json.dumps(dict(command=command, cwd=str(cwd)))],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        messages = queue.Queue()
        reader = threading.Thread(target=lambda: messages.put(process.stdout.readline()), daemon=True)
        reader.start()
        try:
            # Do not use communicate() here: it would close stdin and hide the bug.
            line = messages.get(timeout=12)
            self.assertTrue(line, 'harness exited without reporting a result')
            result = json.loads(line)
            self.assertTrue(result['completed'],
                            'task blocked on the desktop lifecycle input pipe: ' + str(result))
            self.assertFalse(result['busy'], result)
            return result
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            stderr = process.stderr.read().decode('utf-8', errors='replace')
            for pipe in (process.stdout, process.stderr):
                pipe.close()
            reader.join(timeout=1)
            self.assertEqual(process.returncode, 0, stderr)

    def test_python_task_receives_eof_without_reading_desktop_control(self):
        code = ('import sys; assert sys.stdin.read() == ""; '
                'print("TASK_INPUT_EOF", flush=True)')
        result = self.run_under_live_control_pipe([sys.executable, '-B', '-c', code], ROOT)
        self.assertEqual(result['exit'], 0)
        self.assertIn('TASK_INPUT_EOF', result['lines'])

    def test_batch_validation_completes_with_desktop_control_reader_active(self):
        with tempfile.TemporaryDirectory(prefix='桌面 管道 ') as temporary:
            root = Path(temporary)
            scripts = root / 'scripts'
            scripts.mkdir()
            for name in ('build_local.bat', 'doctor_local.bat', 'stage_local.bat',
                         'run_local.bat', 'validate_local_python.bat'):
                shutil.copy2(ROOT / 'scripts' / name, scripts / name)
            # Successful validation stops here before any project/config access.
            (scripts / 'load_local_env.bat').write_text(
                '@echo off\necho VALIDATION_REACHED_LOADER\nexit /b 83\n', encoding='ascii')
            (scripts / 'run_local.py').write_text(
                'print("VALIDATION_REACHED_RUN", flush=True)\nraise SystemExit(83)\n',
                encoding='ascii')
            for name in ('build', 'doctor', 'stage', 'run'):
                with self.subTest(entrypoint=name):
                    # The harness inherits the selected interpreter just as the
                    # desktop host does; PATH need not contain Python.
                    command = [os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c',
                               str(scripts / (name + '_local.bat'))]
                    old = os.environ.get('LISHUTTLE_PYTHON')
                    os.environ['LISHUTTLE_PYTHON'] = sys.executable
                    try:
                        result = self.run_under_live_control_pipe(command, root)
                    finally:
                        if old is None:
                            os.environ.pop('LISHUTTLE_PYTHON', None)
                        else:
                            os.environ['LISHUTTLE_PYTHON'] = old
                    self.assertEqual(result['exit'], 83 if name == 'run' else 1)
                    expected = 'VALIDATION_REACHED_RUN' if name == 'run' else 'VALIDATION_REACHED_LOADER'
                    self.assertIn(expected, result['lines'])


if __name__ == '__main__':
    unittest.main()
