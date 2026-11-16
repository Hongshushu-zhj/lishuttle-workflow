"""Desktop resource scanning uses disposable directories only."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'platform/backend'), str(ROOT / 'scripts')]
from discovery import DiscoveryManager, scan_resources


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def engine(self, name):
        base = self.root / name
        (base / 'LiShuttle').mkdir(parents=True)
        (base / 'SwanUtility/incl').mkdir(parents=True)
        (base / 'CMakeLists.txt').write_text('project(example)')
        (base / 'SwanUtility/incl/LiShuttleTypes.h').write_text('// fixture')
        return base

    def test_recognizes_engine_by_content_and_reports_multiple_candidates(self):
        self.engine('任意项目 A')
        self.engine('completely-different-B')
        result = scan_resources([str(self.root)])
        engines = [r for r in result['results'] if r['kind'] == 'engine']
        self.assertEqual(len(engines), 2)
        self.assertTrue(all(r['evidence'] for r in engines))
        self.assertEqual(result['status'], 'done')

    def test_map_leaf_and_parent_are_distinct_and_runtime_filename_is_arbitrary(self):
        scene = self.root / 'some-data/建筑A'
        scene.mkdir(parents=True)
        (scene / '楼层.DAS').write_bytes(b'fixture')
        outdoor = self.root / 'some-data/outside/heights'
        outdoor.mkdir(parents=True)
        (outdoor / 'index.txt').write_text('fixture')
        task = self.root / 'input/任务包'
        task.mkdir(parents=True)
        (task / 'random.xml').write_text('<RuntimeSchema name="example"/>')
        (task / 'cells.csv').write_text('Cell ID,Longitude,Latitude,Height (m),Azimuth,Antenna,Power\n1,1,1,10,0,x,20\n')
        result = scan_resources([str(self.root)])
        by_kind = {}
        for candidate in result['results']:
            by_kind.setdefault(candidate['kind'], []).append(candidate)
        self.assertEqual(len(by_kind['map']), 2)
        self.assertEqual(by_kind['map-root'][0]['path'], (self.root / 'some-data').as_posix())
        self.assertTrue(any(r['path'].endswith('random.xml') for r in by_kind['runtime']))
        self.assertTrue(any(r['path'] == task.as_posix() for r in by_kind['task']))

    def test_entry_budget_and_depth_bound_work(self):
        for i in range(15):
            (self.root / str(i)).mkdir()
        result = scan_resources([str(self.root)], max_entries=3)
        self.assertTrue(result['limited'])
        self.assertLessEqual(result['visited'], 3)
        self.assertEqual(scan_resources([str(self.root)], max_depth=0)['visited'], 0)

    def test_cancelled_scan_and_unavailable_root_are_reported(self):
        cancelled = threading.Event()
        cancelled.set()
        self.assertEqual(scan_resources([str(self.root)], cancel=cancelled)['status'], 'cancelled')
        result = scan_resources([str(self.root / 'missing')])
        self.assertTrue(result['skipped'])
        self.assertFalse(result['results'])

    def test_does_not_execute_candidate_or_mutate_tree(self):
        self.engine('project')
        (self.root / 'not-runtime.xml').write_text('<Other/>')
        (self.root / 'cmake.exe').write_text('never execute')
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        result = scan_resources([str(self.root)])
        self.assertFalse(any(r['path'].endswith('not-runtime.xml') for r in result['results']))
        self.assertEqual(before, sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')))

    def test_manager_ids_are_isolated_and_unknown_id_is_explicit(self):
        manager = DiscoveryManager()
        self.addCleanup(manager.close)
        first = manager.start([str(self.root)])
        second = manager.start([str(self.root)])
        self.assertNotEqual(first, second)
        self.assertEqual(manager.status(first)['id'], first)
        self.assertEqual(manager.status(second)['id'], second)
        with self.assertRaisesRegex(ValueError, '扫描'):
            manager.status('unknown')
        with self.assertRaises(ValueError):
            manager.start([])
