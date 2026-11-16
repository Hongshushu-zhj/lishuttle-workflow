'use strict';
const test=require('node:test');const assert=require('node:assert/strict');const path=require('node:path');
let BackendHost;try{({BackendHost}=require('../backend-host.cjs'));}catch(e){if(e.code!=='MODULE_NOT_FOUND')throw e;}
function create(mode){assert.equal(typeof BackendHost,'function');return new BackendHost({executable:process.execPath,args:[path.join(__dirname,'fixtures','fake-service.cjs'),...(mode?[mode]:[])],cwd:__dirname,bootstrap:{data_dir:__dirname,static_dir:__dirname,resource_root:__dirname,session_secret:'never-in-command-or-logs',cookie_name:'lishuttle_test'},startupTimeout:1000,requestTimeout:1000});}
test('starts actual child with credentials exclusively on stdin and correlates activity',async t=>{
 const host=create();t.after(()=>host.forceStop());const origin=await host.start();assert.equal(origin,'http://127.0.0.1:49222');assert.equal(host.child.spawnargs.join(' ').includes('never-in-command-or-logs'),false);
 const activity=await host.activity();assert.equal(activity.busy,false);assert.equal(activity.pid,host.child.pid);
 await host.stop({timeout:1000});assert.equal(host.child.exitCode,0);
});
test('rejects hostile ready origin and stops its owned child',async t=>{const host=create('bad-origin');t.after(()=>host.forceStop());await assert.rejects(host.start(),/origin/i);});
test('reports service startup crash without hanging',async t=>{const host=create('crash');t.after(()=>host.forceStop());await assert.rejects(host.start(),/19|exited/i);});
test('EOF stops only owned child when host is force closed',async()=>{const host=create();await host.start();host.child.stdin.end();await host.waitForExit(1000);assert.equal(host.child.exitCode,0);});
