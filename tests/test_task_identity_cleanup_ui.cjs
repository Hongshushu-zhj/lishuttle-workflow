const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const nodes = new Map();
function el(id) {
  if (!nodes.has(id)) {
    const classes = new Set(['hidden']);
    nodes.set(id, {value:'',textContent:'',innerHTML:'',style:{},disabled:false,
      addEventListener(){}, querySelectorAll(){return [];},
      classList:{add:c=>classes.add(c),remove:c=>classes.delete(c),contains:c=>classes.has(c)}});
  }
  return nodes.get(id);
}
const ctx = vm.createContext({document:{getElementById:el,querySelectorAll:()=>[],querySelector:()=>null},setTimeout(){}});
vm.runInContext(fs.readFileSync('platform/frontend/app.js','utf8').replace(/init\(\);\s*$/,''),ctx);
const run = code => vm.runInContext(code,ctx);
run(`S.project='/engine';S.projectEpoch=1;S.job={name:'old',schema:'old.xml',func:'pred',taskId:'1'};`);
el('job-name').value='new'; el('task-id').value='1';
(async()=>{
  run('taskIdentityChanged()');
  assert.match(el('task-name-note').textContent,/重新装配/);
  let calls=[];
  ctx.respond=async(name,body)=>{calls.push({name,body});return {};};
  run('api=(name,body)=>respond(name,body)');
  await run('doRun()');
  assert.equal(calls.length,0,'renaming cannot silently execute the previous task');
  const plan={keep_schema:'old.xml',files:[{path:'/engine/build/Bin/runtimelibrary/history.xml'}],
    skipped:[],launch_changed:true,token:'snapshot'};
  ctx.plan=plan;
  ctx.respond=async(name,body)=>{calls.push({name,body});return body.apply
    ? {ok:true,message:'已归档',archive:'/workflow/docs/runtime-config-archives/one'} : plan;};
  await run('previewCleanup()');
  assert.equal(calls[0].body.keep_schema,'old.xml');
  assert.match(el('cleanup-preview-text').textContent,/history.xml/);
  assert.equal(el('btn-cleanup-apply').disabled,false);
  assert.equal(calls.length,1,'preview does not move files');
  await el('btn-cleanup-apply').onclick();
  assert.equal(calls[1].body.token,'snapshot');
  assert.equal(calls[1].body.apply,true);
  assert.match(el('cleanup-note').textContent,/docs\/runtime-config-archives/);
  await run('previewCleanup()');
  const staleApply=el('btn-cleanup-apply').onclick, before=calls.length;
  run('S.projectEpoch++');
  await staleApply();
  assert.equal(calls.length,before,'a preview cannot apply after changing project');
  let resolve;
  ctx.respond=()=>new Promise(r=>{resolve=r;});
  const pending=run('previewCleanup()');
  run('resetCleanupPreview()');
  resolve(plan); await pending;
  assert.equal(el('cleanup-preview').classList.contains('hidden'),true);
  console.log('PASS: task rename blocks old runs, cleanup preview/token, archival feedback and stale-project guards');
})().catch(e=>{console.error(e);process.exitCode=1;});
