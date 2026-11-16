'use strict';
const fs = require('node:fs'); const path = require('node:path'); const https = require('node:https');
const { createHash } = require('node:crypto'); const { spawnSync } = require('node:child_process');
const PYTHON = Object.freeze({ version: '3.13.17', archive: 'python-3.13.17-embed-amd64.zip',
  sha256: '9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38',
  url: 'https://www.python.org/ftp/python/3.13.17/python-3.13.17-embed-amd64.zip',
  checksumSource: 'https://www.python.org/ftp/python/3.13.17/python-3.13.17-embed-amd64.zip.spdx.json' });
function verifyArchive(file) {
  const hash = createHash('sha256').update(fs.readFileSync(file)).digest('hex');
  if (hash !== PYTHON.sha256) throw new Error('Python archive SHA-256 mismatch: cache cannot be used');
  return hash;
}
function pthContents(layout) {
  if (!['dev', 'packaged'].includes(layout)) throw new Error('Invalid Python path layout');
  const prefix = layout === 'packaged' ? '../workflow/' : '../../';
  return ['python313.zip', '.', prefix + 'platform/backend', prefix + 'scripts', ''].join('\n');
}
async function download(url, destination, redirects = 0) {
  if (redirects > 3) throw new Error('Too many runtime download redirects');
  await new Promise((resolve, reject) => {
    const request = https.get(url, { timeout: 30000 }, response => {
      if ([301,302,303,307,308].includes(response.statusCode)) {
        response.resume(); const next = new URL(response.headers.location, url);
        if (next.protocol !== 'https:' || next.hostname !== 'www.python.org') { reject(new Error('Untrusted Python download redirect')); return; }
        download(next.href, destination, redirects + 1).then(resolve, reject); return;
      }
      if (response.statusCode !== 200) { response.resume(); reject(new Error('Python download returned ' + response.statusCode)); return; }
      const output = fs.createWriteStream(destination, { flags: 'wx' });
      let bytes = 0;
      response.on('data', chunk => { bytes += chunk.length; if (bytes > 30 * 1024 * 1024) request.destroy(new Error('Python archive is unexpectedly large')); });
      response.on('error', reject); output.on('error', reject); output.on('finish', () => output.close(resolve)); response.pipe(output);
    });
    request.on('timeout', () => request.destroy(new Error('Python runtime download timed out')));
    request.on('error', reject);
  });
}
function run(executable, args, options = {}) {
  const result = spawnSync(executable, args, { encoding: 'utf8', shell: false, windowsHide: true, ...options });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error('Embedded Python preparation failed: ' + (result.stderr || result.stdout || result.status));
  return result.stdout.trim();
}
function validateRuntime(directory, { importApplication = false } = {}) {
  for (const name of ['python.exe','python313.dll','python313.zip','python313._pth','LICENSE.txt']) if (!fs.statSync(path.join(directory,name)).isFile()) throw new Error('Missing runtime resource: ' + name);
  const code = 'import sys,ctypes,encodings,xml.etree.ElementTree,http.server,subprocess,sqlite3,ssl,json; assert sys.version_info[:3]==(3,13,17); ' +
    (importApplication ? 'import runtime_paths,project_config,desktop_entry; ' : '') +
    'print(json.dumps({"version":sys.version.split()[0],"isolated":sys.flags.isolated,"executable":sys.executable}))';
  const env = { ...process.env, PYTHONDONTWRITEBYTECODE:'1' }; delete env.PYTHONPATH; delete env.PYTHONHOME;
  return JSON.parse(run(path.join(directory,'python.exe'), ['-B','-c',code], { env, cwd: directory }));
}
function validateOutputDirectory(root,directory) {
  const scratch=path.resolve(root,'.desktop-build');const output=path.resolve(directory);const relative=path.relative(scratch,output);
  if(!relative || relative.startsWith('..'+path.sep) || relative==='..' || path.isAbsolute(relative))throw new Error('Runtime output must be inside the build directory');
  for(let current=output;current!==path.dirname(scratch);current=path.dirname(current))if(fs.existsSync(current)&&fs.lstatSync(current).isSymbolicLink())throw new Error('Runtime build directory cannot contain links');
  return output;
}
async function preparePython({ root = path.resolve(__dirname,'..'), offline = false, layout = 'dev', outputDir } = {}) {
  if (process.platform !== 'win32') throw new Error('Windows x64 is required to prepare the embedded Windows runtime');
  const scratch = path.join(root,'.desktop-build'); const cache = path.join(scratch,'cache');
  fs.mkdirSync(cache,{recursive:true}); const archive = path.join(cache,PYTHON.archive);
  if (!fs.existsSync(archive)) {
    if (offline) throw new Error('Pinned Python archive is absent from the offline build cache');
    const temporary = archive + '.download-' + process.pid;
    try { await download(PYTHON.url,temporary); verifyArchive(temporary); fs.renameSync(temporary,archive); }
    finally { fs.rmSync(temporary,{force:true}); }
  }
  verifyArchive(archive);
  const directory = validateOutputDirectory(root,outputDir || path.join(scratch, layout === 'packaged' ? 'python-package' : 'python')); fs.rmSync(directory,{recursive:true,force:true});
  fs.mkdirSync(directory,{recursive:true});
  const currentManifest = path.join(directory,'runtime-manifest.json');
  const powershell = path.join(process.env.SystemRoot || 'C:\Windows','System32','WindowsPowerShell','v1.0','powershell.exe');
  // Always extract from the checksum-verified archive: never execute a reused,
  // potentially modified interpreter from a previous build directory.
  run(powershell,['-NoLogo','-NoProfile','-NonInteractive','-Command',"Expand-Archive -LiteralPath $env:LISHUTTLE_ARCHIVE -DestinationPath $env:LISHUTTLE_RUNTIME -Force"],
    {env:{...process.env,LISHUTTLE_ARCHIVE:archive,LISHUTTLE_RUNTIME:directory}});
  fs.writeFileSync(path.join(directory,'python313._pth'),pthContents(layout),'utf8');
  fs.writeFileSync(currentManifest,JSON.stringify({...PYTHON,archiveSha256:PYTHON.sha256,layout},null,2)+'\n');
  const validation = validateRuntime(directory);
  return { directory, validation, manifest: PYTHON };
}
if (require.main === module) preparePython({offline:process.argv.includes('--offline')}).then(result=>console.log(JSON.stringify(result,null,2))).catch(error=>{console.error(error.message);process.exitCode=1;});
module.exports = { PYTHON, verifyArchive, pthContents, validateRuntime, validateOutputDirectory, preparePython };
