'use strict';
const path = require('node:path');
function resolvePaths({ isPackaged, resourcesPath, sourceRoot = path.resolve(__dirname, '..'), localAppData, channel = 'dev' }) {
  if (!['stable', 'dev'].includes(channel)) throw new Error('Unsupported desktop channel');
  if (!localAppData || !path.isAbsolute(localAppData)) throw new Error('LOCALAPPDATA must be an absolute path');
  const suffix = channel === 'dev' ? '-Dev' : '';
  const dataDir = path.join(localAppData, 'LiShuttleWorkflow' + suffix);
  const resourceRoot = isPackaged ? path.join(resourcesPath, 'workflow') : sourceRoot;
  return Object.freeze({ channel, appId: 'com.lishuttle.workflow' + (channel === 'dev' ? '.dev' : ''),
    productName: 'LiShuttle Workflow' + (channel === 'dev' ? ' (Dev)' : ''), dataDir,
    userData: path.join(dataDir, 'electron'), sessionData: path.join(dataDir, 'electron', 'session'),
    logsDir: path.join(dataDir, 'logs'), resourceRoot,
    staticDir: path.join(resourceRoot, 'desktop-ui', 'dist'),
    python: isPackaged ? path.join(resourcesPath, 'python', 'python.exe') : path.join(sourceRoot, '.desktop-build', 'python', 'python.exe'),
    supervisor: path.join(resourceRoot, 'platform', 'backend', 'desktop_supervisor.py') });
}
function windowBounds({ width, height }) {
  width = Math.max(320, Math.floor(width)); height = Math.max(240, Math.floor(height));
  return { width: Math.min(1440, width), height: Math.min(900, height), minWidth: Math.min(1100, width), minHeight: Math.min(700, height) };
}
module.exports = { resolvePaths, windowBounds };
