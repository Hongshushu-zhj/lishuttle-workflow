const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function fixture() {
  const nodes = new Map(), timers = new Map(), calls = [];
  let timerId = 0;
  const el = id => {
    if (!nodes.has(id)) nodes.set(id, {value:'',checked:false,disabled:false,innerHTML:'',textContent:'',style:{},dataset:{},
      className:'',classList:{add(){},remove(){},toggle(){},contains(){return false;}},
      setAttribute(){},removeAttribute(){},addEventListener(){},querySelectorAll(){return [];},
      insertAdjacentHTML(_,value){this.innerHTML += value;},scrollIntoView(){}});
    return nodes.get(id);
  };
  const ctx = vm.createContext({console,document:{getElementById:el,querySelector(){return null;},
    querySelectorAll(selector){return selector.includes('#params-area') ? [el('raw-input')] : [];}},
    setTimeout(){},setInterval(fn){const id=++timerId;timers.set(id,fn);return id;},clearInterval(id){timers.delete(id);}});
  vm.runInContext(require('./frontend_source.cjs')(),ctx);
  const run = source => vm.runInContext(source,ctx);
  run(`S.project='/fixture';S.projectEpoch=1;S.profileRevision='1';S.configTouched=new Set();
    S.projectConfig={PRESET:'release',BUILD_SUBDIR:'out/release',CMAKE:'cmake',NINJA:'ninja',VCVARS:'vcvars'};
    S.projectDraft={...S.projectConfig};S.buildWorkflow={built:false};
    invalidateSchemaPreview=()=>{};taskIdentityChanged=()=>{};renderProjectConfig=()=>refreshWorkflow();
    S.completed=0;refreshWorkflow();`);
  ctx.fetch = async (url,options={}) => {
    calls.push({url,body:options.body ? JSON.parse(options.body) : null});
    return {json:async()=>ctx.respond(url)};
  };
  ctx.respond = async url => url.includes('/output')
    ? {status:'done',exit:0,lines:['build complete'],total:1,next_since:1,has_more:false,label:'build',
      context:{operation:'build',project:'/fixture'},result:{verdict:'success'}}
    : url.includes('/runtime_state') ? {busy:false,phase:'idle'}
    : {build_workflow:{built:true},build_values:{PRESET:'release',BUILD_SUBDIR:'out/release'},profile_revision:'2'};
  const start = callback => {
    run(`applyRuntimeState({busy:true,sid:41,phase:'running',operation:'build',label:'build'});
      attachConsole(41,'当前编译',${callback || "async()=>{S.completed++;const status=await post('build_status',{});applyBuildStatus(status)}"});`);
  };
  return {ctx,run,el,timers,calls,start,poll:()=>timers.get(run('S.pollTimer'))()};
}

test('明确done后，旧运行状态刷新挂起也能解锁编译与输入',async()=>{
  const f=fixture();f.start();
  f.run('S.runtimeRefreshPending=true');
  assert.equal(f.el('btn-build').disabled,true);
  assert.equal(f.el('raw-input').disabled,true);
  await f.poll();
  assert.equal(f.run('S.pollTimer'),null);
  assert.equal(f.run('S.runtime.busy'),false);
  assert.equal(f.el('btn-build').disabled,false);
  assert.equal(f.el('raw-input').disabled,false);
  assert.equal(f.run('S.completed'),1);
});

test('历史列表连接挂起不阻断编译完成回调',async()=>{
  const f=fixture();f.start();
  f.run('S.historyInitialized=true;S.historyState={offset:0,limit:10,total:0,runs:[],request:0}');
  const respond=f.ctx.respond;let releaseHistory;
  f.ctx.respond=url=>url.includes('/history') ? new Promise(resolve=>releaseHistory=resolve) : respond(url);
  const pending=f.poll();
  try {
    await new Promise(setImmediate);
    assert.equal(f.run('S.completed'),1);
    assert.equal(f.run('S.pollTimer'),null);
    assert.equal(f.el('btn-build').disabled,false);
  } finally {
    releaseHistory?.({runs:[],total:0});
    await pending;
  }
});

test('运行状态连接挂起不阻断编译完成回调',async()=>{
  const f=fixture();f.start();
  const respond=f.ctx.respond;let releaseRuntime;
  f.ctx.respond=url=>url.includes('/runtime_state') ? new Promise(resolve=>releaseRuntime=resolve) : respond(url);
  const pending=f.poll();
  try {
    await new Promise(setImmediate);
    assert.equal(f.run('S.completed'),1);
    assert.equal(f.el('btn-build').disabled,false);
  } finally {
    releaseRuntime?.({busy:false});
    await pending;
  }
});

test('编译完成回调失败时解锁，提示刷新失败而非虚假日志重试',async()=>{
  const f=fixture();f.start('async()=>{throw Error("构建状态不可用")}');
  f.run('S.runtimeRefreshPending=true');
  await f.poll();
  assert.equal(f.run('S.runtime.busy'),false);
  assert.equal(f.el('btn-build').disabled,false);
  assert.match(f.el('run-connection').textContent,/后续状态刷新失败.*构建状态不可用/);
  assert.doesNotMatch(f.el('run-connection').textContent,/正在重试/);
});

test('分页未读完前保留补读，最后一页明确done后解锁',async()=>{
  const f=fixture();f.start();f.run('S.runtimeRefreshPending=true');
  const respond=f.ctx.respond;let page=0;
  f.ctx.respond=url=>url.includes('/output') ? {status:'done',exit:0,label:'build',total:2,
    next_since:++page,has_more:page===1,lines:[page===1?'first':'last'],
    context:{operation:'build',project:'/fixture'},result:{verdict:'success'}} : respond(url);
  await f.poll();
  assert.ok(f.run('S.pollTimer'));
  assert.equal(f.run('S.completed'),0);
  await f.poll();
  assert.equal(f.run('S.pollTimer'),null);
  assert.equal(f.run('S.runtime.busy'),false);
  assert.equal(f.run('S.completed'),1);
});

test('日志写着完成但后端仍running时持续等待',async()=>{
  const f=fixture();f.start();
  f.ctx.respond=async()=>({status:'running',exit:null,total:1,lines:['[100%] Build succeeded / 编译完成'],next_since:1,has_more:false});
  await f.poll();
  assert.ok(f.run('S.pollTimer'));
  assert.equal(f.run('S.runtime.busy'),true);
  assert.equal(f.run('S.completed'),0);
  assert.equal(f.el('btn-build').disabled,true);
});

test('旧会话done不能清除另一个活动任务的运行状态',async()=>{
  const f=fixture();f.start('async()=>{S.completed++}');
  f.run('applyRuntimeState({busy:true,sid:42,phase:"running",operation:"build"});S.runtimeRefreshPending=true');
  await f.poll();
  assert.equal(f.run('S.runtime.sid'),42);
  assert.equal(f.run('S.runtime.busy'),true);
  assert.equal(f.el('btn-build').disabled,true);
});

test('完成前发出的迟到busy响应不能把已解锁编译再次锁住',async()=>{
  const f=fixture();f.start('async()=>{S.completed++}');
  const respond=f.ctx.respond;let releaseRuntime;
  f.ctx.respond=url=>url.includes('/runtime_state') ? new Promise(resolve=>releaseRuntime=resolve) : respond(url);
  const oldRequest=f.run('refreshRuntimeState(true)');
  await f.poll();
  releaseRuntime({busy:true,sid:41,phase:'running',operation:'build'});
  await oldRequest;
  assert.equal(f.run('S.runtime.busy'),false);
  assert.equal(f.run('S.pollTimer'),null);
  assert.equal(f.el('btn-build').disabled,false);
});

test('完整编译入口在程序状态刷新失败后仍释放输入锁并允许重试',async()=>{
  const f=fixture(),respond=f.ctx.respond;
  f.ctx.respond=url=>url.endsWith('/toolkit') ? {sid:41,build_workflow:{built:false},
    build_values:{PRESET:'release',BUILD_SUBDIR:'out/release'},runtime:{busy:true,sid:41,phase:'running',operation:'build'}}
    : url.endsWith('/build_status') ? {error:'程序状态读取失败'} : respond(url);
  await f.run('toolkit("build")');
  assert.equal(f.run('S.inputTransition'),false);
  assert.equal(f.el('raw-input').disabled,true);
  await f.poll();
  assert.equal(f.run('S.runtime.busy'),false);
  assert.equal(f.run('S.pollTimer'),null);
  assert.equal(f.el('btn-build').disabled,false);
  assert.equal(f.el('raw-input').disabled,false);
  assert.match(f.el('hint').textContent,/程序状态读取失败/);
});

test('旧编译完成状态请求迟到时不能覆盖新活动会话',async()=>{
  const f=fixture(),respond=f.ctx.respond;let releaseBuild;
  f.ctx.respond=url=>url.endsWith('/toolkit') ? {sid:41,build_workflow:{built:false},
    build_values:{PRESET:'release',BUILD_SUBDIR:'out/release'},runtime:{busy:true,sid:41,phase:'running',operation:'build'}}
    : url.endsWith('/build_status') ? new Promise(resolve=>releaseBuild=resolve)
    : url.includes('/runtime_state') ? {busy:true,sid:42,phase:'running',operation:'build'} : respond(url);
  await f.run('toolkit("build")');
  const pending=f.poll();
  await new Promise(setImmediate);
  f.run('applyRuntimeState({busy:true,sid:42,phase:"running",operation:"build"});attachConsole(42,"下一次编译",async()=>{})');
  const currentTimer=f.run('S.pollTimer');
  releaseBuild({build_workflow:{built:true},profile_revision:'old-revision'});
  await pending;
  assert.equal(f.run('S.sid'),42);
  assert.equal(f.run('S.pollTimer'),currentTimer);
  assert.equal(f.run('S.buildWorkflow.built'),false);
  assert.equal(f.run('S.profileRevision'),'1');
});
