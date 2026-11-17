"""Fault injection for durable journal publication and finite recovery."""
from pathlib import Path
import sys, tempfile, unittest, struct
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'platform/backend'))
from log_stream import EventJournal, LogExportResponse

class JournalFailureTests(unittest.TestCase):
 def test_failed_index_fsync_cannot_publish_duplicate_sequence_after_finish(self):
  import log_stream
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);journal=EventJournal(root,1,'gbk');real=log_stream.os.fsync;calls=0
   def fail_index(fd):
    nonlocal calls
    calls+=1
    if calls==2:raise OSError('index fsync fixture')
    real(fd)
   with patch.object(log_stream.os,'fsync',side_effect=fail_index):
    with self.assertRaises(OSError):journal.append('uncommitted')
   self.assertEqual(journal.sequence,0)
   self.assertEqual((root/'events.idx').stat().st_size,0)
   self.assertEqual((root/'events.jsonl').stat().st_size,0)
   with self.assertRaises(OSError):journal.finish()
   # Recovery must either reject a marked failure or yield a valid empty prefix.
   try:restored=EventJournal.open(root,1)
   except OSError:return
   self.assertEqual(restored.sequence,0)
   self.assertLess(sum(map(len,LogExportResponse(1,{},restored).chunks())),1000)
 def test_reopen_rejects_duplicate_sequence_and_partial_index(self):
  for corruption in ('duplicate','partial'):
   with self.subTest(corruption=corruption),tempfile.TemporaryDirectory() as directory:
    root=Path(directory);journal=EventJournal(root,2,'gbk');journal.append('one');journal.finish()
    if corruption=='duplicate':
     with (root/'events.idx').open('r+b') as index:index.seek(8);index.write(struct.pack('<Q',0))
    else:
     with (root/'events.idx').open('ab') as index:index.write(b'x')
    with self.assertRaises(OSError):EventJournal.open(root,2)
 def test_export_rejects_nonprogress_even_if_reader_contract_is_broken(self):
  class BrokenJournal:
   sequence=2
   def read(self,after,limit):return [{'sid':3,'seq':1,'kind':'text','text':'x'}]
  output=iter(LogExportResponse(3,{},BrokenJournal()).chunks());next(output);self.assertEqual(next(output),b'x')
  with self.assertRaises(OSError):next(output)
 def test_no_history_storage_is_cleaned_at_shutdown_without_deleting_persisted_history(self):
  import core
  from run_guard import RuntimeGuard
  from run_history import RunHistory
  with tempfile.TemporaryDirectory() as directory:
   runner=core.Runner(guard=RuntimeGuard());sid=runner.start([sys.executable,'-c',"print('ok')"],directory,'fixture')
   self.assertTrue(runner.sessions[sid]['done_event'].wait(5));events=runner.log_journal(sid).directory
   runner.shutdown();self.assertFalse(events.exists())
   persistent=core.Runner(guard=RuntimeGuard(),history=RunHistory(Path(directory)/'history'))
   sid=persistent.start([sys.executable,'-c',"print('ok')"],directory,'fixture');self.assertTrue(persistent.sessions[sid]['done_event'].wait(5))
   persistent.shutdown();self.assertEqual(persistent.history.output(sid)['lines'],['ok'])


class EndFailureTests(unittest.TestCase):
 def test_end_failure_is_persisted_unconfirmed_and_releases_shutdown(self):
  import core, threading
  from run_guard import RuntimeGuard
  from run_history import RunHistory
  with tempfile.TemporaryDirectory() as directory:
   runner=core.Runner(guard=RuntimeGuard(),history=RunHistory(Path(directory)/'history'))
   with patch.object(EventJournal,'finish',side_effect=OSError('end persist fixture')):
    sid=runner.start([sys.executable,'-c',"print('ok')"],directory,'fixture')
    self.assertTrue(runner.sessions[sid]['done_event'].wait(5))
   self.assertEqual(runner.output(sid)['result']['verdict'],'unconfirmed')
   record=runner.history.get(sid)
   self.assertEqual(record['result']['verdict'],'unconfirmed')
   self.assertIn('end persist fixture',record['internal_error'])
   with self.assertRaises(OSError):runner.export_log(sid)
   with self.assertRaises(OSError):EventJournal.open(runner.history._directory(sid),sid)
   finished=threading.Event()
   threading.Thread(target=lambda:(runner.shutdown(),finished.set()),daemon=True).start()
   self.assertTrue(finished.wait(2));self.assertFalse(runner.guard.snapshot()['busy'])


class FailureHttpTests(unittest.TestCase):
 def test_corrupt_export_returns_finite_error_and_server_closes(self):
  import desktop_entry, threading, http.client
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);journal=EventJournal(root/'events',4,'gbk');journal.append('one');journal.finish()
   with (root/'events'/'events.idx').open('r+b') as index:index.seek(8);index.write(struct.pack('<Q',0))
   def export(query):return LogExportResponse(4,{},EventJournal.open(root/'events',4))
   server=desktop_entry.create_server(root,'s'*48,'fixture',{('GET','export_log'):export})
   threading.Thread(target=server.serve_forever,daemon=True).start()
   connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=2)
   try:
    connection.request('GET','/api/export_log?sid=4',headers={'Cookie':'fixture='+'s'*48,'Origin':server.origin})
    response=connection.getresponse();self.assertEqual(response.status,500);self.assertIn(b'API_FAILED',response.read())
   finally:
    connection.close();server.stopping.set();closed=threading.Event()
    threading.Thread(target=lambda:(server.shutdown(),server.server_close(),closed.set()),daemon=True).start()
    self.assertTrue(closed.wait(2),'failed export blocked shutdown')
 def test_length_preflight_honors_shutdown_before_response_headers(self):
  import threading
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory() as directory:
   journal=EventJournal(Path(directory),5,'gbk');journal.append('one');journal.finish()
   stopping=threading.Event();stopping.set();headers=[]
   handler=SimpleNamespace(connection=SimpleNamespace(settimeout=lambda n:None),server=SimpleNamespace(stopping=stopping),send_response=headers.append)
   with self.assertRaises(OSError):LogExportResponse(5,{},journal).send(handler)
   self.assertEqual(headers,[])


class FailedStreamFinalizationTests(unittest.TestCase):
 def test_failed_stream_waits_for_final_result_and_accepts_reconnect_without_loop(self):
  import core, threading, io
  from types import SimpleNamespace
  from log_stream import LogStreamResponse
  from run_guard import RuntimeGuard
  from run_history import RunHistory
  with tempfile.TemporaryDirectory() as directory:
   runner=core.Runner(guard=RuntimeGuard(),history=RunHistory(Path(directory)/'history'))
   entered=threading.Event();release=threading.Event();finished=threading.Event();errors=[]
   def finalize(*args,**kwargs):
    entered.set();release.wait(5);return {'verdict':'success'}
   real_append=EventJournal.append
   def fail_text(journal,text='',kind='text',**kwargs):
    if text:journal.fail(OSError('capture fixture'));raise OSError('capture fixture')
    return real_append(journal,text,kind,**kwargs)
   with patch.object(EventJournal,'append',new=fail_text):
    sid=runner.start([sys.executable,'-c',"print('trigger')"],directory,'fixture',finalize=finalize)
    try:
     self.assertTrue(entered.wait(3));self.assertEqual(runner.output(sid)['status'],'finalizing');self.assertTrue(runner.guard.snapshot()['busy'])
     journal=runner.log_journal(sid);body=io.BytesIO()
     handler=SimpleNamespace(server=SimpleNamespace(stopping=threading.Event()),connection=SimpleNamespace(settimeout=lambda n:None),send_response=lambda n:None,send_header=lambda *args:None,end_headers=lambda:None,wfile=body)
     def subscribe():
      try:LogStreamResponse(journal,0).send(handler)
      except Exception as error:errors.append(error)
      finally:finished.set()
     threading.Thread(target=subscribe,daemon=True).start()
     self.assertFalse(finished.wait(.2),'failed SSE ended before finalization')
     self.assertNotIn(b'event: failed',body.getvalue())
     release.set();self.assertTrue(finished.wait(3));self.assertEqual(errors,[])
     self.assertIn(b'event: failed',body.getvalue());self.assertNotIn(b'event: complete',body.getvalue())
     report=runner.output(sid);self.assertEqual(report['status'],'done');self.assertEqual(report['result']['verdict'],'unconfirmed');self.assertFalse(runner.guard.snapshot()['busy'])
    finally:release.set();runner.shutdown()


class FailedStreamShutdownTests(unittest.TestCase):
 def test_waiting_failed_stream_wakes_for_shutdown_without_finalizer_completion(self):
  import threading, io
  from types import SimpleNamespace
  from log_stream import LogStreamResponse
  with tempfile.TemporaryDirectory() as directory:
   journal=EventJournal(Path(directory),9,'gbk');journal.terminal_ready=False;journal.fail(OSError('fixture'))
   stopping=threading.Event();finished=threading.Event();body=io.BytesIO()
   handler=SimpleNamespace(server=SimpleNamespace(stopping=stopping),connection=SimpleNamespace(settimeout=lambda n:None),send_response=lambda n:None,send_header=lambda *args:None,end_headers=lambda:None,wfile=body)
   thread=threading.Thread(target=lambda:(LogStreamResponse(journal).send(handler),finished.set()),daemon=True);thread.start()
   self.assertFalse(finished.wait(.1));stopping.set();self.assertTrue(finished.wait(2))
   self.assertIn(b'event: stopping',body.getvalue());self.assertNotIn(b'event: failed',body.getvalue())


class EmptyReadRaceTests(unittest.TestCase):
 def test_failure_after_empty_read_cannot_emit_complete_before_finalization(self):
  import threading, io
  from types import SimpleNamespace
  from log_stream import LogStreamResponse
  with tempfile.TemporaryDirectory() as directory:
   journal=EventJournal(Path(directory),11,'gbk');journal.terminal_ready=False
   response=LogStreamResponse(journal);real_read=journal.read;injected=threading.Event();done=threading.Event();body=io.BytesIO()
   def read_then_fail(after,limit=64):
    batch=real_read(after,limit)
    journal.fail(OSError('empty-read race'));injected.set();return batch
   journal.read=read_then_fail
   handler=SimpleNamespace(server=SimpleNamespace(stopping=threading.Event()),connection=SimpleNamespace(settimeout=lambda n:None),send_response=lambda n:None,send_header=lambda *args:None,end_headers=lambda:None,wfile=body)
   thread=threading.Thread(target=lambda:(response.send(handler),done.set()),daemon=True);thread.start()
   try:
    self.assertTrue(injected.wait(1));self.assertFalse(done.wait(.2),'empty-read race emitted terminal event')
    self.assertNotIn(b'event: complete',body.getvalue());journal.complete();self.assertTrue(done.wait(2))
    self.assertIn(b'event: failed',body.getvalue());self.assertNotIn(b'event: complete',body.getvalue())
   finally:journal.complete();thread.join(2)

if __name__=='__main__':unittest.main()
