"""One service-wide lease for runtime resources and their input writers."""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import threading
import time
import uuid
from resource_lock import ResourceLease, ResourceBusy, normalize_resource


class RuntimeBusy(RuntimeError):
    code = 'RUNTIME_BUSY'

    def __init__(self, owner):
        self.owner = owner
        super().__init__(f"平台正在{owner.get('label', '执行任务')}，请结束或取消后再操作")

    def response(self):
        return {'ok': False, 'error': str(self), 'message': str(self),
                'code': self.code, 'runtime': self.owner}


class RuntimeGuard:
    def __init__(self):
        self._lock = threading.RLock()
        self._owner = None
        self._current = ContextVar('runtime_lease', default=None)
        self._leases = []
        self._resources = set()

    def snapshot(self):
        with self._lock:
            if self._owner is None:
                return {'busy': False, 'phase': 'idle', 'sid': None}
            return deepcopy({key: value for key, value in self._owner.items()
                             if key not in ('token', 'retained')})

    @contextmanager
    def operation(self, label, context=None):
        with self._lock:
            current = self._current.get()
            nested = self._owner is not None and self._owner['token'] == current
            if self._owner is not None and not nested:
                raise RuntimeBusy(self.snapshot())
            if nested:
                token = current
            else:
                token = uuid.uuid4().hex
                metadata = {key:value for key,value in (context or {}).items() if key in
                            ('project', 'bin_dir', 'schema_name', 'func', 'task_id', 'out_dir')}
                self._owner = dict(metadata, token=token, busy=True,
                                   phase='preparing', sid=None, label=label,
                                   started_at=time.time(), retained=False)
        reset = self._current.set(token)
        try:
            yield token
        finally:
            self._current.reset(reset)
            if not nested:
                with self._lock:
                    if self._owner and self._owner['token'] == token and not self._owner['retained']:
                        self.release(token)

    def bind(self, token, sid, context=None):
        with self._lock:
            if not self._owner or self._owner['token'] != token:
                raise RuntimeError('运行占用已失效')
            # Only safe, descriptive fields are exposed in the busy response.
            for key in ('project', 'bin_dir', 'schema_name', 'func', 'task_id', 'out_dir'):
                if context and key in context:
                    self._owner[key] = context[key]
            self._owner.update(sid=sid, phase='running', retained=True)

    def acquire_resources(self, token, context):
        """Extend the current lease before reading or changing shared inputs."""
        with self._lock:
            if not self._owner or self._owner['token'] != token:
                raise RuntimeError('运行占用已失效')
            resources = {normalize_resource(context[key]) for key in ('bin_dir', 'out_dir', 'source_project')
                         if context.get(key)} - self._resources
            if not resources:
                return
            owner = dict(self.snapshot(), **{key: context[key] for key in
                         ('project', 'bin_dir', 'out_dir') if context.get(key)})
            lease = ResourceLease(resources, owner=owner)
            try:
                lease.acquire()
            except ResourceBusy as exc:
                raise RuntimeBusy(dict(exc.owner, busy=True, external=True,
                                       phase=exc.owner.get('phase', 'running'))) from exc
            self._leases.append(lease)
            self._resources.update(resources)

    def external_snapshot(self, context):
        own = self.snapshot()
        if own['busy']:
            return own
        resources = [context[key] for key in ('bin_dir', 'out_dir', 'source_project') if context.get(key)]
        if not resources:
            return own
        lease = ResourceLease(resources)
        try:
            lease.acquire()
        except ResourceBusy as exc:
            return dict(exc.owner, busy=True, external=True,
                        phase=exc.owner.get('phase', 'running'))
        finally:
            lease.release()
        return own

    def set_phase(self, token, phase):
        with self._lock:
            if self._owner and self._owner['token'] == token:
                self._owner['phase'] = phase

    def release(self, token):
        with self._lock:
            if not self._owner or self._owner['token'] != token:
                return False
            for lease in reversed(self._leases):
                lease.release()
            self._leases = []
            self._resources.clear()
            self._owner = None
            return True
