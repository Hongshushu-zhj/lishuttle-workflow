const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

// Reuse the full-app fixture without executing its registered tests.
const helperSource = fs.readFileSync('tests/test_build_release_ui.cjs', 'utf8').split('\ntest(')[0];
const helpers = vm.createContext({require, console});
vm.runInContext(helperSource + '\nglobalThis.buildFixture = fixture;', helpers);

test('完成后的程序状态刷新挂起时，仍能再次提交编译', async () => {
  const f = helpers.buildFixture(), original = f.ctx.respond;
  let releaseBuild, submissions = 0;
  f.ctx.respond = url => url.endsWith('/toolkit')
    ? {sid:41 + submissions++, build_workflow:{built:false},
       build_values:{PRESET:'release',BUILD_SUBDIR:'out/release'},
       runtime:{busy:true,sid:40 + submissions,phase:'running',operation:'build'}}
    : url.endsWith('/build_status') ? new Promise(resolve => { releaseBuild = resolve; })
    : original(url);
  await f.run('toolkit("build")');
  const completion = f.poll();
  try {
    await new Promise(setImmediate);
    assert.equal(f.run('S.runtime.busy'), false);
    assert.equal(f.run('S.pollTimer'), null);
    assert.equal(f.el('btn-build').disabled, false);
    await f.run('toolkit("build")');
    assert.equal(submissions, 2, '完成后刷新不能以 pendingRequests 阻止新的编译请求');
  } finally {
    releaseBuild?.({build_workflow:{built:true}, build_values:{}, profile_revision:'2'});
    await completion;
  }
});

test('完成后的程序状态刷新挂起时，仍能提交下一次真实运行请求', async () => {
  const f=helpers.buildFixture(),original=f.ctx.respond;
  let releaseBuild,runs=0;
  f.ctx.respond=url=>url.endsWith('/toolkit') ? {sid:41,build_workflow:{built:false},
    build_values:{PRESET:'release',BUILD_SUBDIR:'out/release'},runtime:{busy:true,sid:41,phase:'running',operation:'build'}}
    : url.endsWith('/build_status') ? new Promise(resolve=>releaseBuild=resolve)
    : url.endsWith('/preflight') ? {ok:true,issues:[]}
    : url.endsWith('/run') ? (runs++,{sid:81,context:{func:'pred',task_name:'current'},runtime:{busy:true,sid:81,phase:'running'}})
    : original(url);
  await f.run('toolkit("build")');
  const completion=f.poll();
  try {
    await new Promise(setImmediate);
    f.run(`S.buildWorkflow={built:true};S.city={name:'map'};S.task={name:'task',engineering_file:'fixture.csv'};
      S.func='pred';$('job-name').value='current';$('task-id').value='1';
      S.job={name:'current',schema:'current.xml',func:'pred',taskId:'1'};markWorkflowAssembled(S.job);`);
    assert.equal(f.run('S.pendingRequests'),0);
    await f.run('doRun()');
    assert.equal(runs,1);
    assert.equal(f.run('S.sid'),81);
  } finally {
    releaseBuild?.({build_workflow:{built:true},profile_revision:'old-build'});
    await completion;
  }
});

test('仅程序状态查询免写锁，普通保存仍阻止后续编译',async()=>{
  const f=helpers.buildFixture();let release;
  f.ctx.respond=()=>new Promise(resolve=>release=resolve);
  const pending=f.run('post("save_project_config",{values:{}})');
  try {
    assert.equal(f.run('S.pendingRequests'),1);
    await f.run('toolkit("build")');
    assert.equal(f.calls.filter(call=>call.url.endsWith('/toolkit')).length,0);
  } finally {
    release({ok:true});await pending;
  }
  assert.equal(f.run('S.pendingRequests'),0);
});

test('同sid改看历史后，旧编译状态刷新不能清空新装配',async()=>{
  const f=helpers.buildFixture(),original=f.ctx.respond;let releaseBuild;
  f.ctx.respond=url=>url.endsWith('/toolkit') ? {sid:41,build_workflow:{built:false},
    build_values:{PRESET:'release',BUILD_SUBDIR:'out/release'},runtime:{busy:true,sid:41,phase:'running',operation:'build'}}
    : url.endsWith('/build_status') ? new Promise(resolve=>releaseBuild=resolve)
    : url.includes('/results') ? {historical:true,associated:true,exists:true,files:[],log_tail:[],verdict:'success'}
    : original(url);
  await f.run('toolkit("build")');
  const completion=f.poll();
  await new Promise(setImmediate);
  f.run(`S.job={name:'new-assembly',schema:'new.xml'};S.historyState={runs:[{sid:41,label:'build',context:{operation:'build'}}]};`);
  await f.run('selectHistoryRun(41)');
  assert.equal(f.run('S.consoleHistorical'),true);
  releaseBuild({build_workflow:{built:true},profile_revision:'old-build'});
  await completion;
  assert.equal(f.run('S.job?.schema'),'new.xml');
  assert.notEqual(f.run('S.profileRevision'),'old-build');
});

test('程序状态查询失败只提示刷新问题，保留原编译成功结论',async()=>{
  const f=helpers.buildFixture(),original=f.ctx.respond;
  f.ctx.respond=url=>url.endsWith('/toolkit') ? {sid:41,build_workflow:{built:false},
    build_values:{PRESET:'release',BUILD_SUBDIR:'out/release'},runtime:{busy:true,sid:41,phase:'running',operation:'build'}}
    : url.endsWith('/build_status') ? Promise.reject(Error('状态连接不可用')) : original(url);
  await f.run('toolkit("build")');
  await f.poll();
  assert.equal(f.run('S.pendingRequests'),0);
  assert.match(f.el('run-status').textContent,/成功/);
  assert.match(f.el('run-status').className,/\bok\b/);
  assert.match(f.el('run-connection').textContent,/后续状态刷新失败/);
  assert.equal(f.run('S.runtime.busy'),false);
});
