'use strict';
const fs=require('node:fs');const path=require('node:path');const {createHash}=require('node:crypto');
function isAllowedWorkflowFile(file){
 if(typeof file!=='string'||file.includes('\\')||file.split('/').some(part=>['..','.',''].includes(part)))return false;
 const backend = new Set(['core','log_stream','desktop_entry','desktop_features','desktop_supervisor','discovery','engineering_format','engineering','function_profiles','indoor_building_export','managed_process','render_process','migration','parameter_catalog','preflight','resource_lock','result_validation','run_guard','run_history','runtime_cleanup','runtime_configs','server','vs_launch'].map(name=>'platform/backend/'+name+'.py'));
 const scripts = new Set(['dll_dependencies','file_safety','indoor_maps','patch_gongcan','project_config','project_detection','project_workflow','render_schema','run_local','runtime_paths','task_schema'].map(name=>'scripts/'+name+'.py'));
 const batches = new Set(['build_local','doctor_local','load_local_env','run_local','stage_local','validate_local_python'].map(name=>'scripts/'+name+'.bat'));
 return backend.has(file) || scripts.has(file) || batches.has(file) ||
  ['platform/backend/params_spec.json','platform/backend/function_profile_sources.json','templates/runtimeschema.xml.tpl','templates/runtimeschema-indoor.xml.tpl'].includes(file) ||
  /^desktop-ui\/dist\/(?:assets\/)?[a-z0-9_.@-]+\.(?:html|js|css|svg|png|ico|woff2?)$/i.test(file);
}
function hashTree(directory){
 const result={};
 function visit(dir){for(const name of fs.readdirSync(dir).sort()){const file=path.join(dir,name);const stat=fs.lstatSync(file);if(stat.isSymbolicLink())throw new Error('Package contains a link: '+file);if(stat.isDirectory())visit(file);else if(stat.isFile())result[path.relative(directory,file).split(path.sep).join('/')]=createHash('sha256').update(fs.readFileSync(file)).digest('hex');else throw new Error('Package contains a special file');}}
 visit(directory);return result;
}
function verifyManifestTree(directory,expected,allowed=()=>true){
 const actual=hashTree(directory);
 for(const [name,hash]of Object.entries(actual)){if(!allowed(name))throw new Error('Package file is not allowed: '+name);if(!(name in expected))throw new Error('Unexpected package file: '+name);if(expected[name]!==hash)throw new Error('Package resource hash changed: '+name);}
 for(const name of Object.keys(expected))if(!(name in actual))throw new Error('Missing package resource: '+name);
 return Object.keys(actual).length;
}
function verifyPackage(unpacked){
 const resources=path.join(unpacked,'resources'),info=JSON.parse(fs.readFileSync(path.join(resources,'build-info.json'),'utf8'));
 if(!['stable','dev'].includes(info.channel)||info.version!==require('../package.json').version||!info.unsigned)throw new Error('Invalid build metadata');
 const unexpected=fs.readdirSync(resources).filter(name=>!['app.asar','workflow','python','third-party','build-info.json'].includes(name));if(unexpected.length)throw new Error('Unexpected top-level resources: '+unexpected.join(', '));
 const workflow=path.join(resources,'workflow'),python=path.join(resources,'python');
 const workflowFiles=verifyManifestTree(workflow,info.workflowHashes,isAllowedWorkflowFile);
 const runtimeFiles=verifyManifestTree(python,info.pythonHashes);
 const noticeFiles=verifyManifestTree(path.join(resources,'third-party'),info.noticeHashes);
 for(const required of ['platform/backend/desktop_entry.py','platform/backend/desktop_supervisor.py','platform/backend/core.py','platform/backend/render_process.py','platform/backend/params_spec.json','scripts/runtime_paths.py','scripts/render_schema.py','scripts/build_local.bat','templates/runtimeschema.xml.tpl','templates/runtimeschema-indoor.xml.tpl','desktop-ui/dist/index.html'])if(!info.workflowHashes[required])throw new Error('Required workflow file missing: '+required);
 for(const required of ['python.exe','python313.dll','python313.zip','python313._pth','LICENSE.txt','runtime-manifest.json'])if(!info.pythonHashes[required])throw new Error('Required Python file missing: '+required);
 const runtime=JSON.parse(fs.readFileSync(path.join(python,'runtime-manifest.json'),'utf8'));const pin=require('./prepare-python.cjs').PYTHON;
 if(runtime.archiveSha256!==pin.sha256||runtime.version!==pin.version)throw new Error('Unpinned Python runtime');
 if(fs.readFileSync(path.join(python,'python313._pth'),'utf8')!==require('./prepare-python.cjs').pthContents('packaged'))throw new Error('Invalid packaged Python search paths');
 const asar=require('@electron/asar');const archive=path.join(resources,'app.asar');
 const appMetadata=JSON.parse(asar.extractFile(archive,'package.json').toString('utf8'));
 if(appMetadata.name!=='lishuttle-workflow-desktop'||appMetadata.version!==info.version||appMetadata.desktopChannel!==info.channel)throw new Error('Application metadata differs from build');
 const archiveFiles=asar.listPackage(archive).map(file=>file.replace(/\\/g,'/').replace(/^\//,''));
 for(const required of ['desktop/main.cjs','desktop/preload.cjs','desktop/backend-host.cjs','desktop/security.cjs','desktop/paths.cjs','desktop/ipc.cjs','desktop/session-export.cjs','desktop/status.html','package.json'])if(!archiveFiles.includes(required))throw new Error('Required application archive file missing: '+required);
 for(const name of archiveFiles){if(!name.includes('.')&&!name.includes('tests'))continue;if(!/^(package\.json|desktop\/(?:main|preload|backend-host|security|paths|ipc|session-export)\.cjs|desktop\/status\.html)$/.test(name))throw new Error('Unexpected application archive content: '+name);}
 for(const file of ['LICENSE.electron.txt','LICENSES.chromium.html'])if(!fs.existsSync(path.join(unpacked,file)))throw new Error('Missing Electron/Chromium license: '+file);
 const validation=require('./prepare-python.cjs').validateRuntime(python,{importApplication:true});
 return {channel:info.channel,version:info.version,workflowFiles,runtimeFiles,noticeFiles,python:validation.version,archiveFiles:archiveFiles.length,unsigned:info.unsigned};
}
function writeChecksums(directory){
 const hashes=hashTree(directory);const entries=Object.entries(hashes).filter(([name])=>name!=='SHA256SUMS.txt'&&!name.startsWith('win-unpacked/'));
 fs.writeFileSync(path.join(directory,'SHA256SUMS.txt'),entries.map(([name,hash])=>hash+'  '+name).join('\n')+'\n');return entries.length;
}
if(require.main===module){try{console.log(JSON.stringify(verifyPackage(path.resolve(process.argv[2]||'release/stable/'+require('../package.json').version+'/win-unpacked')),null,2));}catch(error){console.error(error.stack||error.message);process.exitCode=1;}}
module.exports={isAllowedWorkflowFile,hashTree,verifyManifestTree,verifyPackage,writeChecksums};
