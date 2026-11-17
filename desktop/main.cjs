'use strict';
const { app, BrowserWindow, dialog, ipcMain, session, shell, screen } = require('electron');
const fs = require('node:fs'); const path = require('node:path'); const { randomBytes } = require('node:crypto');
const { pathToFileURL } = require('node:url');
const { resolvePaths, windowBounds } = require('./paths.cjs');
const { isAllowedNavigation } = require('./security.cjs');
const { BackendHost } = require('./backend-host.cjs');
const { registerDesktopIpc } = require('./ipc.cjs');
const metadata = require('../package.json');
const paths = resolvePaths({ isPackaged:app.isPackaged,resourcesPath:process.resourcesPath,sourceRoot:path.resolve(__dirname,'..'),
  localAppData:process.env.LOCALAPPDATA || path.join(app.getPath('home'),'AppData','Local'),channel:metadata.desktopChannel });
app.setName(paths.productName); app.setAppUserModelId(paths.appId);
fs.mkdirSync(paths.userData,{recursive:true});fs.mkdirSync(paths.logsDir,{recursive:true});fs.mkdirSync(paths.sessionData,{recursive:true});
app.setPath('userData',paths.userData);app.setPath('sessionData',paths.sessionData);app.setPath('logs',paths.logsDir);
const logFile=path.join(paths.logsDir,'desktop.log');
function log(message) {
  try { if(fs.existsSync(logFile)&&fs.statSync(logFile).size>4*1024*1024)fs.renameSync(logFile,logFile+'.1');fs.appendFileSync(logFile,new Date().toISOString()+' '+String(message).slice(0,65536)+'\n'); } catch {}
}
let window=null,backend=null,origin=null,dirty=false,closing=false,allowQuit=false,starting=false;
const {streamSessionExport}=require('./session-export.cjs');
const statusUrl=pathToFileURL(path.join(__dirname,'status.html')).href;
if (!app.requestSingleInstanceLock()) { app.quit(); }
else {
 app.on('second-instance',()=>{if(window){if(window.isMinimized())window.restore();window.show();window.focus();}});
 app.whenReady().then(createWindow).catch(error=>{log(error.stack||error.message);dialog.showErrorBox('LiShuttle 无法启动',error.message+'\n日志：'+logFile);app.exit(1);});
 app.on('before-quit',event=>{if(!allowQuit){event.preventDefault();void requestClose();}});
 app.on('window-all-closed',()=>{if(allowQuit)app.quit();});
}
function info(){return {version:app.getVersion(),channel:paths.channel,dataDir:paths.dataDir,resourceRoot:paths.resourceRoot};}
registerDesktopIpc({ipcMain,dialog,shell,getWindow:()=>window,getOrigin:()=>origin,getInfo:info,exportSession:async(sid,target)=>{const active=backend;if(!active||!origin||active.exitResult)throw Error('本地服务不可用');await streamSessionExport({origin,cookieName:active.bootstrap.cookie_name,secret:active.bootstrap.session_secret,sid,target});},setDirty:value=>{dirty=value;}});
async function createWindow() {
 const isolated=session.fromPartition('lishuttle-'+randomBytes(16).toString('hex'),{cache:false});
 isolated.setPermissionRequestHandler((_contents,_permission,callback)=>callback(false));
 isolated.setPermissionCheckHandler(()=>false);
 isolated.webRequest.onBeforeRequest((details,callback)=>callback({cancel:details.url!==statusUrl&&!isAllowedNavigation(details.url,origin)}));
 window=new BrowserWindow({...windowBounds(screen.getPrimaryDisplay().workAreaSize),title:paths.productName,backgroundColor:'#f4f7fb',show:false,autoHideMenuBar:true,
  webPreferences:{preload:path.join(__dirname,'preload.cjs'),nodeIntegration:false,nodeIntegrationInWorker:false,contextIsolation:true,sandbox:true,webviewTag:false,webSecurity:true,allowRunningInsecureContent:false,session:isolated,devTools:!app.isPackaged}});
 window.setMenu(null);
 window.webContents.setWindowOpenHandler(()=>({action:'deny'}));
 window.webContents.on('will-attach-webview',event=>event.preventDefault());
 window.webContents.on('will-navigate',(event,url)=>{if(!isAllowedNavigation(url,origin))event.preventDefault();});
 window.webContents.on('will-redirect',(event,url)=>{if(!isAllowedNavigation(url,origin))event.preventDefault();});
 window.webContents.on('render-process-gone',(_event,details)=>{log('Renderer stopped: '+details.reason);if(!closing&&!allowQuit)void rendererFailure();});
 window.on('close',event=>{if(!allowQuit){event.preventDefault();void requestClose();}});
 await window.loadURL(statusUrl);window.show();await startBackend();
}
async function startBackend() {
 if(starting||allowQuit)return;starting=true;origin=null;dirty=false;
 try {
  for(const [name,file] of [['内置 Python',paths.python],['服务监管器',paths.supervisor],['工作台页面',path.join(paths.staticDir,'index.html')]])if(!fs.existsSync(file))throw new Error(name+'缺失：'+file);
  const secret=randomBytes(32).toString('hex'),cookieName='lishuttle_'+randomBytes(12).toString('hex');
  const next=new BackendHost({executable:paths.python,args:['-B',paths.supervisor],cwd:paths.resourceRoot,channel:paths.channel,
   bootstrap:{data_dir:paths.dataDir,static_dir:paths.staticDir,resource_root:paths.resourceRoot,session_secret:secret,cookie_name:cookieName},log});
  backend=next;next.on('exit',result=>{if(backend===next&&!result.expected&&!allowQuit&&!starting){origin=null;void serviceFailure(new Error('后台服务意外结束，退出码 '+result.code));}});
  origin=await next.start(); const activity=await next.activity(); log('Owned service processes supervisor='+next.child.pid+' service='+activity.pid);
  await window.webContents.session.clearStorageData({storages:['cookies']});
  await window.webContents.session.cookies.set({url:origin,name:cookieName,value:secret,httpOnly:true,secure:false,sameSite:'strict',path:'/'});
  await window.loadURL(origin+'/');log('Workspace ready; channel='+paths.channel+' version='+app.getVersion());
 } catch(error){log('Startup failed: '+error.message);await serviceFailure(error);}
 finally {starting=false;}
}
async function serviceFailure(error) {
 if(allowQuit||!window||window.isDestroyed())return;
 await window.loadURL(statusUrl).catch(()=>{});
 const result=await dialog.showMessageBox(window,{type:'error',title:'本地服务不可用',message:'工作台暂时无法连接后台服务',detail:error.message+'\n已阻止继续写入。查看日志后可重新连接；不会自动重跑任务。\n日志：'+logFile,buttons:['重新连接','打开日志目录','退出'],defaultId:0,cancelId:2,noLink:true});
 if(result.response===1){await shell.openPath(paths.logsDir);return serviceFailure(error);}
 if(result.response===2){await quitAfterBackend();return;}
 if(backend&&!backend.exitResult){backend.forceStop();await backend.waitForExit(5000).catch(()=>{});}
 // Schedule after the active startup attempt releases its guard.
 setTimeout(()=>{void startBackend();},50);
}
async function rendererFailure(){
 const answer=await dialog.showMessageBox(window,{type:'error',title:'工作台页面已停止',message:'页面发生异常，后台任务仍由本地服务管理。',detail:'重新加载页面会读取当前任务状态，不会重复开始任务。',buttons:['重新加载页面','返回'],defaultId:0,cancelId:1});
 if(answer.response===0&&origin)await window.loadURL(origin+'/');
}
async function requestClose(){
 if(closing||allowQuit)return;closing=true;
 try {
  if(dirty){
   const decision=await dialog.showMessageBox(window,{type:'warning',title:'有尚未保存的修改',message:'关闭前请保存或放弃当前草稿。',detail:'选择“返回保存”后，请在工作台完成保存，再关闭窗口。',buttons:['返回保存','放弃草稿并退出','取消'],defaultId:0,cancelId:2,noLink:true});
   if(decision.response!==1)return;
  }
  if(backend&&!backend.exitResult){
   let state;try{state=await backend.activity();}catch(error){
    log(error.message);const result=await dialog.showMessageBox(window,{type:'warning',title:'后台状态尚未确认',message:'暂时无法确认后台任务状态。',detail:'可返回等待；仅在确认需要中止时强制停止本应用的后台进程。',buttons:['返回等待','强制停止后退出'],defaultId:0,cancelId:0});
    if(result.response!==1)return;backend.forceStop();await backend.waitForExit(5000);allowQuit=true;window.destroy();app.quit();return;
   }
   if(state.busy){const decision=await dialog.showMessageBox(window,{type:'warning',title:'后台任务仍在进行',message:'退出将停止当前任务并等待归档完成。',detail:'可以返回继续工作，或最小化窗口保留运行。',buttons:['继续运行并返回','停止任务后退出'],defaultId:0,cancelId:0,noLink:true});if(decision.response!==1)return;}
  }
  await quitAfterBackend();
 }catch(error){log('Close blocked: '+error.message);await dialog.showMessageBox(window,{type:'error',title:'尚未完成退出',message:'后台任务尚未确认已安全停止。',detail:error.message+'\n请稍后重试，或查看日志目录：'+paths.logsDir,buttons:['返回工作台']});}
 finally{closing=false;}
}
async function quitAfterBackend(){
 if(backend&&!backend.exitResult)await backend.stop({timeout:30000});
 allowQuit=true;if(window&&!window.isDestroyed())window.destroy();app.quit();
}
process.on('uncaughtException',error=>{log('Main failure: '+(error.stack||error.message));dialog.showErrorBox('LiShuttle 发生异常','请查看日志：'+logFile+'\n'+error.message);});
process.on('exit',()=>{if(backend&&!backend.exitResult)backend.forceStop();});
