const vm=require('node:vm'),assert=require('node:assert/strict');
const source=require('./frontend_source.cjs')();
function fixture(mutate=s=>s){
  const nodes=new Map();
  const el=id=>{if(!nodes.has(id)) nodes.set(id,{value:'',innerHTML:'',textContent:'',style:{},dataset:{},checked:false,disabled:false,open:false,
    setAttribute(){},removeAttribute(){},replaceChildren(){},focus(){},scrollIntoView(){},addEventListener(){},querySelectorAll:()=>[],
    classList:{add(){},remove(){},contains:()=>false,toggle(){}}});return nodes.get(id);};
  const ctx=vm.createContext({document:{getElementById:el,querySelectorAll:selector=>selector.includes('#params-area') ? [el('raw-xml'),el('raw-csv')] : [],querySelector:()=>null},setTimeout(){},setInterval(){},clearInterval(){}});
  vm.runInContext(mutate(source),ctx); const run=s=>vm.runInContext(s,ctx);
  run(`S.project='/p';S.projectEpoch=1;S.profileId='p';S.projectConfig={PRESET:'old',MAP_ROOT:'/saved',OUT_ROOT:'/out'};
    S.projectDraft={...S.projectConfig,PRESET:'new',MAP_ROOT:'/draft'};S.configTouched=new Set(['MAP_ROOT','OUT_ROOT']);S.projectManualFields=new Set(['OUT_ROOT']);
    S.buildWorkflow={built:false,presets:{new:{built:true,values:{PRESET:'new'}}}};S.city={name:'city'};S.task={name:'task',engineering_file:'old.csv'};
    refreshWorkflow=()=>{};renderProjectConfig=()=>{};focusStage=()=>{};invalidateSchemaPreview=()=>{};taskIdentityChanged=()=>{};
    renderCities=x=>{S.cities=x};renderTasks=x=>{S.tasks=x;S.task=null;clearCsvEditor()};renderFuncRadios=x=>{S.func=x};
    reply={project:'/p',profile_id:'p',profile_revision:'2',project_config:{PRESET:'new',MAP_ROOT:'/saved',OUT_ROOT:'/out'},
      build_workflow:{built:true,presets:{new:{built:true}}},functions:['pred'],projects:['/p'],cities:[],tasks:[]};
    calls=[];api=async(name,payload)=>{calls.push({name,payload});return reply};`);
  return {ctx,run,el};
}
async function reuse(mutate){const f=fixture(mutate);await f.run('useExecutable()');
  assert.equal(f.run('S.projectDraft.MAP_ROOT'),'/draft','resource draft survives');
  assert.equal(f.run("S.configTouched.has('OUT_ROOT')"),true,'equal-value touched metadata survives');
  assert.equal(f.run("S.projectManualFields.has('MAP_ROOT')"),false,'automatic resource stays automatic');
  assert.equal(f.run("S.projectManualFields.has('OUT_ROOT')"),true);
  assert.equal(f.run('S.city.name'),'city');assert.equal(f.run('S.task.name'),'task');
  assert.equal(f.run('calls.length'),1);assert.equal(f.run('calls[0].name'),'save_project_config');
  assert.equal(f.run('calls[0].payload.values.MAP_ROOT'),'/saved','unsaved resources are not persisted');
}
async function saveGuards(mutate){const f=fixture(mutate);f.run('refreshRuntimeState=async()=>{}');await f.run('init()');
  for(const kind of ['csvDirty','xmlDirty']){f.run(`calls=[];S.csvDirty=false;S.xmlDirty=false;S.${kind}=true;parameterDrafts.set('failed','draft')`);
    await f.el('project-config-form').onsubmit({preventDefault(){}});
    assert.equal(f.run('calls.length'),0,kind+' blocks project save');assert.equal(f.run(`S.${kind}`),true);assert.equal(f.run('parameterDrafts.size'),1);}
}
function engineering(mutate){const f=fixture(mutate);f.run(`S.xmlDirty=true;parameterDrafts.set('failed','draft');$('engineering-path').value='new.csv';$('csv-path').value='new.csv';selectEngineering('new.csv',true)`);
  assert.equal(f.run('S.xmlDirty'),true);assert.equal(f.run('parameterDrafts.size'),1);assert.equal(f.run('S.task.engineering_file'),'old.csv');assert.equal(f.el('engineering-path').value,'old.csv');assert.equal(f.el('csv-path').value,'old.csv');}
async function delayedTransition(mutate) {
  for(const action of ['save','switch','reuse']) for(const failure of [false,true]) {
    const f=fixture(mutate);f.run('refreshRuntimeState=async()=>{}');await f.run('init()');
    f.run(`S.task={name:'task',engineering_file:'old.csv'};S.city={name:'city'};
      S.projectDraft.PRESET='new';S.buildWorkflow.presets={new:{built:true}};S.pollTimer=null;S.pendingRequests=0;`);
    f.el('raw-csv').disabled=true; // An intrinsically unavailable control stays unavailable on unlock.
    const cell={contentEditable:'true'};f.el('csv-wrap').querySelectorAll=()=>[cell];
    let release;f.ctx.delayed=new Promise((resolve,reject)=>{release=failure ? ()=>reject(Error('network')) : ()=>resolve(f.run('reply'));});
    f.run('calls=[];api=async(name,payload)=>{calls.push({name,payload});return delayed}');
    const pending=action==='save' ? f.el('project-config-form').onsubmit({preventDefault(){}}) : f.run(action==='switch' ? "changeProject('select_project','/p')" : 'useExecutable()');
    assert.equal(f.el('raw-xml').disabled,true,action+' locks raw XML');assert.equal(cell.contentEditable,'false',action+' locks raw CSV');
    f.run('applyRuntimeState({busy:false,phase:"idle"})');
    assert.equal(f.el('raw-xml').disabled,true,'idle poll cannot unlock pending transition');assert.equal(cell.contentEditable,'false');
    await f.run('useExecutable()');await f.run("changeProject('select_project','/other')");
    assert.equal(f.run('calls.length'),1,'direct mutation actions refuse pending transition');
    f.run('markCsvDirty();markParamDirty({value:"new",classList:{add(){}}})');
    assert.equal(f.run('!!S.csvDirty || !!S.xmlDirty'),false,'direct input callbacks refuse pending transition');
    release();await pending;
    assert.equal(f.run('S.inputTransition'),false);assert.equal(f.el('raw-xml').disabled,false,'completion releases raw input');assert.equal(cell.contentEditable,'true');assert.equal(f.el('raw-csv').disabled,true,'intrinsic disabled state survives');
  }
}
(async()=>{await reuse();await saveGuards();engineering();await delayedTransition();
  // Mutation checks prove that each regression fails when its protection is removed.
  await assert.rejects(()=>reuse(s=>s.replace("applyBuildStatus({...result, build_values:Object.fromEntries(BUILD_KEYS.map(key=>[key,result.project_config?.[key] || '']))}, sentDraft);","applyProjectState(result,{preserveMachineDraft:true});")));
  await assert.rejects(()=>saveGuards(s=>s.replace("if (!guardCsvChanges() || S.xmlDirty) return toast('请先保存或放弃未保存的编辑',false);",'')));
  assert.throws(()=>engineering(s=>s.replace('if (S.inputTransition || !guardCsvChanges() || S.xmlDirty) {','if (!guardCsvChanges()) {')));
  await assert.rejects(()=>delayedTransition(s=>s.replace('const effectiveBusy = !!state.busy || !!S.inputTransition;', 'const effectiveBusy = !!state.busy;')));
  console.log('PASS: project draft guards, existing executable reuse without compilation, pending-transition locks, and four mutation regressions');
})().catch(e=>{console.error(e);process.exitCode=1});


