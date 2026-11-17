"""Authenticated loopback HTTP and pipe lifecycle for the desktop application.

This module deliberately does not import core/server until a valid bootstrap
has established the writable root. stdout contains protocol JSON only.
"""
import hmac
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
import threading
from urllib.parse import parse_qs, unquote, urlsplit

MAX_BODY = 8 * 1024 * 1024
MAX_CONTROL = 65536
BLOCKED_PORTS = {1719, 1720, 1723, 2049, 3659, 4045, 5060, 5061, 6000,
                 6566, 6665, 6666, 6667, 6668, 6669, 6697, 10080, 65535}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
       "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")


class DesktopServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = False
    block_on_close = True


class DesktopHandler(BaseHTTPRequestHandler):
    server_version = 'LiShuttleDesktop'
    sys_version = ''

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header('Content-Security-Policy', CSP)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.close_connection = True
        super().end_headers()

    def _json(self, obj, status=200):
        if isinstance(obj, dict):
            if obj.get('error'):
                obj = dict(obj)
                obj.setdefault('code', 'API_ERROR')
            if obj.get('code') in ('RUNTIME_BUSY', 'FILE_CONFLICT', 'STALE_PREVIEW', 'PREVIEW_STALE', 'REVISION_CONFLICT'):
                status = 409
            elif obj.get('code') == 'REVISION_REQUIRED':
                status = 400
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, code, message):
        return self._json(dict(ok=False, error=message, code=code), status)

    def _trusted(self):
        hosts = self.headers.get_all('Host', [])
        origins = self.headers.get_all('Origin', [])
        if len(hosts) != 1 or hosts[0] != self.server.authority:
            self._error(403, 'HOST_REJECTED', 'Host rejected')
            return False
        if len(origins) > 1 or (origins and origins[0] != self.server.origin) or (self.command == 'POST' and not origins):
            self._error(403, 'ORIGIN_REJECTED', 'Origin rejected')
            return False
        raw = self.headers.get_all('Cookie', [])
        try:
            cookie = SimpleCookie()
            if len(raw) == 1:
                cookie.load(raw[0])
            value = cookie[self.server.cookie_name].value if self.server.cookie_name in cookie else ''
            trusted = hmac.compare_digest(value.encode('utf-8'), self.server.session_secret)
        except (CookieError, UnicodeError, ValueError):
            trusted = False
        if not trusted:
            self._error(401, 'UNAUTHORIZED', 'Session authentication required')
            return False
        if self.server.stopping.is_set():
            self._error(503, 'SHUTTING_DOWN', 'Service is shutting down')
            return False
        if self.headers.get_all('Transfer-Encoding'):
            self._error(400, 'INVALID_FRAMING', 'Transfer-Encoding is not supported')
            return False
        return True

    def _parsed(self):
        parsed = urlsplit(self.path)
        if parsed.scheme or parsed.netloc or not self.path.startswith('/'):
            self._error(400, 'INVALID_TARGET', 'Invalid request target')
            return None
        return parsed

    def _dispatch(self, method, parsed, payload):
        fn = self.server.routes.get((method, parsed.path[len('/api/'):]))
        if fn is None:
            return self._error(404, 'NOT_FOUND', 'Unknown API')
        try:
            if parsed.path == '/api/output_stream' and self.headers.get('Last-Event-ID'):
                payload['after'] = [self.headers['Last-Event-ID']]
            value = fn(payload)
            if hasattr(value, 'send'):
                return value.send(self)
            return self._json(value)
        except (ValueError, TypeError) as exc:
            return self._error(400, 'INVALID_REQUEST', str(exc))
        except Exception:
            # Diagnostics must never echo request headers/bootstrap credentials.
            return self._error(500, 'API_FAILED', 'The operation failed; check its state before retrying')

    def do_GET(self):
        if not self._trusted():
            return
        parsed = self._parsed()
        if parsed is None:
            return
        if parsed.path.startswith('/api/'):
            return self._dispatch('GET', parsed, parse_qs(parsed.query))
        decoded = unquote(parsed.path)
        parts = decoded.split('/')
        if any(part in ('.', '..') for part in parts) or any(char in decoded for char in ('\\', ':', '\x00')):
            return self._error(404, 'NOT_FOUND', 'Not found')
        try:
            full = (self.server.static_dir / (decoded.lstrip('/') or 'index.html')).resolve()
            if not full.is_relative_to(self.server.static_dir) or not full.is_file():
                return self._error(404, 'NOT_FOUND', 'Not found')
            data = full.read_bytes()
        except (OSError, ValueError):
            return self._error(404, 'NOT_FOUND', 'Not found')
        mime = mimetypes.guess_type(str(full))[0] or 'application/octet-stream'
        if mime.startswith('text/') or full.suffix in ('.js', '.json'):
            mime += '; charset=utf-8'
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if not self._trusted():
            return
        parsed = self._parsed()
        if parsed is None:
            return
        if not parsed.path.startswith('/api/'):
            return self._error(404, 'NOT_FOUND', 'Not found')
        lengths = self.headers.get_all('Content-Length', [])
        if not lengths:
            return self._error(411, 'LENGTH_REQUIRED', 'Content-Length required')
        if len(lengths) != 1 or not re.fullmatch(r'[0-9]{1,10}', lengths[0]):
            return self._error(400, 'INVALID_LENGTH', 'Invalid Content-Length')
        length = int(lengths[0])
        if length > MAX_BODY:
            return self._error(413, 'BODY_TOO_LARGE', 'Request body exceeds the limit')
        if self.headers.get_content_type() != 'application/json':
            return self._error(415, 'JSON_REQUIRED', 'Content-Type must be application/json')
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError('incomplete body')
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError('JSON body must be an object')
        except (ValueError, UnicodeError):
            return self._error(400, 'INVALID_JSON', 'Request body must be a JSON object')
        return self._dispatch('POST', parsed, body)


def create_server(static_dir, session_secret, cookie_name, routes):
    if not isinstance(session_secret, str) or not re.fullmatch(r'[\x21-\x7e]{32,512}', session_secret):
        raise ValueError('Invalid session credential')
    if not isinstance(cookie_name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', cookie_name):
        raise ValueError('Invalid session cookie name')
    static = Path(static_dir).resolve(strict=True)
    if not static.is_dir():
        raise ValueError('Static directory does not exist')
    # Retain the bound socket; retry only ports Chromium refuses to navigate.
    for _ in range(32):
        server = DesktopServer(('127.0.0.1', 0), DesktopHandler)
        if server.server_port >= 1024 and server.server_port not in BLOCKED_PORTS:
            break
        server.server_close()
    else:
        raise OSError('Could not obtain a browser-compatible loopback port')
    server.static_dir = static
    server.session_secret = session_secret.encode('ascii')
    server.cookie_name = cookie_name
    server.routes = dict(routes)
    server.authority = '127.0.0.1:' + str(server.server_port)
    server.origin = 'http://' + server.authority
    server.stopping = threading.Event()
    return server


def read_bootstrap(stream):
    raw = stream.readline(MAX_CONTROL + 1)
    if not raw or len(raw) > MAX_CONTROL or not raw.endswith('\n'):
        raise ValueError('Missing or oversized desktop bootstrap')
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('Desktop bootstrap must be an object')
    for name in ('data_dir', 'static_dir', 'resource_root'):
        if not isinstance(data.get(name), str) or not Path(data[name]).is_absolute():
            raise ValueError('Desktop bootstrap requires absolute roots')
        data[name] = str(Path(data[name]).resolve())
    resource, state = Path(data['resource_root']), Path(data['data_dir'])
    if not resource.is_dir() or state.is_relative_to(resource):
        raise ValueError('Desktop data must be separate from installation resources')
    static = Path(data['static_dir'])
    if not static.is_dir() or not static.is_relative_to(resource):
        raise ValueError('Desktop static files must belong to installation resources')
    if not isinstance(data.get('session_secret'), str) or not re.fullmatch(r'[\x21-\x7e]{32,512}', data['session_secret']):
        raise ValueError('Invalid session credential')
    if not isinstance(data.get('cookie_name'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', data['cookie_name']):
        raise ValueError('Invalid session cookie name')
    return data


def main():
    output = sys.stdout
    # Any legacy print diagnostics remain outside the machine-readable channel.
    sys.stdout = sys.stderr
    lock = threading.Lock()
    def emit(value):
        with lock:
            output.write(json.dumps(value, ensure_ascii=False) + '\n')
            output.flush()
    server = None
    thread = None
    core = None
    features = None
    request_id = None
    shutdown_requested = False
    bootstrap = {}
    try:
        bootstrap = read_bootstrap(sys.stdin)
        sys.dontwritebytecode = True
        os.environ.update(LISHUTTLE_RESOURCE_ROOT=bootstrap['resource_root'],
                          LISHUTTLE_DATA_DIR=bootstrap['data_dir'],
                          LISHUTTLE_PYTHON=sys.executable,
                          LISHUTTLE_DESKTOP='1')
        os.environ.pop('LISHUTTLE_CONFIG_SNAPSHOT', None)
        import core as domain
        import server as web
        core = domain
        routes = dict(web.ROUTES)
        try:
            import desktop_features as additions
        except ModuleNotFoundError as exc:
            if exc.name != 'desktop_features':
                raise
        else:
            features = additions
            routes.update(additions.ROUTES)
        server = create_server(bootstrap['static_dir'], bootstrap['session_secret'], bootstrap['cookie_name'], routes)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .1}, name='desktop-http')
        thread.start()
        emit(dict(type='ready', origin=server.origin))
        while True:
            raw = sys.stdin.readline(MAX_CONTROL + 1)
            if not raw:
                break
            if len(raw) > MAX_CONTROL or not raw.endswith('\n'):
                raise ValueError('Oversized lifecycle message')
            message = json.loads(raw)
            if not isinstance(message, dict):
                raise ValueError('Lifecycle message must be an object')
            if message.get('type') == 'shutdown':
                request_id = message.get('request_id')
                shutdown_requested = True
                break
            if message.get('type') == 'activity':
                activity = core.RUNTIME.snapshot()
                emit(dict(type='activity', request_id=message.get('request_id'),
                          busy=bool(activity['busy']), activity=activity, pid=os.getpid()))
            else:
                emit(dict(type='error', code='UNKNOWN_CONTROL', request_id=message.get('request_id')))
    except (Exception, KeyboardInterrupt) as exc:
        detail = str(exc)
        secret = bootstrap.get('session_secret')
        if secret:
            detail = detail.replace(secret, '[redacted]')
        sys.stderr.write('Desktop service: ' + type(exc).__name__ + ': ' + detail[:1000] + '\n')
        sys.stderr.flush()
        emit(dict(type='error', code='SERVICE_FAILED', message='Desktop service could not continue'))
        return_code = 1
    else:
        return_code = 0
    finally:
        if server is not None:
            server.stopping.set()
            if core is not None:
                # Release synchronous assembly requests through their normal
                # error/transaction rollback path before waiting for HTTP drain.
                core.shutdown_renderers()
            server.shutdown()
            server.server_close()  # Wait for accepted writes before Runner finalization.
        if core is not None:
            core.RUNNER.shutdown()
        if features is not None:
            close = getattr(features, 'close', None)
            if close:
                close()
        if thread is not None:
            thread.join()
    if shutdown_requested:
        ack = dict(type='shutdown', status='stopped')
        if request_id is not None:
            ack['request_id'] = request_id
        emit(ack)
    return return_code


if __name__ == '__main__':
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='strict')
    raise SystemExit(main())
