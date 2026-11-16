"""The desktop listener authenticates every request before dispatch."""
import http.client
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
import io
import os

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'platform/backend'))


class DesktopServiceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('desktop_entry'), 'isolated desktop service is required')
        import desktop_entry
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        static = root / 'static'
        static.mkdir()
        (static / 'index.html').write_text('<p>fixture</p>',encoding='utf-8')
        (root / 'private.txt').write_text('private fixture')
        self.calls = []
        def echo(body):
            self.calls.append(body)
            return {'ok':True,'body':body}
        self.server = desktop_entry.create_server(static, 's' * 48, 'test_session', {('GET','echo'):echo,('POST','echo'):echo})
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(self.server.shutdown)
        self.origin = 'http://127.0.0.1:' + str(self.server.server_port)

    def request(self, path='/api/echo', method='GET', body=None, **overrides):
        connection = http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        self.addCleanup(connection.close)
        headers = {'Cookie':'test_session=' + 's' * 48, 'Origin':self.origin}
        headers.update(overrides)
        connection.request(method,path,body=body,headers=headers)
        response = connection.getresponse()
        return response.status,dict(response.getheaders()),response.read()

    def test_random_loopback_port_and_cookie_authentication(self):
        self.assertEqual(self.server.server_address[0],'127.0.0.1')
        self.assertGreater(self.server.server_port,0)
        self.assertEqual(self.request()[0],200)
        self.assertEqual(self.request(Cookie='test_session=wrong')[0],401)
        self.assertEqual(self.request(Cookie='')[0],401)
        self.assertEqual(len(self.calls),1)

    def test_os_selected_chromium_blocked_port_is_closed_and_rebound(self):
        import desktop_entry
        blocked = SimpleNamespace(server_port=6667,server_close=Mock())
        allowed = SimpleNamespace(server_port=32001,server_close=Mock())
        with patch.object(desktop_entry,'DesktopServer',side_effect=[blocked,allowed]):
            listener = desktop_entry.create_server(Path(self.temp.name)/'static','a'*48,'fixture',{})
        self.assertIs(listener,allowed)
        blocked.server_close.assert_called_once()
        self.assertEqual(listener.origin,'http://127.0.0.1:32001')

    def test_host_origin_and_framing_fail_before_dispatch(self):
        for headers in ({'Host':'example.com'}, {'Origin':'http://evil.test'}, {'Origin':'null'}, {'Host':'127.0.0.1:1'}):
            self.assertEqual(self.request(**headers)[0],403)
        for headers, expected in (({'Content-Length':'-1'},400),({'Content-Length':'1000000000'},413),({'Transfer-Encoding':'chunked'},400)):
            self.assertEqual(self.request(method='POST',body='{}',**headers)[0],expected)
        self.assertEqual(self.calls,[])

    def test_json_body_must_be_an_object_with_json_content_type(self):
        self.assertEqual(self.request(method='POST',body='[]',**{'Content-Type':'application/json'})[0],400)
        self.assertEqual(self.request(method='POST',body='{}',**{'Content-Type':'text/plain'})[0],415)
        code,_,raw = self.request(method='POST',body='{"fixture":1}',**{'Content-Type':'application/json'})
        self.assertEqual(code,200)
        self.assertEqual(json.loads(raw)['body'],{'fixture':1})

    def test_static_paths_are_contained_and_security_headers_are_set(self):
        code,headers,data = self.request('/')
        self.assertEqual(code,200)
        self.assertIn(b'fixture',data)
        self.assertIn("default-src 'self'",headers['Content-Security-Policy'])
        self.assertEqual(headers['X-Content-Type-Options'],'nosniff')
        self.assertEqual(headers['Cache-Control'],'no-store')
        for path in ('/../private.txt','/%2e%2e/private.txt','/%2e%2e%5cprivate.txt','/C:/private.txt'):
            self.assertEqual(self.request(path)[0],404,path)
        self.assertEqual(self.request('/api/unknown')[0],404)

    def test_read_only_requests_without_origin_still_require_cookie(self):
        connection = http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        self.addCleanup(connection.close)
        connection.request('GET','/',headers={'Cookie':'test_session=' + 's' * 48})
        response = connection.getresponse()
        self.assertEqual(response.status,200)
        response.read()

    def test_entry_waits_for_runner_finalization_before_shutdown_ack(self):
        import desktop_entry
        root = Path(self.temp.name)
        events = []
        output = io.StringIO()
        def finish():
            self.assertNotIn('"status": "stopped"',output.getvalue())
            events.append('archives finished')
        domain = SimpleNamespace(RUNNER=SimpleNamespace(shutdown=finish),RUNTIME=SimpleNamespace(snapshot=lambda:{'busy':False}))
        feature = SimpleNamespace(ROUTES={},close=lambda:events.append('discovery finished'))
        bootstrap = dict(data_dir=str(root/'user'),static_dir=str(root/'static'),resource_root=str(root),session_secret='t'*48,cookie_name='fixture')
        # Data is a sibling of the immutable resource fixture.
        bootstrap['data_dir'] = str(root.parent/(root.name+'-unused-data'))
        control = io.StringIO(json.dumps(bootstrap)+'\n{"type":"shutdown","request_id":"fixture"}\n')
        with patch.dict(os.environ),patch.dict(sys.modules,{'core':domain,'server':SimpleNamespace(ROUTES={}),'desktop_features':feature}), \
                patch.object(sys,'stdin',control),patch.object(sys,'stdout',output):
            result = desktop_entry.main()
        self.assertEqual(result,0)
        self.assertEqual(events,['archives finished','discovery finished'])
        self.assertEqual(json.loads(output.getvalue().splitlines()[-1]),{'type':'shutdown','status':'stopped','request_id':'fixture'})


if __name__ == '__main__':
    unittest.main()
