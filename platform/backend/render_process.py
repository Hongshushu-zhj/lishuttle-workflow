"""Own short-lived configuration renderers separately from long-running tasks."""
import os
import subprocess
import threading
import time

from managed_process import ManagedProcess


class RenderCancelled(ValueError):
    pass


class RenderController:
    def __init__(self):
        self._lock = threading.RLock()
        self._owner = None
        self._closing = False
        self._process_handles = {}

    def _terminate(self, owner):
        with self._lock:
            if os.name == 'nt':
                owner.kernel.WaitForSingleObject.argtypes = [owner.wintypes.HANDLE, owner.wintypes.DWORD]
                owner.kernel.WaitForSingleObject.restype = owner.wintypes.DWORD
                for pid in owner._windows_process_ids():
                    if pid not in self._process_handles:
                        handle = owner.kernel.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
                        if handle:
                            self._process_handles[pid] = handle
                        elif owner.ctypes.get_last_error() != 87:  # Process already exited.
                            raise owner.ctypes.WinError(owner.ctypes.get_last_error())
            owner.terminate()

    def _tree_active(self, owner):
        if owner.active():
            return True
        for handle in self._process_handles.values():
            state = owner.kernel.WaitForSingleObject(handle, 0)
            if state == 0xffffffff:
                raise owner.ctypes.WinError(owner.ctypes.get_last_error())
            if state != 0:
                return True
        return False

    def run(self, command, *, cwd, env, timeout):
        with self._lock:
            if self._closing:
                raise RenderCancelled('应用正在退出，已停止本次配置生成')
            if self._owner is not None:
                raise ValueError('已有配置正在生成，请稍候')
            # ManagedProcess supplies DEVNULL input and owns all descendants.
            owner = ManagedProcess(command, cwd, env=env)
            self._owner = owner
        deadline = time.monotonic() + timeout
        try:
            while True:
                with self._lock:
                    if self._closing:
                        raise RenderCancelled('应用正在退出，已停止本次配置生成')
                try:
                    stdout, _ = owner.proc.communicate(timeout=max(.01, min(.1, deadline - time.monotonic())))
                    break
                except subprocess.TimeoutExpired as exc:
                    if time.monotonic() >= deadline:
                        self._terminate(owner)
                        stdout, _ = owner.proc.communicate(timeout=5)
                        raise subprocess.TimeoutExpired(command, timeout, output=stdout) from exc
            with self._lock:
                if self._closing:
                    raise RenderCancelled('应用正在退出，已停止本次配置生成')
            return subprocess.CompletedProcess(command, owner.proc.returncode,
                stdout.decode('utf-8', errors='replace'), '')
        finally:
            with self._lock:
                try:
                    self._terminate(owner)
                    owner.proc.wait(timeout=5)
                    # Job termination is asynchronous; the root may finish
                    # before descendants release files needed by rollback.
                    deadline = time.monotonic() + 5
                    while self._tree_active(owner):
                        if time.monotonic() >= deadline:
                            raise TimeoutError('配置生成子进程未在 5 秒内退出，请核对装配恢复状态')
                        time.sleep(.01)
                finally:
                    self._owner = None
                    owner.close()
                    for handle in self._process_handles.values():
                        owner.kernel.CloseHandle(handle)
                    self._process_handles.clear()
                    if owner.proc.stdout:
                        owner.proc.stdout.close()

    def shutdown(self):
        with self._lock:
            # Refuse starts that arrive after shutdown during resource staging.
            self._closing = True
            if self._owner is not None:
                self._terminate(self._owner)


RENDERERS = RenderController()
run_renderer = RENDERERS.run
shutdown_renderers = RENDERERS.shutdown
