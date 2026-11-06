const vm = require('node:vm'), assert = require('node:assert/strict');
const nodes = new Map();
function el(id) {
  if (!nodes.has(id)) { const classes = new Set(); nodes.set(id, {value:'', checked:false, disabled:false,
    textContent:'', innerHTML:'', style:{}, dataset:{}, open:false,
    classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x),toggle(x,on){if(on)classes.add(x);else classes.delete(x);}},
    querySelectorAll:()=>[], setAttribute(){},removeAttribute(){},scrollIntoView(){},focus(){this.focused=true;}}); }
  return nodes.get(id);
}
const ctx = vm.createContext({document:{getElementById:el,querySelectorAll:()=>[],querySelector:()=>null},setTimeout(){}});
vm.runInContext(require('./frontend_source.cjs')(),ctx);
const run = code=>vm.runInContext(code,ctx);
run(`S.project='project'; S.projectEpoch=1; S.profileId='fixture'; S.projectConfig={PRESET:'release',BUILD_SUBDIR:'out/release',EXE_NAME:'engine.exe'};
  S.projectDraft={...S.projectConfig}; S.buildWorkflow={built:true}; S.city={name:'map',kind:'outdoor'};
  S.task={name:'task',engineering_file:'a.csv'}; S.func='pred';
  $('job-name').value='job'; $('task-id').value='1';
  S.job={name:'job',schema:'job.xml',taskId:'1',func:'pred'};
  syncWorkflow(); markWorkflowAssembled(S.job);`);
(async()=>{
  assert.equal(run('taskIdentityDirty()'),false);
  run('S.func="commsensing"; refreshWorkflow()');
  assert.equal(run('taskIdentityDirty()'),true,'function changes must stale assembly');
  let requests=0;
  ctx.fetch=async()=>{requests++;return {json:async()=>({ok:true})}};
  await run('doRun()'); assert.equal(requests,0,'old function must never launch');
  run('markWorkflowAssembled(S.job); markWorkflowPreflight({ok:true}); workflowContentChanged("XML 已保存")');
  assert.equal(run('workflowStatus().assemblyCurrent'),true);
  assert.equal(run('workflowStatus().preflightCurrent'),false);
  assert.equal(el('btn-run').disabled,true);
  el('btn-params-save').classList.add('hidden'); el('btn-params-discard').classList.add('hidden');
  run('S.xmlDirty=true; refreshWorkflow()');
  assert.equal(el('btn-params-save').classList.contains('hidden'),false,'failed autosave must expose retry');
  assert.equal(el('btn-params-discard').classList.contains('hidden'),false,'failed autosave must expose discard');
  run('S.xmlDirty=false; refreshWorkflow()');
  run('markWorkflowPreflight({ok:true}); S.task.engineering_file="b.csv"; refreshWorkflow()');
  assert.equal(run('taskIdentityDirty()'),true,'CSV source must stale assembly');
  run('markWorkflowAssembled(S.job); markWorkflowPreflight({ok:true}); S.csvDirty=true; refreshWorkflow()');
  assert.equal(el('btn-preflight').disabled,true);
  assert.equal(el('btn-run').disabled,true);
  run('S.csvDirty=false; focusStage("assembly")'); assert.equal(el('stage-assembly').open,true);
  run('markWorkflowAssembled(S.job);');
  let release;
  ctx.fetch=async()=>({json:async()=>new Promise(resolve=>{release=resolve})});
  const pending=run('doPreflight()');
  await new Promise(resolve=>setImmediate(resolve));
  run('S.func="cali"; refreshWorkflow()'); release({ok:true}); await pending;
  assert.equal(run('workflowStatus().preflightCurrent'),false,'late check cannot pass a changed draft');
  run('markWorkflowAssembled(S.job); markWorkflowPreflight({ok:true});');
  ctx.fetch=async()=>{throw Error('connection lost')};
  await run('submitRender({job_name:"job"})');
  assert.equal(run('taskIdentityDirty()'),true,'unknown assembly write cannot leave old job runnable');
  console.log('PASS: semantic assembly identity, content invalidation, dirty guards and stale async checks');
})().catch(e=>{console.error(e);process.exitCode=1});

