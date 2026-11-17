'use strict';
const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');
const requireMain=require('node:module').createRequire(path.resolve(__dirname,'../main.cjs'));

function closeFixture(response,alreadyStopping=false){
 const events=[],dialogs=[];let attempts=0;
 const backend={stopping:alreadyStopping,exitResult:null,activity:async()=>{assert.equal(backend.stopping,false,'closing backend no longer serves activity requests');return {busy:false};},
  stop:async()=>{events.push('stop');backend.stopping=true;if(++attempts===1&&!alreadyStopping)throw Error('Service shutdown request timed out');backend.exitResult={code:0};},
  forceStop:()=>{events.push('force');backend.stopping=true;},
  waitForExit:async()=>{events.push('wait');backend.exitResult={code:0};}};
 const window={destroy:()=>events.push('destroy'),isDestroyed:()=>false};
 const electron={app:{getPath:()=>__dirname,setName:()=>{},setAppUserModelId:()=>{},setPath:()=>{},requestSingleInstanceLock:()=>false,quit:()=>events.push('quit')},
  dialog:{showMessageBox:async(_window,options)=>{dialogs.push(options);return {response};}},ipcMain:{},session:{},shell:{},screen:{}};
 const context=vm.createContext({fixture:{backend,window},__dirname:path.resolve(__dirname,'..'),setTimeout,process:{env:{},on:()=>{}},
  require:id=>id==='electron'?electron:id==='node:fs'?{mkdirSync:()=>{},existsSync:()=>false,appendFileSync:()=>{}}:
   id==='./paths.cjs'?{resolvePaths:()=>({productName:'fixture',appId:'fixture',userData:__dirname,logsDir:__dirname,sessionData:__dirname}),windowBounds:()=>({})}:
   id==='./ipc.cjs'?{registerDesktopIpc:()=>{}}:id==='./backend-host.cjs'?{BackendHost:class{}}:
   id==='./session-export.cjs'?{streamSessionExport:()=>{}}:requireMain(id)});
 const source=fs.readFileSync(path.resolve(__dirname,'../main.cjs'),'utf8');
 vm.runInContext(source+'\nbackend=fixture.backend;window=fixture.window;dirty=backend.stopping;globalThis.close=requestClose;',context);
 events.length=0;
 return {events,dialogs,close:()=>context.close()};
}

test('a shutdown timeout keeps closing and can wait until the backend exits',async()=>{
 const fixture=closeFixture(0);await fixture.close();
 assert.deepEqual(fixture.events,['stop','stop','destroy','quit']);
 assert.deepEqual(Array.from(fixture.dialogs[0].buttons),['继续等待','强制停止后退出']);
 assert.doesNotMatch(fixture.dialogs.flatMap(dialog=>Array.from(dialog.buttons)).join(' '),/返回工作台/);
});

test('a shutdown timeout offers an explicit force stop and confirms owned process exit',async()=>{
 const fixture=closeFixture(1);await fixture.close();
 assert.deepEqual(fixture.events,['stop','force','wait','destroy','quit']);
 assert.match(fixture.dialogs[0].detail,/未完成|丢失|恢复|核对/);
 assert.doesNotMatch(fixture.dialogs.flatMap(dialog=>Array.from(dialog.buttons)).join(' '),/返回工作台/);
});

test('an already closing backend resumes its exit wait without activity or draft prompts',async()=>{
 const fixture=closeFixture(0,true);await fixture.close();
 assert.deepEqual(fixture.events,['stop','destroy','quit']);assert.equal(fixture.dialogs.length,0);
});
