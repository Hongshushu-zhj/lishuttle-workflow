'use strict';
const path = require('node:path');
const blockedPorts = new Set([2049,3659,4045,5060,5061,6000,6566,6665,6666,6667,6668,6669,6697,10080]);
function validateServiceOrigin(value) {
  if (typeof value !== 'string' || !/^http:\/\/127\.0\.0\.1:[0-9]{4,5}$/.test(value)) throw new Error('Invalid service origin');
  const url = new URL(value);
  const port = Number(url.port);
  if (url.origin !== value || port < 1024 || port > 65535 || blockedPorts.has(port)) throw new Error('Invalid service origin port');
  return value;
}
function isAllowedNavigation(value, origin) {
  try { const url = new URL(value); return url.origin === origin && url.protocol === 'http:' && !url.username && !url.password; } catch { return false; }
}
function assertTrustedSender(event, window, origin) {
  if (!window || window.isDestroyed() || !origin || event.sender !== window.webContents ||
      event.senderFrame !== window.webContents.mainFrame || !isAllowedNavigation(event.senderFrame.url, origin)) throw new Error('Untrusted desktop IPC sender');
}
function plain(value, keys) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.getPrototypeOf(value) !== Object.prototype || Object.keys(value).some(key => !keys.includes(key))) throw new TypeError('Invalid desktop arguments');
}
function text(value, label, max = 1024) {
  if (typeof value !== 'string' || value.length > max || /[\0-\x1f\x7f]/.test(value)) throw new TypeError('Invalid ' + label);
  return value;
}
function absolutePath(value) {
  text(value, 'path', 32760);
  if (!path.isAbsolute(value) || /^[a-z][a-z\d+.-]*:\/\//i.test(value) || value.startsWith('\\\\?\\') || value.startsWith('\\\\.\\')) throw new TypeError('Expected an absolute local filesystem path');
  return value;
}
function validateDialogOptions(value = {}, file = false) {
  plain(value, file ? ['title', 'defaultPath', 'extensions'] : ['title', 'defaultPath']);
  const result = {};
  if (value.title !== undefined) result.title = text(value.title, 'dialog title', 160);
  if (value.defaultPath !== undefined && value.defaultPath !== '') result.defaultPath = absolutePath(value.defaultPath);
  if (value.extensions !== undefined) {
    if (!file || !Array.isArray(value.extensions) || value.extensions.length < 1 || value.extensions.length > 20 ||
        value.extensions.some(ext => typeof ext !== 'string' || !/^[a-z0-9]{1,16}$/i.test(ext))) throw new TypeError('Invalid file extensions');
    result.extensions = [...value.extensions];
  }
  return result;
}
function validateSaveText(value) {
  plain(value, ['suggestedName', 'text']);
  const suggestedName = text(value.suggestedName, 'suggestedName', 160);
  if (!suggestedName || /[\\/:*?"<>|]/.test(suggestedName) || /[. ]$/.test(suggestedName) || /^(con|prn|aux|nul|com\d|lpt\d)(\.|$)/i.test(suggestedName)) throw new TypeError('Invalid suggested filename');
  if (typeof value.text !== 'string' || Buffer.byteLength(value.text, 'utf8') > 16 * 1024 * 1024) throw new TypeError('Text export exceeds 16 MiB');
  return { suggestedName, text: value.text };
}
module.exports = { validateServiceOrigin, isAllowedNavigation, assertTrustedSender, validateDialogOptions, validateSaveText, absolutePath };
