from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
import core
from server import Api
from result_validation import snapshot, validate
from run_guard import RuntimeGuard


class RunSessionTests(unittest.TestCase):
    def test_current_products_are_validated_in_pinned_session_not_current_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pred = root / 'output/task/pred/4'
            context = {'func':'pred', 'schema_name':'file.xml', 'task_name':'task', 'task_id':'4',
                       'out_dir':str(root/'output/task'), 'pred_dir':str(pred),
                       'mode':{'effective':'ground','layer_count':1}, 'regions':[{'id':0}]}
            baseline = snapshot(context)
            code = ('from pathlib import Path; import struct; '
                    f'p=Path({str(pred)!r}); p.mkdir(parents=True); '
                    '(p/"index.txt").write_text("UTM 50\\nRSRP.dem 0 2 0 2 1\\nDLRSSINR.dem 0 2 0 2 1\\nBESTSERVER.dem 0 2 0 2 1\\n"); '
                    '(p/"cellid.csv").write_text("1,cell-a\\n"); '
                    '(p/"RSRP.dem").write_bytes(struct.pack("<4h",-9000,-9100,-9200,-9300)); '
                    '(p/"DLRSSINR.dem").write_bytes(struct.pack("<4h",100,200,300,400)); '
                    '(p/"BESTSERVER.dem").write_bytes(struct.pack("<4h",1,1,1,1)); print("session fixture")')
            guard = RuntimeGuard()
            runner = core.Runner(guard=guard)
            sid = runner.start([sys.executable,'-u','-c',code], temporary, 'fixture',
                               context=context, baseline=baseline, finalize=validate)
            context['out_dir'] = 'wrong-project'
            deadline = time.monotonic() + 10
            while runner.output(sid, 0)['status'] != 'done' and time.monotonic() < deadline:
                threading.Event().wait(.02)
            self.assertEqual(runner.output(sid, 0)['status'], 'done')
            self.assertFalse(guard.snapshot()['busy'])
            with patch.object(core,'RUNNER',runner), patch.object(core,'load_env',side_effect=AssertionError('must use session')):
                report = Api.results({'sid':[str(sid)]})
            self.assertTrue(report['associated'])
            self.assertEqual(report['verdict'], 'success', report.get('issues'))
            self.assertEqual(report['context']['schema_name'], 'file.xml')
            self.assertNotEqual(report['dir'], 'wrong-project')
            report['context']['task_name'] = 'tampered'
            self.assertEqual(runner.output(sid,0)['context']['task_name'], 'task')

    def test_directory_status_end_is_never_current_run_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root/'out/old'
            output.mkdir(parents=True)
            (output/'jobstatus_end').write_text('old')
            (output/'arbitrary.txt').write_text('old product')
            env = {'PROJECT_DIR':str(root), 'BUILD_SUBDIR':'build', 'OUT_ROOT':str(root/'out')}
            with patch.object(core,'load_env',return_value=env):
                report = core.results('old')
            self.assertEqual(report['status'], 'end')
            self.assertFalse(report['associated'])
            self.assertEqual(report['verdict'], 'unconfirmed')


if __name__ == '__main__':
    unittest.main()
