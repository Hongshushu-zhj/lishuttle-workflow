"""Decoded stdout events: durable ordered replay, bounded reads, no client callbacks."""
import codecs
from collections import deque
import json
import os
import re
from pathlib import Path
import struct
import threading


class OutputDecoder:
    def __init__(self, encoding='gbk'):
        self.encoding = codecs.lookup(encoding).name
        if self.encoding not in ('gbk', 'utf-8'):
            raise ValueError('日志编码只支持 GBK 或 UTF-8')
        self.decoder = codecs.getincrementaldecoder(self.encoding)(errors='replace')
        self.pending = []
        self.cr = False

    def feed(self, raw, final=False):
        text = self.decoder.decode(raw, final=final)
        lines = []
        for part in re.split(r'([\r\n])', text):
            if not part:
                continue
            if self.cr:
                self.cr = False
                if part == '\n':
                    continue
            if part in ('\r', '\n'):
                lines.append(''.join(self.pending))
                self.pending = []
                self.cr = part == '\r'
            else:
                self.pending.append(part)
        if final and self.pending:
            lines.append(''.join(self.pending))
            self.pending = []
        return text, lines


class EventJournal:
    """Fixed-width disk index permits bounded replay from any sequence.

    A published event has already been flushed/fsynced. Network I/O never holds
    this lock. The optional cache is bounded by event count AND event size.
    """
    def __init__(self, directory, sid, encoding, cache_size=128):
        self.directory = Path(directory)
        self.sid = sid
        self.encoding = encoding
        self.condition = threading.Condition()
        self.cache = deque(maxlen=cache_size)
        self.sequence = 0
        self.ended = False
        self.failure = None
        self.sealed = False
        self.terminal_ready = True
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / 'events.jsonl').touch()
        (self.directory / 'events.idx').touch()
        (self.directory / 'stream.json').write_text(json.dumps({'version':1, 'sid':sid, 'encoding':encoding}), encoding='utf-8')

    @classmethod
    def open(cls, directory, sid):
        directory = Path(directory)
        if not (directory / 'stream.json').is_file():
            return None
        obj = cls.__new__(cls)
        if (directory / 'stream.failed').exists():
            raise OSError('日志事件持久化失败，无法确认完整性')
        metadata = json.loads((directory / 'stream.json').read_text(encoding='utf-8'))
        if metadata.get('version') != 1 or str(metadata.get('sid')) != str(sid):
            raise OSError('日志事件元数据无效')
        obj.directory, obj.sid, obj.encoding = directory, sid, metadata['encoding']
        obj.condition = threading.Condition()
        obj.cache = deque(maxlen=128)
        index_size = (directory / 'events.idx').stat().st_size
        if index_size % 8:
            raise OSError('日志事件索引不完整')
        obj.sequence = index_size // 8
        obj.failure = None
        obj.sealed = True
        obj.terminal_ready = True
        obj._validate_disk()
        obj.ended = True  # Reopened history is a finite snapshot, even after a crash.
        return obj

    @staticmethod
    def _decode_event(raw, sid, expected):
        try:
            if not raw.endswith(b'\n'):
                raise ValueError('incomplete record')
            event = json.loads(raw)
            if (str(event.get('sid')) != str(sid) or type(event.get('seq')) is not int
                    or event['seq'] != expected or event.get('kind') not in ('text', 'end')
                    or (event['kind'] == 'text' and
                        (not isinstance(event.get('text'), str) or len(event['text']) > 4096))):
                raise ValueError('invalid record')
            return event
        except (ValueError, TypeError, AttributeError) as exc:
            raise OSError('日志事件序列或内容损坏') from exc

    def _validate_disk(self):
        # A reopened journal has no trusted in-memory cursor. Validate all
        # offsets and records in bounded memory before serving it.
        with (self.directory / 'events.idx').open('rb') as index, (self.directory / 'events.jsonl').open('rb') as data:
            ended = False
            for sequence in range(1, self.sequence + 1):
                raw_offset = index.read(8)
                if len(raw_offset) != 8 or struct.unpack('<Q', raw_offset)[0] != data.tell() or ended:
                    raise OSError('日志事件索引损坏')
                event = self._decode_event(data.readline(32768), self.sid, sequence)
                ended = event['kind'] == 'end'
            if data.read(1):
                raise OSError('日志事件存在未提交尾部')

    def _failed_append(self, data_size, index_size, error):
        self.failure = '日志事件保存失败：' + str(error)
        self.ended = True
        # A failed fsync may still have changed the files. Roll BOTH files back
        # to the last published prefix and never retry this writer's sequence.
        for name, size in (('events.idx', index_size), ('events.jsonl', data_size)):
            try:
                with (self.directory / name).open('r+b') as file:
                    file.truncate(size); file.flush(); os.fsync(file.fileno())
            except OSError:
                pass  # Reopen validates both files even if rollback cannot persist.
        try:
            with (self.directory / 'stream.failed').open('wb') as marker:
                marker.write(b'journal write failed\n'); marker.flush(); os.fsync(marker.fileno())
        except OSError:
            pass
        self.condition.notify_all()

    def append(self, text='', kind='text', defer_complete=False):
        # At most 4096 characters/event even for synthetic producers.
        if len(text) > 4096:
            for start in range(0, len(text), 4096):
                self.append(text[start:start+4096], kind)
            return
        with self.condition:
            if self.failure:
                raise OSError(self.failure)
            if self.ended or self.sealed:
                raise ValueError('日志已结束')
            event = {'sid': self.sid, 'seq': self.sequence + 1, 'kind':kind}
            if kind == 'text':
                event['text'] = text
            data = (json.dumps(event, ensure_ascii=False) + '\n').encode('utf-8')
            offset = (self.directory / 'events.jsonl').stat().st_size
            index_size = (self.directory / 'events.idx').stat().st_size
            try:
                with (self.directory / 'events.jsonl').open('ab') as output:
                    output.write(data); output.flush(); os.fsync(output.fileno())
                with (self.directory / 'events.idx').open('ab') as index:
                    index.write(struct.pack('<Q', offset)); index.flush(); os.fsync(index.fileno())
            except OSError as exc:
                self._failed_append(offset, index_size, exc)
                raise
            self.sequence += 1
            self.cache.append(event)
            if kind == 'end':
                self.sealed = True
                self.ended = not defer_complete
            self.condition.notify_all()

    def finish(self, defer_complete=False):
        self.append(kind='end', defer_complete=defer_complete)

    def complete(self):
        with self.condition:
            self.terminal_ready = True
            self.ended = True
            self.condition.notify_all()

    def fail(self, error):
        with self.condition:
            self.failure = '日志事件保存失败：' + str(error)
            self.ended = True
            try:
                with (self.directory / 'stream.failed').open('wb') as marker:
                    marker.write(b'journal write failed\n'); marker.flush(); os.fsync(marker.fileno())
            except OSError:
                pass
            self.condition.notify_all()

    def read(self, after, limit=64):
        limit = max(1, min(128, int(limit)))
        with self.condition:
            if self.failure:
                raise OSError(self.failure)
            total = self.sequence
            if after < 0 or after > total:
                raise ValueError('日志事件游标无效')
            count = min(limit, total - after)
            if not count:
                return []
            if self.cache and after >= self.cache[0]['seq'] - 1:
                return [dict(e) for e in self.cache if e['seq'] > after][:count]
        # The captured prefix is immutable. Read outside the producer lock.
        with (self.directory / 'events.idx').open('rb') as index:
            index.seek(after * 8)
            raw_offset = index.read(8)
            if len(raw_offset) != 8:
                raise OSError('日志事件索引不完整')
            offset = struct.unpack('<Q', raw_offset)[0]
        with (self.directory / 'events.jsonl').open('rb') as source:
            source.seek(offset)
            return [self._decode_event(source.readline(32768), self.sid, after + n + 1) for n in range(count)]

    def wait(self, after, timeout=.5):
        with self.condition:
            if self.sequence <= after and not self.ended:
                self.condition.wait(timeout)


class LogStreamResponse:
    def __init__(self, journal, after=0):
        self.journal, self.after = journal, after
        # A reconnect after capture failure still needs the terminal result;
        # do not turn this into a permanent HTTP-error/retry loop.
        with journal.condition:
            if after < 0 or after > journal.sequence:
                raise ValueError('日志事件游标无效')
            if not journal.failure:
                journal.read(after, 1)

    def send(self, handler):
        stopping = getattr(handler.server, 'stopping', threading.Event())
        handler.connection.settimeout(2)
        handler.send_response(200)
        handler.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('X-Accel-Buffering', 'no')
        handler.end_headers()
        cursor = self.after
        try:
            handler.wfile.write(b': connected\n\n'); handler.wfile.flush()
            idle = 0
            while not stopping.is_set():
                events = self.journal.read(cursor)
                for event in events:
                    if stopping.is_set():
                        break
                    packet = 'id: {0}\nevent: output\ndata: {1}\n\n'.format(event['seq'], json.dumps(event, ensure_ascii=False))
                    handler.wfile.write(packet.encode('utf-8')); handler.wfile.flush()
                    cursor = event['seq']
                # Capture may fail after read() returns an empty batch. Decide
                # terminal state under the same condition used by fail/complete;
                # never infer success from ended alone. Socket I/O stays outside.
                with self.journal.condition:
                    if self.journal.failure:
                        raise OSError(self.journal.failure)
                    complete = (self.journal.terminal_ready and self.journal.ended
                                and self.journal.sealed and cursor >= self.journal.sequence)
                if complete and not stopping.is_set():
                    handler.wfile.write(('event: complete\ndata: '+json.dumps({'sid':self.journal.sid,'seq':cursor})+'\n\n').encode())
                    handler.wfile.flush()
                    return
                self.journal.wait(cursor, .5)
                idle += 1
                if idle >= 20:
                    handler.wfile.write(b': heartbeat\n\n'); handler.wfile.flush(); idle = 0
            handler.wfile.write(b'event: stopping\ndata: {}\n\n'); handler.wfile.flush()
        except (OSError, TimeoutError):
            if self.journal.failure:
                try:
                    # Capture can fail before process termination/validation.
                    # A terminal SSE event must wait for the final result, while
                    # service shutdown must still interrupt this non-daemon request.
                    ticks = 0
                    while not stopping.is_set():
                        with self.journal.condition:
                            if self.journal.terminal_ready:
                                break
                            self.journal.condition.wait(.5)
                        ticks += 1
                        if ticks % 20 == 0:
                            handler.wfile.write(b': finalizing\n\n'); handler.wfile.flush()
                    name = b'stopping' if stopping.is_set() else b'failed'
                    handler.wfile.write(b'event: ' + name + b'\ndata: {}\n\n'); handler.wfile.flush()
                except OSError:
                    pass  # A disconnected reader never affects process capture.
        finally:
            handler.close_connection = True


class LogExportResponse:
    def __init__(self, sid, record, journal=None, legacy_path=None):
        if journal is not None and getattr(journal, 'failure', None):
            raise OSError(journal.failure)
        self.sid, self.record, self.journal = sid, record, journal
        self.sequence = journal.sequence if journal else 0
        self.legacy_path = legacy_path
        self.size = Path(legacy_path).stat().st_size if legacy_path else 0

    def chunks(self, stopping=None):
        record = self.record
        header = ['LiShuttle Workflow 运行日志', '固定会话：'+str(self.sid),
                  '项目：'+str(record.get('context', {}).get('project', '')),
                  '状态：'+str(record.get('status', '')), '退出码：'+str(record.get('exit')),
                  ('截至导出快照事件：'+str(self.sequence) if self.journal else '截至导出快照字节：'+str(self.size)), '','']
        yield '\r\n'.join(header).encode('utf-8')
        if self.journal:
            cursor = 0
            while cursor < self.sequence:
                if stopping is not None and stopping.is_set():
                    raise OSError('日志导出已随服务关闭而中止')
                events = self.journal.read(cursor, min(64, self.sequence-cursor))
                if not events:
                    raise OSError('日志快照读取不完整')
                for event in events:
                    if event.get('seq') != cursor + 1 or event['seq'] > self.sequence:
                        raise OSError('日志快照序列不连续')
                    cursor = event['seq']
                    if event['kind'] == 'text':
                        yield event['text'].encode('utf-8')
        elif self.legacy_path:
            with Path(self.legacy_path).open('rb') as source:
                remaining = self.size
                while remaining:
                    if stopping is not None and stopping.is_set():
                        raise OSError('日志导出已随服务关闭而中止')
                    chunk = source.read(min(65536, remaining))
                    if not chunk:
                        raise OSError('日志快照读取不完整')
                    remaining -= len(chunk)
                    yield chunk

    def send(self, handler):
        handler.connection.settimeout(2)
        stopping = getattr(handler.server, 'stopping', threading.Event())
        length = sum(len(chunk) for chunk in self.chunks(stopping))
        handler.send_response(200)
        handler.send_header('Content-Type', 'text/plain; charset=utf-8')
        handler.send_header('Content-Length', str(length))
        handler.send_header('Content-Disposition', 'attachment; filename="lishuttle-session-'+str(self.sid)+'.log"')
        handler.end_headers()
        try:
            for chunk in self.chunks(stopping):
                if getattr(handler.server, 'stopping', threading.Event()).is_set():
                    break
                handler.wfile.write(chunk)
            handler.wfile.flush()
        except (OSError, TimeoutError):
            pass
        finally:
            handler.close_connection = True
