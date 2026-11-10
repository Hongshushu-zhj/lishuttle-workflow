const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function fixture() {
  const nodes = new Map(), timers = new Map(), calls = [], downloads = [];
  let nextTimer = 1;
  const element = id => {
    if (!nodes.has(id)) nodes.set(id, {value:'', checked:false, textContent:'', innerHTML:'', className:'',
      disabled:false, dataset:{}, style:{}, classList:{add(){},remove(){},toggle(){}},
      querySelectorAll(){return [];}, insertAdjacentHTML(_, text){this.innerHTML += text;}});
    return nodes.get(id);
  };
  const state = {project:'fixture',projectEpoch:1,projectDraft:{},job:{name:'current',schema:'current.xml'},
    runtime:{busy:false},sid:0,since:0,pollTimer:null,resultSid:0};
  const context = vm.createContext({S:state,$:element,console,Blob,
    document:{querySelectorAll(){return [];},body:{appendChild(){}},createElement(){
      return {click(){downloads.push(this.download);},remove(){}};
    }},
    URL:{createObjectURL(blob){context.exported=blob;return 'blob:fixture';},revokeObjectURL(){}},
    setInterval(fn){const id=nextTimer++;timers.set(id,fn);return id;},clearInterval(id){timers.delete(id);},setTimeout(){},
    showOperation(){},toast(message){context.toastMessage=message;},esc(value){return String(value).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');},
    refreshSchemaApplyState(){},refreshCleanupState(){},refreshWorkflow(){},refreshCsvDirtyState(){},
    get:async (endpoint,query='')=>{calls.push({endpoint,query});return context.respond(endpoint,query);},
    post:async (endpoint,body)=>{calls.push({endpoint,body});return {};},
  });
  context.respond = async endpoint => endpoint === 'runtime_state' ? {busy:false,phase:'idle'} : {};
  vm.runInContext(fs.readFileSync('platform/frontend/runtime-session.js','utf8'),context);
  return {nodes,element,state,context,calls,downloads,timers,run:code=>vm.runInContext(code,context),
    poll:async()=>timers.get(state.pollTimer || state.historyPollTimer)()};
}

test('最近运行分页显示，切换项目后忽略迟到列表', async()=>{
  const f=fixture();
  f.context.respond=async()=>({runs:[{sid:9,label:'历史任务',created_at:1,status:'done',result:{verdict:'success'}}],total:23});
  await f.run('initRunHistory()');
  assert.match(f.element('run-history-list').innerHTML,/历史任务/);
  assert.match(f.element('run-history-list').innerHTML,/当时：成功/);
  assert.match(f.element('run-history-page').textContent,/1.*10.*23/);
  assert.equal(f.element('btn-history-prev').disabled,true);
  assert.equal(f.element('btn-history-next').disabled,false);
  let release;
  f.context.respond=()=>new Promise(resolve=>release=resolve);
  const pending=f.run('loadRunHistory(10)');
  f.state.projectEpoch++;f.state.project='new';
  release({runs:[{sid:10,label:'旧项目数据'}],total:30});
  await pending;
  assert.doesNotMatch(f.element('run-history-list').innerHTML,/旧项目数据/);
});

test('最近运行空列表与加载失败有明确提示',async()=>{
  const f=fixture();
  f.context.respond=async()=>({runs:[],total:0});
  await f.run('initRunHistory()');
  assert.match(f.element('run-history-list').textContent,/暂无/);
  f.context.respond=async()=>{throw Error('连接中断');};
  await f.run('loadRunHistory()');
  assert.match(f.element('run-history-status').textContent,/连接中断/);
});

test('未选择项目时不读取跨项目历史',async()=>{
  const f=fixture();f.state.project='';
  await f.run('initRunHistory()');
  assert.equal(f.calls.length,0);
  assert.match(f.element('run-history-status').textContent,/选择项目/);
});

test('选择历史仅绑定结果与日志，不改变当前装配；历史成功与当前变化分开显示',async()=>{
  const f=fixture(),job=f.state.job;
  f.context.respond=async endpoint=>endpoint === 'history'
    ? {runs:[{sid:8,label:'old',context:{func:'pred',task_name:'old'},result:{verdict:'success'}}],total:1}
    : {historical:true,historical_verdict:'success',associated:true,exists:true,dir:'out/old',files:[],log_tail:[],
      verdict:'success',current_files:{status:'changed',files:[]},archive:{dir:'history/8',status:'complete'}};
  await f.run('initRunHistory()');
  await f.run('selectHistoryRun(8)');
  assert.equal(f.state.job,job);
  assert.equal(f.state.resultSid,8);
  assert.equal(f.state.sid,8);
  assert.equal(f.element('result-job').value,'old');
  assert.match(f.element('result-status').textContent,/当时.*成功.*当前.*已变化/);
  assert.doesNotMatch(f.element('result-status').className,/\bok\b/);
  assert.match(f.element('result-validation').textContent,/当时验证结果：成功/);
  assert.match(f.element('result-validation').textContent,/当前文件.*已变化/);
  await f.run('openRunArchive()');
  assert.equal(f.calls.at(-1).endpoint,'open_folder');
  assert.equal(f.calls.at(-1).body.path,'history/8');
});

test('其他实例占用时不绑定本地会话控制台',()=>{
  const f=fixture();
  f.run('applyRuntimeState({busy:true,external:true,phase:"running",sid:5,label:"pred"},true)');
  assert.equal(f.state.sid,0);
  assert.equal(f.state.pollTimer,null);
  assert.match(f.element('runtime-status').textContent,/其他.*实例/);
});

test('完成会话按分页游标读完日志才结束，网络中断后从原游标重试',async()=>{
  const f=fixture();
  f.run('attachConsole(8,"历史会话 8：")');
  let page=0;
  f.context.respond=async endpoint=>{
    if(endpoint === 'runtime_state')return {busy:false};
    page++;
    if(page===1)throw Error('offline');
    return {status:'done',exit:0,total:4,next_since:page===2?2:4,has_more:page===2,
      lines:page===2?['first','second']:['third','last'],result:{verdict:'unconfirmed'}};
  };
  await f.poll();
  assert.equal(f.state.since,0);
  assert.match(f.element('run-connection').textContent,/重试/);
  await f.poll();
  assert.equal(f.state.since,2);
  assert.notEqual(f.state.pollTimer,null);
  await f.poll();
  assert.equal(f.state.since,4);
  assert.equal(f.state.pollTimer,null);
  assert.equal(f.calls.filter(c=>c.endpoint==='output')[2].query,'sid=8&since=2&limit=500');
  assert.match(f.element('run-console').innerHTML,/first[\s\S]*last/);
});

test('导出日志读取全部分页，并固定首次响应总行数',async()=>{
  const f=fixture();f.state.sid=6;
  f.context.respond=async (_,query)=>query.includes('since=0')
    ? {label:'pred',status:'running',exit:null,total:3,next_since:2,has_more:true,lines:['中文一','中文二']}
    : {label:'pred',status:'running',exit:null,total:4,next_since:4,has_more:false,lines:['中文三','导出开始后追加']};
  await f.run('exportRunLog()');
  const text=await f.context.exported.text();
  assert.match(text,/中文一\r\n中文二\r\n中文三/);
  assert.doesNotMatch(text,/导出开始后追加/);
  assert.match(text,/日志行数：3/);
  assert.equal(f.calls.length,2);
  assert.equal(f.downloads.length,1);
});

test('同会话重新读取时，旧请求不能重复追加日志或回退游标',async()=>{
  const f=fixture();let release;
  f.context.respond=()=>new Promise(resolve=>release=resolve);
  f.run('attachConsole(8,"第一次")');
  const pending=f.poll();
  f.run('attachConsole(8,"第二次")');
  release({status:'running',lines:['过期日志'],total:1,next_since:1,has_more:false});
  await pending;
  assert.equal(f.state.since,0);
  assert.doesNotMatch(f.element('run-console').innerHTML,/过期日志/);
});

test('历史工具记录按会话读取，不退回当前装配的任务目录',async()=>{
  const f=fixture();
  f.context.respond=async endpoint=>endpoint==='history'
    ? {runs:[{sid:17,label:'build',context:{operation:'build'}}],total:1}
    : {historical:true,historical_verdict:'success',associated:true,exists:false,files:[],log_tail:[],archive:{dir:'history/17'}};
  await f.run('initRunHistory()');
  await f.run('selectHistoryRun(17)');
  assert.equal(f.calls.find(c=>c.endpoint==='results').query,'sid=17');
  assert.equal(f.element('btn-open-archive').disabled,false);
});

test('读取另一会话失败时不保留前一条归档入口',async()=>{
  const f=fixture();f.state.resultSid=1;f.state.resultContext={task_name:'old'};
  f.element('result-job').value='old';
  f.context.respond=async()=>({associated:true,exists:true,files:[],log_tail:[],archive:{dir:'history/1'}});
  await f.run('loadResults()');
  assert.equal(f.element('btn-open-archive').disabled,false);
  f.context.respond=async()=>{throw Error('连接已断开');};
  f.state.resultSid=2;
  await f.run('loadResults()');
  assert.equal(f.element('btn-open-archive').disabled,true);
  assert.match(f.element('result-status').textContent,/读取失败/);
});

test('重启中断的历史会话结束轮询，并明确提示当前文件未确认',async()=>{
  const f=fixture();f.state.runVerdict='pending';
  f.run('attachConsole(3,"历史",null,{historical:true})');
  f.context.respond=async endpoint=>endpoint==='runtime_state'?{busy:false}:
    {status:'interrupted',exit:null,lines:[],total:0,next_since:0,has_more:false,result:{verdict:'unconfirmed'}};
  await f.poll();
  assert.equal(f.state.pollTimer,null);
  assert.match(f.element('run-status').textContent,/历史会话.*未确认/);
  assert.match(f.element('run-outcome').textContent,/当前文件.*未确认/);
  assert.equal(f.state.runVerdict,'pending');
});

test('停止操作只面向本实例活动任务，历史日志与外部实例只读',async()=>{
  const f=fixture();f.state.sid=8;f.state.consoleHistorical=true;
  await f.run('stopCurrentOperation()');
  assert.equal(f.calls.length,0);
  f.state.runtime={busy:true,external:true,sid:18};
  await f.run('stopCurrentOperation()');
  assert.equal(f.calls.length,0);
  f.state.runtime={busy:true,external:false,sid:19};
  await f.run('stopCurrentOperation()');
  assert.equal(f.calls.at(-1).endpoint,'stop');
  assert.equal(f.calls.at(-1).body.sid,19);
});

test('工作流将外部实例的取消按钮保持禁用',()=>{
  const f=fixture();
  const ctx=vm.createContext({document:{getElementById:f.element,querySelectorAll:()=>[]},setTimeout(){}});
  vm.runInContext(require('./frontend_source.cjs')(),ctx);
  vm.runInContext('S.projectConfig={};S.projectDraft={};S.runtime={busy:true,external:true,sid:44,phase:"running"};',ctx);
  assert.equal(vm.runInContext('workflowStatus().actions.cancel.disabled',ctx),true);
});

test('项目重置立即清除先前结论与归档入口',async()=>{
  const f=fixture();
  f.context.respond=async()=>({runs:[],total:0});
  await f.run('initRunHistory()');
  f.element('run-outcome').textContent='旧项目成功';
  f.element('result-validation').textContent='旧项目结论';
  f.element('btn-open-dir').disabled=false;
  await f.run('resetRunHistory()');
  assert.equal(f.element('run-outcome').textContent,'');
  assert.equal(f.element('result-validation').textContent,'');
  assert.equal(f.element('btn-open-dir').disabled,true);
});

test('中断会话日志导出不再描述为运行中',async()=>{
  const f=fixture();f.state.sid=3;
  f.context.respond=async()=>({status:'interrupted',exit:null,total:1,next_since:1,has_more:false,lines:['启动后服务退出']});
  await f.run('exportRunLog()');
  const text=await f.context.exported.text();
  assert.match(text,/状态：已中断/);
  assert.doesNotMatch(text,/状态：运行中/);
});

test('较晚返回的上一会话结果不覆盖当前选择',async()=>{
  const f=fixture();let release;
  f.state.resultSid=1;f.state.resultContext={task_name:'old'};f.element('result-job').value='old';
  f.context.respond=()=>new Promise(resolve=>release=resolve);
  const pending=f.run('loadResults()');
  f.state.resultSid=2;f.state.resultContext={task_name:'new'};f.element('result-job').value='new';
  f.context.respond=async()=>({associated:true,exists:true,files:[],log_tail:[],verdict:'failed',archive:{dir:'history/2'}});
  await f.run('loadResults()');
  release({associated:true,exists:true,files:[],log_tail:[],verdict:'success',archive:{dir:'history/1'}});
  await pending;
  assert.match(f.element('result-status').textContent,/会话 2.*失败/);
  await f.run('openRunArchive()');
  assert.equal(f.calls.at(-1).body.path,'history/2');
});

test('切换项目后迟到的运行状态不能恢复旧项目控制台',async()=>{
  const f=fixture();let release;
  f.context.respond=()=>new Promise(resolve=>release=resolve);
  const pending=f.run('refreshRuntimeState(true)');
  f.state.projectEpoch++;f.state.project='new';
  release({busy:true,phase:'running',sid:55});
  await pending;
  assert.equal(f.state.runtime.busy,false);
  assert.equal(f.state.sid,0);
});

test('活动运行时选择历史不覆盖当前日志与本次结论',async()=>{
  const f=fixture();
  f.context.respond=async endpoint=>endpoint==='history'
    ? {runs:[{sid:8,label:'history',context:{func:'pred',task_name:'history'}}],total:1}
    : endpoint==='runtime_state' ? {busy:false}
    : {status:'done',exit:0,lines:[],total:0,context:{func:'pred',task_name:'current'},result:{verdict:'success'}};
  await f.run('initRunHistory()');
  f.state.runtime={busy:true,sid:20,phase:'running'};f.state.resultSid=20;
  f.run('attachConsole(20,"当前运行")');
  const timer=f.state.pollTimer;
  await f.run('selectHistoryRun(8)');
  assert.equal(f.state.sid,20);
  assert.equal(f.state.resultSid,20);
  assert.equal(f.state.pollTimer,timer);
  assert.match(f.context.toastMessage,/当前.*结束/);
  await f.poll();
  assert.equal(f.state.runVerdict,'success');
});

test('编译轮询刚绑定时也禁止历史覆盖，并保留完成回调',async()=>{
  const f=fixture();
  f.context.respond=async endpoint=>endpoint==='history'
    ? {runs:[{sid:8,label:'history'}],total:1}
    : endpoint==='runtime_state' ? {busy:false}
    : {status:'done',exit:0,lines:[],total:0,context:{operation:'build'},result:{verdict:'success'}};
  await f.run('initRunHistory()');
  f.run('S.buildFinished=0;attachConsole(21,"当前编译",async()=>{S.buildFinished++})');
  const timer=f.state.pollTimer;
  await f.run('selectHistoryRun(8)');
  assert.equal(f.state.sid,21);
  assert.equal(f.state.pollTimer,timer);
  await f.poll();
  assert.equal(f.state.buildFinished,1);
});

test('历史日志断线重试不占当前运行锁，切项目会清理历史读取',async()=>{
  const f=fixture();
  f.context.respond=async()=>{throw Error('offline');};
  f.run('attachConsole(8,"历史",null,{historical:true})');
  await f.poll();
  assert.equal(f.state.pollTimer,null);
  assert.ok(f.state.historyPollTimer);
  assert.match(f.element('run-connection').textContent,/重试/);
  f.state.projectEpoch++;f.state.project='new';
  await f.run('resetRunHistory()');
  assert.equal(f.state.historyPollTimer,null);
  assert.equal(f.timers.size,0);
});

test('查看历史期间发现本实例新任务时恢复活动任务跟踪',()=>{
  const f=fixture();
  f.run('attachConsole(8,"历史",null,{historical:true})');
  const historyTimer=f.state.historyPollTimer;
  f.run('applyRuntimeState({busy:true,sid:22,phase:"running",label:"build"},true)');
  assert.equal(f.state.sid,22);
  assert.ok(f.state.pollTimer);
  assert.equal(f.state.historyPollTimer,null);
  assert.equal(f.timers.has(historyTimer),false);
  assert.equal(f.state.consoleHistorical,false);
});

test('历史中恰好选中本实例活动会话时也恢复活动跟踪',()=>{
  const f=fixture();
  f.run('attachConsole(22,"历史",null,{historical:true})');
  f.run('applyRuntimeState({busy:true,sid:22,phase:"running",label:"pred"},true)');
  assert.ok(f.state.pollTimer);
  assert.equal(f.state.historyPollTimer,null);
  assert.equal(f.state.consoleHistorical,false);
});
