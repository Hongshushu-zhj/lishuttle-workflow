'use strict';
const fs=require('node:fs');const path=require('node:path');const {spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'..');
function resolveBuildTarget({mode,channel='stable',version='0.1.0'}){
 if(!['dev','pack','dist'].includes(mode))throw new Error('Mode must be dev, pack or dist');
 if(!['stable','dev'].includes(channel))throw new Error('Channel must be stable or dev');
 if(!/^\d+\.\d+\.\d+(?:-[a-z0-9.-]+)?$/.test(version))throw new Error('Invalid release version');
 return {mode,channel,version,appId:'com.lishuttle.workflow'+(channel==='dev'?'.dev':''),productName:'LiShuttle Workflow'+(channel==='dev'?' (Dev)':''),output:'release/'+channel,
 artifactName:'LiShuttle-Workflow'+(channel==='dev'?'-Dev':'')+'-Setup-'+version+'-${arch}.${ext}'};
}
function run(executable,args,cwd=root,options={}){
 const result=spawnSync(executable,args,{cwd,stdio:'inherit',shell:false,windowsHide:true,...options});if(result.error)throw result.error;if(result.status!==0)throw new Error(path.basename(executable)+' exited '+result.status);return result;
}
function stageWorkflow(sourceRoot,destination){
 const {isAllowedWorkflowFile}=require('./package-verify.cjs');
 fs.mkdirSync(destination,{recursive:true});
 for(const source of ['platform/backend','scripts','templates','desktop-ui/dist']){
  const start=path.join(sourceRoot,source);if(!fs.existsSync(start))throw new Error('Missing package source '+source);
  function visit(directory){for(const name of fs.readdirSync(directory).sort()){
   const file=path.join(directory,name),stat=fs.lstatSync(file);if(stat.isSymbolicLink())throw new Error('Refusing source link: '+file);
   if(stat.isDirectory()){if(!['__pycache__','node_modules'].includes(name))visit(file);continue;}
   const relative=path.relative(sourceRoot,file).split(path.sep).join('/');
   if(!isAllowedWorkflowFile(relative))continue;
   const target=path.join(destination,relative);fs.mkdirSync(path.dirname(target),{recursive:true});fs.copyFileSync(file,target);
  }}visit(start);
 }
}
function createNotices(directory){
 fs.mkdirSync(directory,{recursive:true});fs.copyFileSync(path.join(root,'THIRD_PARTY_NOTICES.md'),path.join(directory,'THIRD_PARTY_NOTICES.md'));
 const entries=[{name:'Electron',version:require('electron/package.json').version,license:'MIT',text:fs.readFileSync(path.join(path.dirname(require('electron')),'LICENSE'),'utf8')},
 {name:'Chromium and bundled libraries',version:'included with Electron',license:'multiple',text:'Full licenses are distributed beside the application as LICENSES.chromium.html.'},
 {name:'CPython',version:require('./prepare-python.cjs').PYTHON.version,license:'PSF-2.0 and bundled licenses',text:fs.readFileSync(path.join(root,'.desktop-build','python','LICENSE.txt'),'utf8')}];
 const lock=JSON.parse(fs.readFileSync(path.join(root,'desktop-ui','package-lock.json'),'utf8'));
 for(const [relative,entry]of Object.entries(lock.packages||{})){
  if(!relative||entry.dev||!relative.includes('node_modules/'))continue;
  const moduleDir=path.join(root,'desktop-ui',relative);
  if(!fs.existsSync(moduleDir))throw new Error('Cannot obtain bundled UI dependency license: '+relative);
  const metadata=JSON.parse(fs.readFileSync(path.join(moduleDir,'package.json'),'utf8'));
  const licenseFiles=fs.readdirSync(moduleDir).filter(name=>/^(licen[cs]e|copying|notice)(?:[.-]|$)/i.test(name)&&fs.statSync(path.join(moduleDir,name)).isFile());
  const knownNotice = metadata.name === 'lodash-unified' && metadata.version === '1.0.3' && metadata.license === 'MIT' ? path.join(root,'desktop','notices','lodash-unified-1.0.3-MIT.txt') : null; if(!licenseFiles.length&&!knownNotice)throw new Error('License text missing for shipped dependency '+metadata.name);
  entries.push({name:metadata.name,version:metadata.version,license:entry.license||metadata.license||'See license text',text:licenseFiles.length ? licenseFiles.map(name=>fs.readFileSync(path.join(moduleDir,name),'utf8')).join('\n\n') : fs.readFileSync(knownNotice,'utf8')});
 }
 entries.sort((a,b)=>a.name.localeCompare(b.name));
 fs.writeFileSync(path.join(directory,'licenses.txt'),entries.map(entry=>'='.repeat(72)+'\n'+entry.name+' '+entry.version+'\nLicense: '+entry.license+'\n\n'+entry.text).join('\n\n'),'utf8');
 fs.writeFileSync(path.join(directory,'components.json'),JSON.stringify(entries.map(({text,...entry})=>entry),null,2)+'\n');
 return entries.length;
}
async function main(){
 const mode=process.argv[2]||'dist';const option=name=>{const i=process.argv.indexOf(name);return i<0?undefined:process.argv[i+1];};
 const target=resolveBuildTarget({mode,channel:option('--channel')||(mode==='dev'?'dev':'stable'),version:require('../package.json').version});
 const {preparePython,pthContents}=require('./prepare-python.cjs');await preparePython({root,offline:process.argv.includes('--offline')});
 const npm=process.env.npm_execpath||path.join(path.dirname(process.execPath),'node_modules','npm','bin','npm-cli.js');
 if(!process.argv.includes('--skip-ui-build'))run(process.execPath,[npm,'run','build'],path.join(root,'desktop-ui'));
 if(mode==='dev'){run(require('electron'),[root]);return;}
 const scratch=path.join(root,'.desktop-build'),workflow=path.join(scratch,'workflow'),python=path.join(scratch,'python-package'),notices=path.join(scratch,'third-party');
 for(const directory of [workflow,python,notices])fs.rmSync(directory,{recursive:true,force:true});
 stageWorkflow(root,workflow);fs.cpSync(path.join(scratch,'python'),python,{recursive:true});
 fs.writeFileSync(path.join(python,'python313._pth'),pthContents('packaged'));
 const runtimeManifest=JSON.parse(fs.readFileSync(path.join(python,'runtime-manifest.json'),'utf8'));runtimeManifest.layout='packaged';fs.writeFileSync(path.join(python,'runtime-manifest.json'),JSON.stringify(runtimeManifest,null,2)+'\n');
 const noticeComponents=createNotices(notices);
 const revision=spawnSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8',windowsHide:true});
 const status=spawnSync('git',['status','--porcelain','--untracked-files=normal'],{cwd:root,encoding:'utf8',windowsHide:true});
 if(revision.status!==0||status.status!==0)throw new Error('Cannot record source revision');
 const {hashTree,verifyPackage,writeChecksums}=require('./package-verify.cjs');
 const info={version:target.version,channel:target.channel,appId:target.appId,unsigned:true,revision:revision.stdout.trim(),workingTreeDirty:!!status.stdout.trim(),electron:require('electron/package.json').version,python:require('./prepare-python.cjs').PYTHON.version,noticeComponents,
 workflowHashes:hashTree(workflow),pythonHashes:hashTree(python),noticeHashes:hashTree(notices)};
 fs.writeFileSync(path.join(scratch,'build-info.json'),JSON.stringify(info,null,2)+'\n');
 await require('electron-builder').build({config:{extends:path.join(root,'electron-builder.yml'),appId:target.appId,productName:target.productName,artifactName:target.artifactName,
 afterPack:async context=>{fs.rmSync(path.join(context.appOutDir,'resources','default_app.asar'),{force:true});},directories:{output:path.join(root,target.output)},extraMetadata:{version:target.version,desktopChannel:target.channel,productName:target.productName},electronDist:path.dirname(require('electron'))},dir:mode==='pack'});
 const report=verifyPackage(path.join(root,target.output,'win-unpacked'));fs.writeFileSync(path.join(root,target.output,'package-verification.json'),JSON.stringify(report,null,2)+'\n');writeChecksums(path.join(root,target.output));console.log(JSON.stringify(report,null,2));
}
if(require.main===module)main().then(()=>process.exit(0),error=>{console.error(error.stack||error.message);process.exit(1);});
module.exports={resolveBuildTarget,stageWorkflow,createNotices};
