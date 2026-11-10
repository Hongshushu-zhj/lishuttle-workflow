"""Own the process tree, including children whose original parent has exited."""

import os
import re
import signal
import subprocess
import threading
import time


class ManagedProcess:
    def __init__(self, cmd, cwd, env=None, build_toolchain_root=None):
        self.job = None
        self.proc = None
        self.cleanup_error = ''
        self._build_monitor = None
        self._build_stop = threading.Event()
        self._build_toolchain = (os.path.normcase(os.path.realpath(build_toolchain_root))
                                 if build_toolchain_root else None)
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
                if self._build_toolchain:
                    # Compiler services can inherit the output pipe, so a
                    # reader waiting for EOF cannot perform this cleanup.
                    self._build_monitor = threading.Thread(target=self._finish_build_helpers, daemon=True)
                    self._build_monitor.start()
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
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                  wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        api.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.job = api.CreateJobObjectW(None, None)
        if not self.job:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not api.SetInformationJobObject(self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def _windows_process_ids(self):
        """Enumerate members of this Job, never a global process-name list."""
        capacity = 64
        while capacity <= 65536:
            class ProcessIds(self.ctypes.Structure):
                _fields_ = [('assigned', self.wintypes.DWORD), ('count', self.wintypes.DWORD),
                            ('ids', self.ctypes.c_size_t * capacity)]
            data = ProcessIds()
            if self.kernel.QueryInformationJobObject(self.job, 3, self.ctypes.byref(data),
                                                       self.ctypes.sizeof(data), None):
                return list(data.ids[:data.count])
            error = self.ctypes.get_last_error()
            if error != 234:  # ERROR_MORE_DATA when the process list grew.
                raise self.ctypes.WinError(error)
            capacity = max(capacity * 2, data.assigned)
        raise OSError('受管进程数量超过安全枚举上限')

    def _windows_process_image(self, pid):
        handle = self.kernel.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION only.
        if not handle:
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        try:
            buffer = self.ctypes.create_unicode_buffer(32768)
            length = self.wintypes.DWORD(len(buffer))
            if not self.kernel.QueryFullProcessImageNameW(handle, 0, buffer, self.ctypes.byref(length)):
                raise self.ctypes.WinError(self.ctypes.get_last_error())
            return buffer.value
        finally:
            self.kernel.CloseHandle(handle)

    def _is_build_helper(self, pid):
        image = os.path.normcase(os.path.realpath(self._windows_process_image(pid)))
        base = os.path.join(self._build_toolchain, 'VC', 'Tools', 'MSVC')
        try:
            relative = os.path.relpath(image, base).replace('\\', '/')
        except ValueError:
            return False
        # Only these two persistent MSVC services are safe to reclaim after
        # the build root exits. Compiler/linker and arbitrary same-name tools
        # remain owned and must finish or be explicitly cancelled.
        return bool(re.fullmatch(r'\d+(?:\.\d+)*/bin/Host(?:x86|x64)/(?:x86|x64|arm|arm64)/'
                                 r'(?:mspdbsrv|vctip)\.exe', relative, re.I))

    def _finish_build_helpers(self):
        try:
            self.proc.wait()
        except Exception as exc:
            self.cleanup_error = f'等待编译主进程退出失败：{exc}'
            return
        while not self._build_stop.is_set():
            try:
                members = self._windows_process_ids()
                if not members:
                    self.cleanup_error = ''
                    return
                if all(self._is_build_helper(pid) for pid in members):
                    # Terminate only our own Job. This closes inherited output
                    # handles and leaves other builds' compiler services alone.
                    self.terminate()
                    self.cleanup_error = ''
                    return
                self.cleanup_error = ''
            except Exception as exc:
                # Query failures are never permission to release a live tree.
                self.cleanup_error = f'编译辅助进程收尾未完成：{exc}'
            self._build_stop.wait(.05)

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
        self._build_stop.set()
        if self.job:
            self.kernel.CloseHandle(self.job)
            self.job = None
        monitor = self._build_monitor
        if monitor and monitor is not threading.current_thread() and monitor.ident is not None:
            monitor.join(.2)
