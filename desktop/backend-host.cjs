'use strict';
const { spawn } = require('node:child_process');
const { EventEmitter } = require('node:events');
const { randomUUID } = require('node:crypto');
const { validateServiceOrigin } = require('./security.cjs');
class BackendHost extends EventEmitter {
  constructor({ executable, args, cwd, bootstrap, startupTimeout = 20000, requestTimeout = 5000, channel = 'dev', log = () => {} }) {
    super(); Object.assign(this, { executable, args, cwd, bootstrap, startupTimeout, requestTimeout, channel, log });
    this.pending = new Map(); this.origin = null; this.child = null; this.buffer = ''; this.stopping = false;
  }
  safeLog(message) { this.log(String(message).split(this.bootstrap.session_secret).join('[redacted]')); }
  async start() {
    if (this.child) throw new Error('Backend already started');
    return new Promise((resolve, reject) => {
      let settled = false;
      const finish = (error, origin) => { if (settled) return; settled = true; clearTimeout(timer); this._startup = null; if (error) { this.forceStop(); reject(error); } else resolve(origin); };
      const timer = setTimeout(() => finish(new Error('Python service startup timed out')), this.startupTimeout);
      this._startup = finish;
      const env = { ...process.env, PYTHONDONTWRITEBYTECODE: '1', PYTHONUNBUFFERED: '1', LISHUTTLE_PYTHON: this.executable, LISHUTTLE_DESKTOP_CHANNEL: this.channel };
      delete env.PYTHONPATH; delete env.PYTHONHOME;
      try { this.child = spawn(this.executable, this.args, { cwd: this.cwd, env, stdio: ['pipe', 'pipe', 'pipe'], shell: false, windowsHide: true }); }
      catch (error) { finish(error); return; }
      this.child.once('error', error => finish(error));
      this.child.stdout.setEncoding('utf8');
      this.child.stdout.on('data', chunk => this.consume(chunk));
      this.child.stderr.setEncoding('utf8');
      this.child.stderr.on('data', chunk => this.safeLog('Python: ' + chunk.slice(0, 32768)));
      this.child.stdin.on('error', error => this.safeLog('Service pipe: ' + error.message));
      this.child.once('exit', (code, signal) => {
        this.exitResult = { code, signal }; this.safeLog('Python supervisor exited (' + code + ', ' + signal + ')');
        const error = new Error('Python service exited (' + code + (signal ? ', ' + signal : '') + ')');
        if (!settled) finish(error);
        for (const pending of this.pending.values()) { clearTimeout(pending.timer); pending.reject(error); } this.pending.clear();
        this.emit('exit', { code, signal, expected: this.stopping });
      });
      this.child.stdin.write(JSON.stringify(this.bootstrap) + '\n');
    });
  }
  consume(chunk) {
    this.buffer += chunk;
    if (this.buffer.length > 131072) { const error = new Error('Service protocol line exceeds limit'); this._startup?.(error); this.safeLog(error.message); this.forceStop(); return; }
    for (;;) {
      const index = this.buffer.indexOf('\n'); if (index < 0) break;
      const line = this.buffer.slice(0, index).trim(); this.buffer = this.buffer.slice(index + 1);
      if (!line) continue;
      let message; try { message = JSON.parse(line); } catch { this.safeLog('Service emitted a non-protocol line'); continue; }
      if (message.type === 'ready') {
        if (this.origin) { this.safeLog('Ignored duplicate ready message'); continue; }
        try { this.origin = validateServiceOrigin(message.origin); this._startup?.(null, this.origin); }
        catch (error) { this._startup?.(error); } continue;
      }
      if (message.request_id && this.pending.has(message.request_id)) {
        const pending = this.pending.get(message.request_id);
        if (pending.type !== message.type) continue;
        this.pending.delete(message.request_id); clearTimeout(pending.timer); pending.resolve(message);
      } else if (message.type === 'error') this.safeLog('Service error: ' + (message.error || message.message || 'unknown'));
    }
  }
  request(type, timeout = this.requestTimeout) {
    if (!this.child || this.exitResult || !this.child.stdin.writable) return Promise.reject(new Error('Service is unavailable'));
    const request_id = randomUUID();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(request_id); reject(new Error('Service ' + type + ' request timed out')); }, timeout);
      this.pending.set(request_id, { type, resolve, reject, timer });
      this.child.stdin.write(JSON.stringify({ type, request_id }) + '\n');
    });
  }
  activity() {
    return this.request('activity').then(value => {
      if (typeof value.busy !== 'boolean') throw new Error('Invalid service activity response');
      return value;
    });
  }
  waitForExit(timeout) {
    if (this.exitResult) return Promise.resolve(this.exitResult);
    return new Promise((resolve, reject) => {
      const onExit = result => { clearTimeout(timer); resolve(result); };
      const timer = setTimeout(() => { this.removeListener('exit', onExit); reject(new Error('Service did not finish shutdown; its owned work may still be finalizing')); }, timeout);
      this.once('exit', onExit);
    });
  }
  async stop({ timeout = 30000 } = {}) {
    if (!this.child || this.exitResult) return;
    this.stopping = true;
    // The ack means domain shutdown and archive finalization have completed.
    await this.request('shutdown', timeout);
    this.child.stdin.end();
    await this.waitForExit(5000);
  }
  forceStop() {
    this.stopping = true;
    if (!this.child || this.exitResult) return;
    // Only this spawned supervisor is terminated. Its Windows Job owns descendants.
    this.child.stdin.destroy();
    this.child.kill();
  }
}
module.exports = { BackendHost };
