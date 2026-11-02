const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const nodes = new Map(), timers = new Map();
let nextTimer = 1;
const element = id => {
  if (!nodes.has(id)) nodes.set(id, {value:'', checked:false, textContent:'', innerHTML:'', className:'', style:{},
    disabled:false, dataset:{}, classList:{add(){},remove(){},toggle(){}},
    querySelectorAll(){return [];}, insertAdjacentHTML(_, text){this.innerHTML += text;}});
  return nodes.get(id);
};
const protectedIds = ['btn-run', 'btn-build', 'btn-render', 'btn-csv-save'];
const context = vm.createContext({
  document:{getElementById:element, querySelector(){return {dataset:{tab:'run'},classList:{add(){}}};},
    querySelectorAll(selector){return selector === '[data-runtime-write]' ? protectedIds.map(element) : [];}},
  setTimeout(){}, setInterval(fn){const id=nextTimer++; timers.set(id,fn); return id;},
  clearInterval(id){timers.delete(id);}, console,
});
vm.runInContext(fs.readFileSync('platform/frontend/app.js','utf8').replace(/init\(\);\s*$/, ''), context);
const run = code => vm.runInContext(code, context);

(async () => {
  assert.equal(run('typeof applyRuntimeState'), 'function', '运行状态必须由后端状态恢复');
  run('applyRuntimeState({busy:true,phase:"running",sid:29,label:"pred"}, true)');
  assert.equal(run('S.sid'), 29);
  protectedIds.forEach(id=>assert.equal(element(id).disabled, true));
  run('applyRuntimeState({busy:false,phase:"idle"})');
  protectedIds.forEach(id=>assert.equal(element(id).disabled, false));
  run('clearInterval(S.pollTimer); S.pollTimer=null; S.sid=0; S.resultSid=0; S.project="fixture"; S.projectEpoch=1; '
    + 'S.job={name:"task",schema:"task.xml",func:"pred",taskId:"1"}');
  element('job-name').value='task'; element('task-id').value='1';
  let releaseCheck, runCalls=0;
  const waitCheck = new Promise(resolve=>releaseCheck=resolve);
  context.fetch = async url => {
    if (url.endsWith('/preflight')) {await waitCheck; return {json:async()=>({ok:true,issues:[],context:{}})};}
    if (url.endsWith('/run')) {runCalls++; return {json:async()=>({sid:31,context:{func:'pred',task_name:'task'}})};}
    throw Error('unexpected '+url);
  };
  const first = run('doRun()');
  await run('doRun()');
  releaseCheck(); await first;
  assert.equal(runCalls, 1, '预检查过程中连点也只能发起一次运行');
  context.fetch = async url => ({json:async()=>url.includes('/output') ? {
    status:'done',exit:0,total:0,lines:[],label:'pred',context:{func:'pred',task_name:'task'},
    result:{verdict:'unconfirmed',process:{status:'done',exit:0},artifacts:{status:'unconfirmed'},
      business:{status:'unconfirmed'},issues:[{message:'旧产物无法确认本次归属',path:'RSRP.dem'}]}
  } : {busy:false,phase:'idle'}});
  await timers.get(run('S.pollTimer'))();
  assert.ok(!element('run-status').className.includes(' ok'), '退出 0、产物未确认不得显示绿色成功');
  assert.match(element('run-outcome').textContent, /退出码.*0/);
  assert.match(element('run-outcome').textContent, /产物/);
  assert.match(element('run-outcome').textContent, /业务/);
  run('showOutcome("run-outcome", {process:{status:"exited",exit_code:7}})');
  assert.match(element('run-outcome').textContent, /退出码 7/);
  assert.ok(!element('run-outcome').textContent.includes('正常退出'), '非零退出不能描述为正常退出');
  run('showOutcome("run-outcome", {business:{status:"partial",total:2,succeeded:2,updated:0,' +
    'counts:{processed:3,updated:1,failed:1,skipped:1},model_kinds:{' +
    'general:{status:"success",processed:1,updated:1},' +
    'cells:{status:"no_update",processed:1,skipped:1,unit:"site_groups",reason:"update=N"},' +
    'scenes:{status:"failed",processed:1,failed:1,reason:"保存失败",' +
    'items:[{id:"scene-7",status:"failed",reason:"样本不足"}]}}}})');
  assert.match(element('run-outcome').textContent, /校正站点：2/);
  assert.match(element('run-outcome').textContent, /通用模型：成功/);
  assert.match(element('run-outcome').textContent, /站点模型：无模型更新/);
  assert.match(element('run-outcome').textContent, /场景模型：失败/);
  assert.match(element('run-outcome').textContent, /保存失败/);
  assert.match(element('run-outcome').textContent, /单位：站点组/);
  assert.match(element('run-outcome').textContent, /scene-7：失败；样本不足/);

  let requested;
  element('result-job').value='task';
  context.fetch = async url => {
    requested=url;
    return {json:async()=>({associated:true,exists:true,dir:'fixture/out/task',files:[],log_tail:[],
      verdict:'failed',process:{exit:0,status:'done'},artifacts:{status:'failed'},business:{status:'unusable'},
      issues:[{message:'缺少指标文件',path:'10m/SCR.dem'}]})};
  };
  await run('loadResults()');
  assert.match(requested, /sid=31/);
  assert.match(element('result-validation').textContent, /10m\/SCR.dem/);
  assert.ok(!element('result-status').className.includes(' ok'));
  element('result-directory-only').checked=true;
  context.fetch = async url => {
    requested=url;
    return {json:async()=>({associated:false,exists:true,files:[],log_tail:[],status:'end',verdict:'unconfirmed'})};
  };
  await run('loadResults()');
  assert.match(requested, /job=task/);
  assert.match(element('result-status').textContent, /未关联/);
  assert.ok(!element('result-status').className.includes(' ok'));
  run('attachConsole(31, "restore"); S.resultSid=31;');
  context.fetch = async () => ({json:async()=>({error:'会话不存在',code:'SESSION_NOT_FOUND'})});
  await timers.get(run('S.pollTimer'))();
  assert.equal(run('S.pollTimer'), null, '服务重启导致会话消失后不能保留本地运行锁');
  assert.equal(run('S.sid'), 0);
  assert.equal(run('S.resultSid'), 0, '消失会话结果只能按未关联目录浏览');
  context.fetch = async url => ({json:async()=>url.endsWith('/preflight') ? {ok:true,issues:[]}
    : {sid:32,context:{func:'pred',task_name:'task'}}});
  await run('doRun()');
  assert.equal(run('S.sid'), 32, '释放本地锁后允许再次启动');
  run('clearInterval(S.pollTimer); S.pollTimer=null; S.sid=0; S.project="fixture"; S.projectEpoch=10; '
    + 'S.restoredBuildStatus=null; applyBuildStatus=status=>{S.restoredBuildStatus=status};');
  const buildRequests = [];
  context.fetch = async url => {
    buildRequests.push(url);
    return {json:async()=>url.includes('/output') ? {
      status:'done',exit:0,total:0,lines:[],label:'build',context:{operation:'build',project:'fixture'},
      result:{verdict:'success',process:{status:'done',exit:0}}
    } : url.endsWith('/build_status') ? {build_workflow:{built:true},profile_revision:'new-revision'}
      : {busy:false,phase:'idle'}};
  };
  run('applyRuntimeState({busy:true,phase:"running",sid:42,label:"编译"},true)');
  await timers.get(run('S.pollTimer'))();
  assert.ok(buildRequests.some(url=>url.endsWith('/build_status')), '恢复的编译会话结束后也应刷新构建状态');
  assert.equal(run('S.restoredBuildStatus.build_workflow.built'), true);
  console.log('PASS: restores runtime ownership, rejects duplicate launches, separates exit/artifacts/business, binds results by session');
})().catch(error=>{console.error(error);process.exitCode=1;});
