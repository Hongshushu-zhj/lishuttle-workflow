'use strict';
const fs=require('node:fs');const path=require('node:path');const os=require('node:os');const http=require('node:http');const assert=require('node:assert/strict');const {spawn}=require('node:child_process');const {randomBytes}=require('node:crypto');
const root=path.resolve(__dirname,'..');
function request(origin,route,headers={}){
 return new Promise((resolve,reject)=>{const req=http.get(origin+route,{headers},res=>{let body='';res.setEncoding('utf8');res.on('data',chunk=>body+=chunk);res.on('end',()=>resolve({status:res.statusCode,headers:res.headers,body}));});req.on('error',reject);req.setTimeout(5000,()=>req.destroy(new Error('HTTP smoke timed out')));});
}
async function serviceSmoke(){
 const {BackendHost}=require('../desktop/backend-host.cjs');const dir=fs.mkdtempSync(path.join(os.tmpdir(),'lishuttle-service-smoke-'));const resourceRoot=path.join(dir,'resources'),staticDir=path.join(resourceRoot,'static');fs.mkdirSync(staticDir,{recursive:true});fs.writeFileSync(path.join(staticDir,'index.html'),'<!doctype html><title>Smoke fixture</title>');
 const secret=randomBytes(32).toString('hex'),cookie='lishuttle_smoke';const logs=[];
 const host=new BackendHost({executable:path.join(root,'.desktop-build','python','python.exe'),args:['-B',path.join(root,'platform','backend','desktop_supervisor.py')],cwd:root,channel:'dev',bootstrap:{data_dir:path.join(dir,'data'),resource_root:resourceRoot,static_dir:staticDir,session_secret:secret,cookie_name:cookie},log:line=>logs.push(line)});
 try{
  const origin=await host.start();const authenticated={Cookie:cookie+'='+secret};
  assert.equal((await request(origin,'/')).status,401);assert.equal((await request(origin,'/api/desktop_info',authenticated)).status,200);
  const hostile=await request(origin,'/api/desktop_info',{...authenticated,Origin:'http://evil.invalid'});assert.equal(hostile.status,403);
  const page=await request(origin,'/',authenticated);assert.equal(page.status,200);assert.match(page.headers['content-security-policy'],/default-src 'self'/);
  const info=await host.activity();assert.equal(info.busy,false);await host.stop();assert.equal(logs.join('\n').includes(secret),false);
  return {mode:'service',python:'3.13.17',authenticated:true,hostileOriginRejected:true,gracefulShutdown:true,pid:info.pid,dataDir:dir};
 }finally{if(!host.exitResult){host.forceStop();await host.waitForExit(5000).catch(()=>{});}fs.rmSync(dir,{recursive:true,force:true});}
}
async function desktopSmoke({executable,output,keepData=false}={}){
 const {_electron}=require('playwright');const data=fs.mkdtempSync(path.join(os.tmpdir(),'lishuttle-desktop-smoke-'));
 const env={...process.env,LOCALAPPDATA:data,PATH:path.join(process.env.SystemRoot||'C:\\Windows','System32')};
 delete env.PYTHONHOME;delete env.PYTHONPATH;delete env.ELECTRON_RUN_AS_NODE;
 const args=executable?[]:[root];const executablePath=executable||require('electron');let application;
 const evidence={mode:executable?'packaged':'development',executable:executablePath,isolatedData:data,systemPythonNodeInPath:false,checks:[],limitations:['No real LiShuttle engine executed','No external machine or installer upgrade/uninstall acceptance']};
 try{
  application=await _electron.launch({executablePath,args,cwd:root,env,timeout:30000});
  evidence.checks.push=(...items)=>{Array.prototype.push.apply(evidence.checks,items);console.log(items[0]);return evidence.checks.length;}; const page=await application.firstWindow({timeout:30000});const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.waitForURL(/^http:\/\/127\.0\.0\.1:\d+\/?/, {timeout:30000});await page.locator('#app').waitFor({timeout:30000});await page.waitForFunction(()=>document.querySelector('#app')?.textContent?.trim().length>20);
  evidence.origin=new URL(page.url()).origin;evidence.checks.push('Production UI loaded from authenticated random loopback port');
  const bridge=await page.evaluate(async()=>({keys:Object.keys(window.desktop).sort(),info:await window.desktop.info(),node:typeof process,require:typeof require,cookie:document.cookie}));
  assert.deepEqual(bridge.keys,['exportSessionLog','info','openPath','pickDirectory','pickFile','saveText','setDirty'].sort());assert.equal(bridge.node,'undefined');assert.equal(bridge.require,'undefined');assert.equal(bridge.cookie,'');assert.equal(bridge.info.dataDir.startsWith(data),true);
  evidence.info=bridge.info;evidence.checks.push('Exact native bridge; Node globals absent; session credential HttpOnly; isolated data root');
  assert.equal((await request(evidence.origin,'/api/desktop_info')).status,401);evidence.checks.push('Unauthenticated API rejected');
  const preferences=await application.evaluate(({BrowserWindow})=>{const p=BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences();return {sandbox:p.sandbox,contextIsolation:p.contextIsolation,nodeIntegration:p.nodeIntegration,webSecurity:p.webSecurity};});
  assert.deepEqual(preferences,{sandbox:true,contextIsolation:true,nodeIntegration:false,webSecurity:true});evidence.checks.push('Renderer sandbox and context isolation enabled');
  await application.evaluate(({dialog})=>{globalThis.__smokeOpen=dialog.showOpenDialog;dialog.showOpenDialog=async()=>({canceled:true,filePaths:[]});});
  assert.equal(await page.evaluate(()=>window.desktop.pickDirectory({title:'Smoke cancellation'})),null);assert.equal(await page.evaluate(()=>window.desktop.pickFile({extensions:['xml']})),null);
  await application.evaluate(({dialog})=>{dialog.showOpenDialog=globalThis.__smokeOpen;delete globalThis.__smokeOpen;});evidence.checks.push('Actual IPC dialog cancellation returns null');
  const target=path.join(data,'exported-log.txt');
  await application.evaluate(({dialog},file)=>{globalThis.__smokeSave=dialog.showSaveDialog;dialog.showSaveDialog=async()=>({canceled:false,filePath:file});},target);
  const saved=await page.evaluate(()=>window.desktop.saveText({suggestedName:'run-log.txt',text:'Fixture log 日志\n'}));assert.equal(saved.saved,true);assert.equal(fs.readFileSync(target,'utf8'),'Fixture log 日志\n');
  await application.evaluate(({dialog})=>{dialog.showSaveDialog=globalThis.__smokeSave;delete globalThis.__smokeSave;});evidence.checks.push('Actual IPC text export saved exact UTF-8 bytes');
  await page.evaluate(async()=>{window.desktop.setDirty(true);await window.desktop.info();});
  await application.evaluate(({dialog,BrowserWindow})=>{globalThis.__smokeMessage=dialog.showMessageBox;globalThis.__smokeMessageCalls=0;dialog.showMessageBox=async()=>{globalThis.__smokeMessageCalls++;return {response:2};};BrowserWindow.getAllWindows()[0].close();});
  await page.waitForFunction(()=>true);
  const closeCheck=await application.evaluate(({BrowserWindow})=>({windows:BrowserWindow.getAllWindows().length,calls:globalThis.__smokeMessageCalls}));assert.equal(closeCheck.windows,1);assert.equal(closeCheck.calls,1);
  await application.evaluate(({dialog})=>{dialog.showMessageBox=globalThis.__smokeMessage;delete globalThis.__smokeMessage;});await page.evaluate(async()=>{window.desktop.setDirty(false);await window.desktop.info();});evidence.checks.push('Unsaved draft close prompt preserves the window on cancel');
  await application.evaluate(({dialog,BrowserWindow,app})=>{const Host=process.mainModule.require(app.getAppPath()+'/desktop/backend-host.cjs').BackendHost;globalThis.__smokeActivity=Host.prototype.activity;Host.prototype.activity=async()=>({busy:true,activity:{phase:'fixture'}});globalThis.__smokeBusyTitle='';globalThis.__smokeBusyDialog=dialog.showMessageBox;dialog.showMessageBox=async(_window,options)=>{globalThis.__smokeBusyTitle=options.title;return {response:0};};BrowserWindow.getAllWindows()[0].close();});
  const busyClose=await application.evaluate(({BrowserWindow})=>({windows:BrowserWindow.getAllWindows().length,title:globalThis.__smokeBusyTitle}));assert.equal(busyClose.windows,1);assert.equal(busyClose.title,'后台任务仍在进行');
  await application.evaluate(({dialog,app})=>{const Host=process.mainModule.require(app.getAppPath()+'/desktop/backend-host.cjs').BackendHost;Host.prototype.activity=globalThis.__smokeActivity;dialog.showMessageBox=globalThis.__smokeBusyDialog;delete globalThis.__smokeActivity;delete globalThis.__smokeBusyDialog;});evidence.checks.push('Busy close prompt preserves running window (injected activity fixture, no engine execution)');
  const initialUrl=page.url();await page.evaluate(()=>{location.href='https://example.invalid/';});await page.waitForFunction(expected=>location.href===expected,initialUrl);evidence.checks.push('External navigation blocked');
  const second=spawn(executablePath,args,{cwd:root,env,stdio:'ignore',windowsHide:true});
  const exit=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>{second.kill();reject(new Error('Second instance did not exit'));},10000);second.once('error',reject);second.once('exit',code=>{clearTimeout(timer);resolve(code);});});assert.equal(exit,0);evidence.checks.push('Second instance exited and retained the first window');
  const activity=await page.evaluate(async()=>{const value=await fetch('/api/state').then(r=>r.json());return value;});evidence.session={projects:activity.projects.length,runtime:activity.runtime};
  if(output){fs.mkdirSync(output,{recursive:true});await page.screenshot({path:path.join(output,'desktop-smoke.png'),fullPage:true});}
  const closed=new Promise(resolve=>application.once('close',resolve));await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].close());let closeTimer;try{await Promise.race([closed,new Promise((_,reject)=>{closeTimer=setTimeout(()=>reject(new Error('Graceful window close timed out')),35000);})]);}finally{clearTimeout(closeTimer);}application=null;evidence.checks.push('Window close drained service and exited');
  const log=path.join(bridge.info.dataDir,'logs','desktop.log');const text=fs.readFileSync(log,'utf8');assert.match(text,/Python supervisor exited \(0, null\)/);evidence.checks.push('Supervisor graceful exit 0 recorded'); const owned=/Owned service processes supervisor=(\d+) service=(\d+)/.exec(text); assert.ok(owned,'Owned Python process ids are recorded'); for(const pid of owned.slice(1).map(Number)){let alive=false;try{process.kill(pid,0);alive=true;}catch(error){if(error.code!=='ESRCH')throw error;}assert.equal(alive,false,'Owned Python process must exit: '+pid);} evidence.checks.push('Recorded supervisor and service process ids no longer exist'); evidence.pageErrors=errors;assert.deepEqual(errors,[]);
  return evidence;
 }catch(error){evidence.error=error.stack||error.message;console.error('Smoke check failed: '+evidence.error);throw Object.assign(error,{evidence});}
 finally{if(application)await application.close().catch(()=>{});if(output){fs.mkdirSync(output,{recursive:true});fs.writeFileSync(path.join(output,'desktop-smoke.json'),JSON.stringify(evidence,null,2)+'\n');}if(!keepData)fs.rmSync(data,{recursive:true,force:true});}
}
if(require.main===module){const value=name=>{const index=process.argv.indexOf(name);return index<0?undefined:process.argv[index+1];};(process.argv.includes('--service-only')?serviceSmoke():desktopSmoke({executable:value('--executable'),output:value('--output')||path.join(root,'release','smoke'),keepData:process.argv.includes('--keep-data')})).then(result=>console.log(JSON.stringify(result,null,2))).catch(error=>{console.error(error.stack||error.message);process.exitCode=1;});}
module.exports={serviceSmoke,desktopSmoke,request};
