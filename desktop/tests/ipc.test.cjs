'use strict';
const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const os=require('node:os');const path=require('node:path');
let register;try{register=require('../ipc.cjs').registerDesktopIpc;}catch(e){if(e.code!=='MODULE_NOT_FOUND')throw e;}
test('native IPC rejects child frames and invalid data before touching operating system',async()=>{
 assert.equal(typeof register,'function');const handlers=new Map();let calls=0;const frame={url:'http://127.0.0.1:49152/'};const webContents={mainFrame:frame};const window={webContents,isDestroyed:()=>false};
 register({ipcMain:{handle:(key,fn)=>handlers.set(key,fn),on:(key,fn)=>handlers.set(key,fn)},dialog:{showOpenDialog:async()=>{calls++;return {canceled:true,filePaths:[]};}},shell:{},getWindow:()=>window,getOrigin:()=>'http://127.0.0.1:49152',getInfo:()=>({version:'0.1.0'}),setDirty:()=>{}});
 const event={sender:webContents,senderFrame:frame};assert.equal(await handlers.get('desktop:pickDirectory')(event,{title:'Choose'}),null);assert.equal(calls,1);
 await assert.rejects(handlers.get('desktop:pickDirectory')({...event,senderFrame:{...frame}},{}),/trusted/i);assert.equal(calls,1);
 await assert.rejects(handlers.get('desktop:pickFile')(event,{extensions:['../bad']}));assert.equal(calls,1);
});
test('saveText writes only to native save dialog result and respects cancel',async t=>{
 assert.equal(typeof register,'function');const directory=fs.mkdtempSync(path.join(os.tmpdir(),'lishuttle-ipc-'));t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
 const output=path.join(directory,'saved.txt');let canceled=true;const handlers=new Map();const frame={url:'http://127.0.0.1:49152/'};const webContents={mainFrame:frame};const event={sender:webContents,senderFrame:frame};
 register({ipcMain:{handle:(key,fn)=>handlers.set(key,fn),on:()=>{}},dialog:{showSaveDialog:async()=>({canceled,filePath:output})},shell:{},getWindow:()=>({webContents,isDestroyed:()=>false}),getOrigin:()=>'http://127.0.0.1:49152',getInfo:()=>({}),setDirty:()=>{}});
 assert.deepEqual(await handlers.get('desktop:saveText')(event,{suggestedName:'log.txt',text:'你好'}),{saved:false});assert.equal(fs.existsSync(output),false);
 canceled=false;assert.deepEqual(await handlers.get('desktop:saveText')(event,{suggestedName:'log.txt',text:'你好'}),{saved:true,path:output});assert.equal(fs.readFileSync(output,'utf8'),'你好');
});

test('session export accepts only sid, uses native target, and never accepts renderer credentials or paths',async()=>{
 const handlers=new Map();let dialogs=0;const calls=[];const frame={url:'http://127.0.0.1:49152/'};const webContents={mainFrame:frame};const event={sender:webContents,senderFrame:frame};
 const target=path.join(os.tmpdir(),'native-session.log');let canceled=true;
 register({ipcMain:{handle:(key,fn)=>handlers.set(key,fn),on:()=>{}},dialog:{showSaveDialog:async()=>{dialogs++;return {canceled,filePath:target};}},shell:{},getWindow:()=>({webContents,isDestroyed:()=>false}),getOrigin:()=>'http://127.0.0.1:49152',getInfo:()=>({}),setDirty:()=>{},exportSession:async(...args)=>calls.push(args)});
 const save=handlers.get('desktop:exportSessionLog');
 for(const value of [{sid:'../secret'},{sid:1,path:target},{sid:1,url:'http://evil.invalid'},{sid:1,secret:'x'},{sid:NaN},{sid:0}])await assert.rejects(save(event,value));
 assert.equal(dialogs,0);assert.deepEqual(await save(event,{sid:7}),{saved:false});assert.deepEqual(calls,[]);
 canceled=false;assert.deepEqual(await save(event,{sid:7}),{saved:true,path:target});assert.deepEqual(calls,[[7,target]]);
 await assert.rejects(save({...event,senderFrame:{...frame}},{sid:7}),/trusted/i);
});
