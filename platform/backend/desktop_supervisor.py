"""Own the desktop Python service and its descendants, relaying pipe JSON.

On Windows assignment happens while the service is suspended. Closing this
supervisor's Job handle kills only its service tree, including on host death.
Normal stdin EOF is forwarded first and waits for domain/archive finalization.
"""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from desktop_entry import MAX_CONTROL, read_bootstrap
from managed_process import ManagedProcess


class ControlPipe:
    """Read the host pipe without holding Python's buffered stdin lock.

    The input relay may still be waiting when a failed service exits. A daemon
    thread blocked in os.read can then exit without locking interpreter teardown.
    """
    def __init__(self, descriptor):
        self.descriptor = descriptor
        self.pending = bytearray()

    def readline(self):
        while b'\n' not in self.pending and len(self.pending) <= MAX_CONTROL:
            chunk = os.read(self.descriptor, 4096)
            if not chunk:
                result = bytes(self.pending)
                self.pending.clear()
                return result
            self.pending.extend(chunk)
        end = self.pending.find(b'\n') + 1
        if not end or end > MAX_CONTROL:
            end = MAX_CONTROL + 1
        result = bytes(self.pending[:end])
        del self.pending[:end]
        return result


class ServiceProcess(ManagedProcess):
    """Reuse the existing native Job implementation with dedicated control IO."""
    def __init__(self, cmd, cwd, env=None):
        self.job = None
        self.proc = None
        self._assigned = False
        self._build_stop = threading.Event()
        self._build_monitor = None
        options = dict(cwd=cwd, env=env, stdin=subprocess.PIPE,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       shell=False, close_fds=True)
        try:
            if os.name == 'nt':
                self._windows_job()
                self.proc = subprocess.Popen(cmd, creationflags=0x4 | subprocess.CREATE_NEW_PROCESS_GROUP, **options)
                if not self.kernel.AssignProcessToJobObject(self.job, int(self.proc._handle)):
                    raise self.ctypes.WinError(self.ctypes.get_last_error())
                self._assigned = True
                ntdll = self.ctypes.WinDLL('ntdll')
                ntdll.NtResumeProcess.argtypes = [self.wintypes.HANDLE]
                ntdll.NtResumeProcess.restype = self.wintypes.LONG
                status = ntdll.NtResumeProcess(int(self.proc._handle))
                if status < 0:
                    raise OSError('Cannot resume supervised service')
            else:
                self.proc = subprocess.Popen(cmd, start_new_session=True, **options)
        except BaseException:
            self.close()
            raise

    def close(self):
        try:
            if self.proc is not None and self.proc.poll() is None:
                if (self.job and self._assigned) or os.name != 'nt':
                    self.terminate()
                else:
                    # An assignment failure leaves the new child suspended and
                    # outside our Job. Only direct termination can reap it.
                    self.proc.kill()
                self.proc.wait(timeout=5)
        finally:
            super().close()
            if self.proc is not None:
                for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
                    if stream and not stream.closed:
                        stream.close()


def main():
    owner = None
    outputs = []
    bootstrap = {}
    try:
        control = ControlPipe(sys.stdin.fileno())
        raw = control.readline()
        bootstrap = read_bootstrap(io.StringIO(raw.decode('utf-8')))
        owner = ServiceProcess([sys.executable, '-B', '-u', str(Path(__file__).with_name('desktop_entry.py'))],
                               bootstrap['resource_root'])
        child = owner.proc
        child.stdin.write(raw)
        child.stdin.flush()

        def forward_input():
            try:
                while True:
                    line = control.readline()
                    if not line or len(line) > MAX_CONTROL or not line.endswith(b'\n'):
                        break
                    child.stdin.write(line)
                    child.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass
            finally:
                try:
                    child.stdin.close()
                except (BrokenPipeError, OSError, ValueError):
                    pass

        def forward_output(source, target):
            try:
                while True:
                    line = source.readline()
                    if not line:
                        break
                    target.write(line)
                    target.flush()
            except (BrokenPipeError, OSError, ValueError):
                # Host disappearance must initiate graceful cleanup as EOF does.
                try:
                    child.stdin.close()
                except (BrokenPipeError, OSError, ValueError):
                    pass

        threading.Thread(target=forward_input, name='desktop-control', daemon=True).start()
        for source, target in ((child.stdout, sys.stdout.buffer), (child.stderr, sys.stderr.buffer)):
            thread = threading.Thread(target=forward_output, args=(source, target), name='desktop-relay')
            thread.start()
            outputs.append(thread)
        try:
            code = child.wait()
        except KeyboardInterrupt:
            child.stdin.close()
            code = child.wait()
        for thread in outputs:
            thread.join()
        return code
    except Exception as exc:
        # Never include bootstrap text or credentials in the diagnostic channel.
        detail = str(exc)
        secret = bootstrap.get('session_secret')
        if secret:
            detail = detail.replace(secret, '[redacted]')
        sys.stderr.write('Desktop supervisor startup: ' + type(exc).__name__ + ': ' + detail[:1000] + '\n')
        sys.stderr.flush()
        sys.stdout.write(json.dumps(dict(type='error', code='SUPERVISOR_FAILED', message='Desktop service could not start')) + '\n')
        sys.stdout.flush()
        return 1
    finally:
        if owner is not None:
            owner.close()


if __name__ == '__main__':
    raise SystemExit(main())
