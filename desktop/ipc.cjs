'use strict';
const fs = require('node:fs/promises');
const { assertTrustedSender, validateDialogOptions, validateSaveText, absolutePath } = require('./security.cjs');
function registerDesktopIpc({ ipcMain, dialog, shell, getWindow, getOrigin, getInfo, setDirty }) {
  const trusted = event => assertTrustedSender(event, getWindow(), getOrigin());
  const handle = (name, callback) => ipcMain.handle('desktop:' + name, async (event, value) => { trusted(event); return callback(value); });
  handle('pickDirectory', async value => {
    const options = validateDialogOptions(value);
    const result = await dialog.showOpenDialog(getWindow(), { ...options, properties: ['openDirectory'] });
    return result.canceled ? null : result.filePaths[0] || null;
  });
  handle('pickFile', async value => {
    const { extensions, ...options } = validateDialogOptions(value, true);
    const result = await dialog.showOpenDialog(getWindow(), { ...options, properties: ['openFile'], ...(extensions ? { filters: [{ name: 'Files', extensions }] } : {}) });
    return result.canceled ? null : result.filePaths[0] || null;
  });
  handle('saveText', async value => {
    const { suggestedName, text } = validateSaveText(value);
    const result = await dialog.showSaveDialog(getWindow(), { defaultPath: suggestedName, title: '另存为', properties: ['showOverwriteConfirmation'] });
    if (result.canceled || !result.filePath) return { saved: false };
    const target = absolutePath(result.filePath);
    await fs.writeFile(target, text, 'utf8');
    return { saved: true, path: target };
  });
  handle('openPath', async value => {
    const target = absolutePath(value);
    const info = await fs.stat(target);
    if (info.isDirectory()) {
      const error = await shell.openPath(target); if (error) throw new Error(error);
    } else if (info.isFile()) shell.showItemInFolder(target);
    else throw new Error('Path is not a regular file or directory');
  });
  handle('info', () => ({ ...getInfo() }));
  ipcMain.on('desktop:setDirty', (event, value) => {
    try { trusted(event); if (typeof value !== 'boolean') throw new TypeError('Expected dirty boolean'); setDirty(value); }
    catch { /* An untrusted frame must never change close protection. */ }
  });
}
module.exports = { registerDesktopIpc };
