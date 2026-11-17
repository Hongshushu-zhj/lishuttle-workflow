'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('desktop', Object.freeze({
  pickDirectory: options => ipcRenderer.invoke('desktop:pickDirectory', options),
  pickFile: options => ipcRenderer.invoke('desktop:pickFile', options),
  exportSessionLog: options => ipcRenderer.invoke('desktop:exportSessionLog', options),
  saveText: options => ipcRenderer.invoke('desktop:saveText', options),
  openPath: value => ipcRenderer.invoke('desktop:openPath', value),
  info: () => ipcRenderer.invoke('desktop:info'),
  setDirty: value => ipcRenderer.send('desktop:setDirty', value)
}));
