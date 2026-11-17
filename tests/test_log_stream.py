from pathlib import Path
import sys, tempfile, threading, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform/backend'))
from log_stream import EventJournal, OutputDecoder

class LogStreamTests(unittest.TestCase):
    def test_incremental_encoding_and_eof(self):
        for encoding in ('gbk', 'utf-8'):
            decoder = OutputDecoder(encoding)
            raw = '中文\x1b[31m红\x1b[0m\r进度\r\nEOF'.encode(encoding)
            text, lines = '', []
            for byte in raw:
                chunk, complete = decoder.feed(bytes([byte]))
                text += chunk; lines += complete
            tail, complete = decoder.feed(b'', final=True)
            self.assertEqual(text + tail, raw.decode(encoding))
            self.assertEqual(lines + complete, ['中文\x1b[31m红\x1b[0m', '进度', 'EOF'])
    def test_bounded_replay_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = EventJournal(Path(directory), 123, 'gbk', cache_size=2)
            for i in range(12): journal.append(str(i))
            journal.finish()
            self.assertLessEqual(len(journal.cache), 2)
            self.assertEqual([e['seq'] for e in journal.read(0, 5)], list(range(1,6)))
            restored = EventJournal.open(Path(directory), 123)
            self.assertEqual([e['seq'] for e in restored.read(5, 30)], list(range(6,14)))
            self.assertEqual(restored.read(12)[0]['kind'], 'end')
    def test_runner_halfline_is_visible_before_exit_and_evidence_complete(self):
        import core
        from run_guard import RuntimeGuard
        from run_history import RunHistory
        with tempfile.TemporaryDirectory() as directory:
            runner = core.Runner(guard=RuntimeGuard(), history=RunHistory(Path(directory)/'runs'))
            sid=runner.start([sys.executable,'-u','-c',"import sys,time;sys.stdout.write('half');sys.stdout.flush();time.sleep(1);print('line')"],directory,'fixture')
            try:
                journal=runner.log_journal(sid)
                for _ in range(100):
                    if journal.read(0): break
                    threading.Event().wait(.01)
                self.assertEqual(journal.read(0)[0]['text'],'half')
                self.assertNotEqual(runner.output(sid)['status'],'done')
                self.assertTrue(runner.sessions[sid]['done_event'].wait(5))
                self.assertEqual(runner.output(sid)['lines'],['halfline'])
            finally: runner.shutdown()


class LogHttpTests(unittest.TestCase):
    def setUp(self):
        import desktop_entry
        from log_stream import LogStreamResponse, LogExportResponse
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name);self.journal=EventJournal(self.directory/'events',8,'gbk')
        self.journal.append('one');self.journal.append('two')
        self.server=desktop_entry.create_server(self.directory,'s'*48,'fixture',{
            ('GET','output_stream'):lambda q:LogStreamResponse(self.journal,int(q.get('after',['0'])[0])),
            ('GET','export_log'):lambda q:LogExportResponse(8,{'status':'done','context':{}},self.journal)})
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        def close():
            self.server.stopping.set();self.server.shutdown();self.server.server_close()
        self.addCleanup(close)
    def request(self,path='/api/output_stream',headers=None):
        import http.client
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=4)
        self.addCleanup(connection.close)
        auth={'Cookie':'fixture='+'s'*48,'Origin':self.server.origin};auth.update(headers or {})
        connection.request('GET',path,headers=auth)
        return connection.getresponse()
    def test_auth_replay_last_event_id_and_no_gaps(self):
        self.journal.finish()
        self.assertEqual(self.request(headers={'Cookie':'fixture=wrong'}).status,401)
        self.assertEqual(self.request(headers={'Origin':'http://evil.invalid'}).status,403)
        self.assertEqual(self.request(headers={'Host':'evil.invalid'}).status,403)
        response=self.request('/api/output_stream?after=0',{'Last-Event-ID':'1'})
        body=response.read().decode()
        self.assertEqual(response.status,200);self.assertNotIn('id: 1\n',body)
        self.assertIn('id: 2\n',body);self.assertIn('id: 3\n',body);self.assertIn('event: complete',body)
        self.assertEqual(self.request('/api/output_stream?after=99').status,400)
    def test_open_stream_exits_before_server_close_even_if_runner_still_active(self):
        response=self.request()
        self.assertEqual(response.readline(),b': connected\n')
        self.server.stopping.set()
        finished=threading.Event()
        def close():
            self.server.shutdown();self.server.server_close();finished.set()
        worker=threading.Thread(target=close,daemon=True);worker.start()
        self.assertTrue(finished.wait(3),'SSE request held non-daemon server shutdown open')
        self.assertIn(b'event: stopping',response.read())
    def test_export_header_and_actual_cr_ansi_are_preserved(self):
        self.journal.append('\rprogress\x1b[31mred\x1b[0m\r\nEOF');self.journal.finish()
        response=self.request('/api/export_log');body=response.read()
        self.assertEqual(int(response.getheader('Content-Length')),len(body))
        self.assertIn('固定会话：8'.encode(),body)
        self.assertTrue(body.endswith(b'onetwo\rprogress\x1b[31mred\x1b[0m\r\nEOF'))

class LogIntegrityTests(unittest.TestCase):
    def test_slow_subscriber_never_blocks_producer(self):
        from log_stream import LogStreamResponse
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temporary:
            journal=EventJournal(Path(temporary),9,'gbk');entered=threading.Event();release=threading.Event()
            class Writer:
                def write(self,data): entered.set();release.wait(3);raise TimeoutError('slow fixture')
                def flush(self): pass
            handler=SimpleNamespace(server=SimpleNamespace(stopping=threading.Event()),connection=SimpleNamespace(settimeout=lambda n:None),send_response=lambda x:None,send_header=lambda *x:None,end_headers=lambda:None,wfile=Writer())
            reader=threading.Thread(target=lambda:LogStreamResponse(journal).send(handler),daemon=True);reader.start()
            self.assertTrue(entered.wait(1))
            produced=threading.Event()
            def produce():journal.append('still collecting');journal.finish();produced.set()
            threading.Thread(target=produce,daemon=True).start()
            try:self.assertTrue(produced.wait(1))
            finally:release.set();reader.join(2)
    def test_cancel_closes_journal_with_eof_tail(self):
        import core
        from run_guard import RuntimeGuard
        from run_history import RunHistory
        with tempfile.TemporaryDirectory() as temporary:
            runner=core.Runner(guard=RuntimeGuard(),history=RunHistory(Path(temporary)/'runs'))
            sid=runner.start([sys.executable,'-u','-c',"import sys,time;sys.stdout.write('tail');sys.stdout.flush();time.sleep(30)"],temporary,'cancel fixture')
            journal=runner.log_journal(sid)
            try:
                for _ in range(100):
                    if journal.sequence:break
                    threading.Event().wait(.01)
                self.assertTrue(runner.stop(sid));self.assertTrue(runner.sessions[sid]['done_event'].wait(5))
                self.assertTrue(journal.ended);self.assertEqual(runner.output(sid)['lines'],['tail'])
                self.assertEqual(journal.read(journal.sequence-1)[0]['kind'],'end')
            finally:runner.shutdown()
    def test_old_version_one_history_export_over_16_mib_uses_bounded_chunks(self):
        from log_stream import LogExportResponse
        from run_history import RunHistory
        with tempfile.TemporaryDirectory() as temporary:
            history=RunHistory(temporary);record=history.create(4,'old',{},[],temporary)
            source=Path(temporary)/'4'/'console.log'
            with source.open('wb') as target:
                for _ in range(18):target.write(b'a'*(1024*1024))
                target.write(b'\nEOF\n')
            self.assertIsNone(EventJournal.open(Path(temporary)/'4',4))
            export=LogExportResponse(4,record,legacy_path=source)
            chunks=iter(export.chunks());self.assertIn('固定会话：4'.encode(),next(chunks))
            size=0;tail=b''
            for chunk in chunks:self.assertLessEqual(len(chunk),65536);size+=len(chunk);tail=chunk
            self.assertEqual(size,18*1024*1024+5);self.assertTrue(tail.endswith(b'\nEOF\n'))

class FullEvidenceTests(unittest.TestCase):
    def test_explicit_utf8_full_finalizer_evidence_and_archive_are_not_display_ring(self):
        import core, os
        from run_guard import RuntimeGuard
        from run_history import RunHistory
        with tempfile.TemporaryDirectory() as temporary:
            runner=core.Runner(guard=RuntimeGuard(),history=RunHistory(Path(temporary)/'runs'))
            captured=[]
            def finalize(context, baseline, lines, code, cancelled=False):
                captured.extend(lines)
                return {'verdict':'success'}
            code="import os;os.write(1,bytes.fromhex('e4b8ad'));os.write(2,bytes.fromhex('e69687')+b'\\n');os.write(1,b'line\\n'*4000+b'EOF')"
            sid=runner.start([sys.executable,'-u','-c',code],temporary,'utf8 fixture',
                             env=dict(os.environ,LISHUTTLE_LOG_ENCODING='utf-8'),finalize=finalize)
            try:
                self.assertTrue(runner.sessions[sid]['done_event'].wait(10))
                self.assertEqual(captured[0],'中文');self.assertEqual(captured[-1],'EOF')
                self.assertEqual(len(captured),4002)
                self.assertEqual(runner.history.output(sid,limit=5000)['lines'],captured)
                self.assertEqual(runner.history.get(sid)['context']['log_encoding'],'utf-8')
                exported=b''.join(runner.export_log(sid).chunks())
                self.assertTrue(exported.endswith(('中文\n'+'line\n'*4000+'EOF').encode()))
            finally:runner.shutdown()

if __name__ == '__main__': unittest.main()
