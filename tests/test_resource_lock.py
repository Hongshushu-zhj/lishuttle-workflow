import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


BACKEND = Path(__file__).resolve().parents[1] / 'platform/backend'
sys.path.insert(0, str(BACKEND))


class ResourceLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.locks = self.root / 'locks'
        self.assertIsNotNone(importlib.util.find_spec('resource_lock'), '缺少跨进程资源互斥模块')
        self.module = importlib.import_module('resource_lock')

    def lease(self, resources, **kwargs):
        lease = self.module.ResourceLease(resources, lock_dir=self.locks, **kwargs)
        self.addCleanup(lease.release)
        return lease

    def test_same_resource_conflicts_and_reports_safe_owner(self):
        first = self.lease([self.root / 'Bin'], owner={'label': '测试运行', 'secret': 'private'})
        first.acquire()
        with self.assertRaises(self.module.ResourceBusy) as caught:
            self.lease([self.root / 'Bin']).acquire()
        self.assertEqual(caught.exception.owner['pid'], os.getpid())
        self.assertEqual(caught.exception.owner['label'], '测试运行')
        self.assertNotIn('secret', caught.exception.owner)

    def test_release_allows_reacquire_and_is_idempotent(self):
        first = self.lease([self.root / 'Bin'])
        first.acquire()
        first.acquire()
        first.release()
        first.release()
        self.lease([self.root / 'Bin']).acquire()

    def test_normalized_aliases_and_duplicate_resources_conflict(self):
        folder = self.root / 'Bin'
        folder.mkdir()
        self.lease([folder, folder / '..' / 'Bin']).acquire()
        with self.assertRaises(self.module.ResourceBusy):
            self.lease([str(folder) + os.sep]).acquire()

    def test_distinct_resources_can_be_used_together(self):
        self.lease([self.root / 'Bin-a']).acquire()
        self.lease([self.root / 'Bin-b']).acquire()

    def test_failed_multi_resource_acquisition_releases_prior_locks(self):
        self.lease([self.root / 'b']).acquire()
        with self.assertRaises(self.module.ResourceBusy):
            self.lease([self.root / 'a', self.root / 'b']).acquire()
        self.lease([self.root / 'a']).acquire()

    def child(self, resource):
        source = (
            'import sys,time;sys.path.insert(0,sys.argv[1]);'
            'from resource_lock import ResourceLease;'
            'lease=ResourceLease([sys.argv[2]],lock_dir=sys.argv[3]);'
            'lease.acquire();print("locked",flush=True);time.sleep(60)'
        )
        child = subprocess.Popen([sys.executable, '-u', '-c', source, str(BACKEND),
                                  str(resource), str(self.locks)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: child.poll() is None and child.kill())
        self.addCleanup(lambda: child.stdout.close())
        self.addCleanup(lambda: child.stderr.close())
        self.assertEqual(child.stdout.readline().strip(), 'locked')
        return child

    def test_independent_process_conflicts_and_kill_releases_lock(self):
        resource = self.root / 'Bin'
        child = self.child(resource)
        with self.assertRaises(self.module.ResourceBusy) as caught:
            self.lease([resource]).acquire()
        self.assertEqual(caught.exception.owner['pid'], child.pid)
        child.kill()
        child.wait(timeout=5)
        self.lease([resource]).acquire()

    def test_default_lock_directory_is_shared_across_working_directories(self):
        first = self.module.ResourceLease([self.root / 'shared'])
        self.addCleanup(first.release)
        first.acquire()
        with self.assertRaises(self.module.ResourceBusy):
            self.module.ResourceLease([self.root / 'shared']).acquire()


if __name__ == '__main__':
    unittest.main()
