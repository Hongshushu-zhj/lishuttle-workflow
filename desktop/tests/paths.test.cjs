'use strict';
const test=require('node:test'); const assert=require('node:assert/strict'); const path=require('node:path');
let subject={};try{subject=require('../paths.cjs');}catch(e){if(e.code!=='MODULE_NOT_FOUND')throw e;}
test('stable and dev writable paths and application identifiers are isolated',()=>{
 assert.equal(typeof subject.resolvePaths,'function');
 const base={isPackaged:true,resourcesPath:'C:\\Installed\\resources',sourceRoot:'D:\\Source',localAppData:'C:\\User\\Local',version:'0.1.0'};
 const stable=subject.resolvePaths({...base,channel:'stable'}),dev=subject.resolvePaths({...base,channel:'dev'});
 assert.equal(stable.dataDir,path.join(base.localAppData,'LiShuttleWorkflow'));assert.equal(dev.dataDir,path.join(base.localAppData,'LiShuttleWorkflow-Dev'));
 assert.notEqual(stable.appId,dev.appId);assert.notEqual(stable.userData,dev.userData);
 assert.equal(stable.resourceRoot,path.join(base.resourcesPath,'workflow'));assert.equal(stable.python,path.join(base.resourcesPath,'python','python.exe'));
 assert.equal(stable.staticDir,path.join(stable.resourceRoot,'desktop-ui','dist'));
 assert.throws(()=>subject.resolvePaths({...base,channel:'../bad'}),/channel/);
});
test('development launches same built UI and bundled runtime without PATH dependency',()=>{
 assert.equal(typeof subject.resolvePaths,'function');
 const result=subject.resolvePaths({isPackaged:false,sourceRoot:'D:\\Source',resourcesPath:'unused',localAppData:'C:\\Local',channel:'dev'});
 assert.equal(result.python,path.join('D:\\Source','.desktop-build','python','python.exe'));assert.equal(result.staticDir,path.join('D:\\Source','desktop-ui','dist'));
 assert.equal(result.supervisor,path.join('D:\\Source','platform','backend','desktop_supervisor.py'));
});
test('window sizes never exceed available work area',()=>{
 assert.equal(typeof subject.windowBounds,'function');
 assert.deepEqual(subject.windowBounds({width:1280,height:680}),{width:1280,height:680,minWidth:1100,minHeight:680});
 assert.deepEqual(subject.windowBounds({width:1920,height:1040}),{width:1440,height:900,minWidth:1100,minHeight:700});
});
