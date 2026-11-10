const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const nodes = new Map();
function element(id) {
  if (!nodes.has(id)) {
    const classes = new Set();
    nodes.set(id, { value:'', checked:false, disabled:false, textContent:'', style:{},
      classList:{add:c=>classes.add(c),remove:c=>classes.delete(c),contains:c=>classes.has(c),toggle(){}},
      focus(){}, scrollIntoView(){}, querySelectorAll(){return [];} });
  }
  return nodes.get(id);
}
const context = vm.createContext({document:{getElementById:element,querySelector:()=>null,querySelectorAll:()=>[element('btn-apply-schema')]},setTimeout(){}});
vm.runInContext(require('./frontend_source.cjs')().replace(/init\(\);\s*$/,''),context);
const run = s=>vm.runInContext(s,context);
run(`S.city={name:'city',kind:'outdoor'}; S.task={name:'task',engineering_file:'a.csv'};`);
element('job-name').value='job'; element('schema-source').value='a.xml'; element('use-existing-schema').checked=true;
let renderReply = {error:'retry'};
let requests=[];
context.fetch=async(url,options)=>{
  const payload=JSON.parse(options.body); requests.push({url,payload});
  if(url.endsWith('preview_render')) { run('applyRuntimeState({busy:true})'); return {json:async()=>({source:'a',destination:'b',changes:[],warnings:[],token:'token'})}; }
  if(renderReply instanceof Error) throw renderReply;
  return {json:async()=>renderReply};
};
(async()=>{
  await run('doRender()'); run('applyRuntimeState({busy:false})');
  assert.equal(element('btn-apply-schema').disabled,false,'idle must preserve a valid preview');
  const oldHandler=element('btn-apply-schema').onclick;
  await oldHandler(); assert.equal(element('btn-apply-schema').disabled,false,'ordinary error can retry');
  renderReply={schema_ok:false}; await oldHandler(); assert.equal(element('btn-apply-schema').disabled,false,'schema failure can retry');
  run('applyRuntimeState({busy:true}); invalidateSchemaPreview(); applyRuntimeState({busy:false})');
  assert.equal(element('btn-apply-schema').disabled,true,'idle cannot revive an invalidated preview');
  const count=requests.length; await oldHandler(); assert.equal(requests.length,count,'old handler cannot write');
  await run('doRender()'); run('applyRuntimeState({busy:false})');
  run(`S.task.engineering_file='mutated.csv'`);
  const before=requests.length; await element('btn-apply-schema').onclick();
  assert.equal(requests.length,before,'direct mutable context change invalidates handler');
  await run('doRender()'); run('applyRuntimeState({busy:false})');
  renderReply=new Error('offline'); await element('btn-apply-schema').onclick();
  assert.equal(element('btn-apply-schema').disabled,true,'unknown write outcome requires new preview');
  assert.match(element('hint').textContent,/重新预览/);
  await run('doRender()'); run('applyRuntimeState({busy:false})');
  renderReply={error:'expired',code:'PREVIEW_STALE'}; await element('btn-apply-schema').onclick();
  assert.equal(element('btn-apply-schema').disabled,true);
  await run('doRender()'); run('applyRuntimeState({busy:false})');
  renderReply={error:'busy',code:'RUNTIME_BUSY',runtime:{busy:true}}; await element('btn-apply-schema').onclick();
  assert.equal(element('btn-apply-schema').disabled,true); run('applyRuntimeState({busy:false})');
  assert.equal(element('btn-apply-schema').disabled,false);
  let resolve; context.fetch=async()=>new Promise(r=>{resolve=r;});
  const handler=element('btn-apply-schema').onclick; const pending=handler(); await Promise.resolve();
  await handler(); assert.equal(element('btn-apply-schema').disabled,true);
  resolve({json:async()=>({error:'retry'})}); await pending;
  assert.equal(element('btn-apply-schema').disabled,false);
  let assembled=0;
  context.markWorkflowAssembled=()=>{assembled++;};
  run('switchTab=()=>{}; loadParams=()=>{}; updateNote=()=>{};');
  context.fetch=async()=>({json:async()=>({schema_ok:true,generated:false,render_status:'failed',assembly_status:'rolled_back',render_exit:1,render_output:'fatal: invalid XML',base_resources:{copied:[{from:'/source/new.dll',to:'/bin/new.dll'}],kept_count:2,config_source:'/config',dll_source:'/dll',exe_dir:'/bin'}})});
  const fatal = await run(`submitRender({job_name:'job'})`);
  assert.equal(fatal.status,'retryable_error');
  assert.equal(assembled,0,'old XML must never confirm failed generation');
  assert.match(element('render-output').textContent,/fatal: invalid XML/);
  assert.match(element('render-output').textContent,/已撤销/,'reverted resource copies must be labeled as reverted');
  context.fetch=async()=>({json:async()=>({error:'resource copy failed',render_output:'fatal copy details',generated:false,render_status:'failed',schema_ok:false})});
  await run(`submitRender({job_name:'job'})`);
  assert.match(element('render-output').textContent,/fatal copy details/,'failure details remain visible');
  context.fetch=async(url)=>({json:async()=> url.endsWith('preview_render')
    ? {source:'a',destination:'b',changes:[],warnings:[],token:'next'}
    : {schema_ok:true,generated:true,render_status:'missing_inputs',render_exit:1,schema_name:'job.xml',func:'pl',task_id:'1',out_dir:'/out'}});
  run('switchTab=()=>{}; loadParams=()=>{}; updateNote=()=>{};');
  await run('doRender()'); await element('btn-apply-schema').onclick();
  assert.equal(element('schema-preview').classList.contains('hidden'),true,'successful assembly clears preview');
  assert.equal(element('btn-apply-schema').disabled,true);
  assert.equal(run('S.job.schema'),'job.xml');
  assert.equal(assembled,1,'valid generation with missing inputs still confirms assembly');
  console.log('PASS: assembly preview validity, busy/idle races, retry, stale token, network recovery and duplicate guard');
})().catch(e=>{console.error(e);process.exitCode=1;});

