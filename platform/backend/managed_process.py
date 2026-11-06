"""Own the process tree, including children whose original parent has exited."""

import os
import signal
import subprocess
import time


class ManagedProcess:
    def __init__(self, cmd, cwd, env=None):
        self.job = None
        self.proc = None
        options = dict(cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, encoding='gbk', errors='replace', shell=False, env=env)
        if os.name == 'nt':
            self._windows_job()
            try:
                # Assign before any engine/build code can spawn unowned children.
                self.proc = subprocess.Popen(cmd, creationflags=0x4 | subprocess.CREATE_NEW_PROCESS_GROUP, **options)
                if not self.kernel.AssignProcessToJobObject(self.job, int(self.proc._handle)):
                    raise self.ctypes.WinError(self.ctypes.get_last_error())
                ntdll = self.ctypes.WinDLL('ntdll')
                ntdll.NtResumeProcess.argtypes = [self.wintypes.HANDLE]
                ntdll.NtResumeProcess.restype = self.wintypes.LONG
                status = ntdll.NtResumeProcess(int(self.proc._handle))
                if status < 0:
                    raise OSError(f'无法恢复受管进程：NTSTATUS {status:#x}')
            except BaseException:
                if self.proc is not None:
                    self.proc.kill()
                    self.proc.wait()
                    if self.proc.stdout:
                        self.proc.stdout.close()
                self.close()
                raise
        else:
            self.proc = subprocess.Popen(cmd, start_new_session=True, **options)

    def _windows_job(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes, self.wintypes = ctypes, wintypes
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)

        class Limits(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', wintypes.DWORD), ('min_working', ctypes.c_size_t),
                        ('max_working', ctypes.c_size_t), ('active_limit', wintypes.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                        ('scheduling', wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                        ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [('basic', Limits), ('io', IO), ('process_memory', ctypes.c_size_t),
                        ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t),
                        ('peak_job', ctypes.c_size_t)]

        class Accounting(ctypes.Structure):
            _fields_ = [(name, ctypes.c_int64) for name in
                        ('user_time', 'kernel_time', 'period_user', 'period_kernel')] + [
                            ('faults', wintypes.DWORD), ('total', wintypes.DWORD),
                            ('active', wintypes.DWORD), ('terminated', wintypes.DWORD)]

        self.Accounting = Accounting
        api = self.kernel
        api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        api.CreateJobObjectW.restype = wintypes.HANDLE
        api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        api.SetInformationJobObject.restype = wintypes.BOOL
        api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        api.AssignProcessToJobObject.restype = wintypes.BOOL
        api.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                  wintypes.DWORD, ctypes.c_void_p]
        api.QueryInformationJobObject.restype = wintypes.BOOL
        api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        api.TerminateJobObject.restype = wintypes.BOOL
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        api.CloseHandle.restype = wintypes.BOOL
        self.job = api.CreateJobObjectW(None, None)
        if not self.job:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not api.SetInformationJobObject(self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def active(self):
        if os.name == 'nt':
            accounting = self.Accounting()
            if not self.kernel.QueryInformationJobObject(self.job, 1, self.ctypes.byref(accounting),
                                                          self.ctypes.sizeof(accounting), None):
                raise self.ctypes.WinError(self.ctypes.get_last_error())
            return accounting.active > 0
        try:
            os.killpg(self.proc.pid, 0)
            return True
        except ProcessLookupError:
            return False

    def terminate(self):
        if os.name == 'nt':
            if not self.kernel.TerminateJobObject(self.job, 1):
                raise self.ctypes.WinError(self.ctypes.get_last_error())
        else:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def wait(self):
        code = self.proc.wait()
        while self.active():
            time.sleep(.05)
        return code

    def close(self):
        if self.job:
            self.kernel.CloseHandle(self.job)
            self.job = None
