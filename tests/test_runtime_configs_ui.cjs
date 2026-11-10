const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');

function fixture() {
  const nodes = new Map(), calls = [];
  function el(id) {
    if (!nodes.has(id)) {
      const classes = new Set();
      nodes.set(id, {value:'',textContent:'',innerHTML:'',disabled:false,style:{},dataset:{},
        addEventListener(){},setAttribute(){},removeAttribute(){},focus(){},scrollIntoView(){},
        replaceChildren(...children){this.children=children;this.value=children[0]?.value || '';},
        add(child){(this.children ||= []).push(child);},querySelectorAll(){return [];},querySelector(){return null;},
        classList:{add:c=>classes.add(c),remove:c=>classes.delete(c),contains:c=>classes.has(c),
          toggle(c,on){on ? classes.add(c) : classes.delete(c);}}});
    }
    return nodes.get(id);
  }
  const c = vm.createContext({document:{getElementById:el,querySelectorAll:()=>[],querySelector:()=>null},
    setTimeout(){},clearInterval(){},Option:function(text,value){this.text=text;this.value=value;}});
  vm.runInContext(require('./frontend_source.cjs')(), c);
  const run = code => vm.runInContext(code,c);
  c.respond = async(name,body) => {calls.push({name,body});return {};};
  run(`api=(name,body)=>respond(name,body); S.project='/A';S.projectEpoch=1;S.profileRevision='1';
    S.functions=['pred','predindoor'];S.projectConfig={PRESET:'debug',BUILD_SUBDIR:'build/debug'};
    S.projectDraft={...S.projectConfig};S.buildWorkflow={built:true};
    S.runtime={busy:false};S.runtimeCatalog={scope:'A-debug',directory:'/A/Bin/runtimelibrary',configs:[]};`);
  el('task-id').value='1';
  const config = {schema:'saved.xml',revision:'r1',runtime_name:'actual-name',loadable:true,file:'/A/Bin/runtimelibrary/saved.xml'};
  const activated = {ok:true,job:{schema:'saved.xml',name:'actual-name',func:'pred',taskId:'1',outDir:'/custom/actual-name',mode:'existing'},revision:'r1',inputs:{engineering_file:'/outside/cells.csv'},validation_required:true};
  c.config=config;c.activated=activated;
  return {c,el,run,calls,config,activated};
}

test('loading XML uses the filename, preserves root name, and requires a new preflight', async()=>{
  const f=fixture();f.c.respond=async(name,body)=>{f.calls.push({name,body});return name==='activate_runtime_config'?f.activated:{groups:[],values:{},inputs:{engineering_file:'/outside/cells.csv'}};};
  f.run(`S.sid=55;S.resultSid=55;S.runVerdict='success';S.runtimeCatalog.configs=[config];$('selection-note').textContent='先前任务包与地图'`);
  await f.run(`activateRuntimeConfig('saved.xml')`);
  assert.equal(f.run('S.job.name'),'actual-name');assert.equal(f.run('S.job.schema'),'saved.xml');
  assert.equal(f.el('job-name').value,'actual-name');assert.equal(f.el('job-name').readOnly,true);
  assert.match(f.el('selection-note').textContent,/saved.xml.*actual-name/);
  assert.equal(f.el('csv-path').value,'/outside/cells.csv');assert.equal(f.run('S.sid'),0);
  assert.equal(f.run('S.resultSid'),0);assert.equal(f.run('S.runVerdict'),null);
  assert.equal(f.run('workflowStatus().actions.preflight.disabled'),false);
  assert.equal(f.run('workflowStatus().actions.run.disabled'),true);
  assert.equal(f.calls.some(x=>x.name==='render'),false);
});

test('refresh restores only the current scope saved choice, including changed XML contents', async()=>{
  const f=fixture();f.c.respond=async(name,body)=>{f.calls.push({name,body});
    if(name==='runtime_configs')return {scope:'A-debug',directory:'/A/Bin/runtimelibrary',configs:[{...f.config,revision:'r2'}],selected:{schema:'saved.xml',revision:'r1',func:'pred',task_id:'7'}};
    if(name==='activate_runtime_config')return {...f.activated,revision:'r2',job:{...f.activated.job,taskId:'7'}};
    return {groups:[],values:{}};};
  await f.run('refreshRuntimeConfigs({restore:true})');
  assert.equal(f.run('S.job.taskId'),'7');assert.match(f.el('runtime-config-status').textContent,/变化|最新/);
  const call=f.calls.find(x=>x.name==='activate_runtime_config');assert.equal(call.body.revision,'r2');assert.equal(call.body.scope,'A-debug');
});

test('missing saved XML is explained without rendering or choosing another file',async()=>{
  const f=fixture();f.c.respond=async()=>({scope:'A-debug',configs:[f.config],selected:{schema:'missing.xml',func:'pred',task_id:'1'}});
  await f.run('refreshRuntimeConfigs({restore:true})');assert.equal(f.run('S.job'),null);assert.match(f.el('runtime-config-status').textContent,/missing.xml|不存在|找不到/);
});

test('unsupported saved function requires an explicit new choice',async()=>{
  const f=fixture();f.c.respond=async()=>({scope:'A-debug',configs:[f.config],selected:{schema:'saved.xml',func:'obsolete',task_id:'1'}});
  await f.run('refreshRuntimeConfigs({restore:true})');assert.equal(f.run('S.job'),null);assert.match(f.el('runtime-config-status').textContent,/功能|obsolete/);
});

test('a delayed activation cannot restore the previous project',async()=>{
  const f=fixture();let resolve;f.c.respond=()=>new Promise(r=>{resolve=r;});f.run('S.runtimeCatalog.configs=[config]');
  const pending=f.run(`activateRuntimeConfig('saved.xml')`);f.run(`S.project='/B';S.projectEpoch++;resetRuntimeConfigs()`);resolve(f.activated);await pending;
  assert.equal(f.run('S.job'),null);
});

test('drafts and an active runtime block choosing another config or mode',async()=>{
  const f=fixture();f.run('S.csvDirty=true');await f.run(`activateRuntimeConfig('saved.xml')`);f.run(`setRuntimeConfigMode('new')`);
  assert.equal(f.calls.length,0);assert.notEqual(f.run('S.runtimeConfigMode'),'new');
  f.run('S.csvDirty=false;S.runtime.busy=true');await f.run(`activateRuntimeConfig('saved.xml')`);assert.equal(f.calls.length,0);
});

test('existing execution changes persist the selection and invalidate preflight without rendering',async()=>{
  const f=fixture();f.c.respond=async(name,body)=>{f.calls.push({name,body});return {...f.activated,job:{...f.activated.job,func:body.func,taskId:body.task_id}};};
  f.run(`S.runtimeConfigMode='existing';S.job={...activated.job};S.runtimeRevision='r1';$('job-name').value=S.job.name;markWorkflowAssembled(S.job);markWorkflowPreflight({ok:true});S.func='predindoor';$('task-id').value='9'`);
  await f.run('runtimeExecutionSelectionChanged()');
  assert.equal(f.run('S.job.func'),'predindoor');assert.equal(f.run('S.job.taskId'),'9');assert.equal(f.run('taskIdentityDirty()'),false);
  assert.equal(f.run('workflowStatus().preflightCurrent'),false);assert.equal(f.calls[0].name,'activate_runtime_config');assert.equal(f.calls.some(x=>x.name==='render'),false);
});

test('engineering input follows params XML source and never falls back to the previous CSV',()=>{
  const f=fixture();f.run(`S.job={...activated.job};applyRuntimeEngineering({engineering_file:'/first.csv'});applyRuntimeEngineering({engineering_file:''})`);
  assert.equal(f.el('csv-path').value,'');assert.match(f.el('engineering-reason').textContent,/没有|未配置|不可用/);
});

test('import preview exposes root name, output, warnings and same-name conflict',async()=>{
  const f=fixture();f.el('runtime-import-source').value='/external/saved.xml';f.el('runtime-import-name').value='copy.xml';
  f.c.respond=async()=>({token:'t',source:'/external/saved.xml',destination:'/A/Bin/runtimelibrary/copy.xml',runtime_name:'actual-name',out_dir:'/custom/actual-name',conflict:true,warnings:['相对资源路径按 Bin 解释']});
  await f.run('previewRuntimeImport()');assert.match(f.el('runtime-import-preview-text').textContent,/actual-name/);assert.match(f.el('runtime-import-preview-text').textContent,/custom/);assert.match(f.el('runtime-import-preview-text').textContent,/Bin/);
  assert.equal(f.el('btn-runtime-import-apply').disabled,true);
});

test('import confirmation becomes stale when destination changes',async()=>{
  const f=fixture();f.el('runtime-import-source').value='/external/saved.xml';f.el('runtime-import-name').value='copy.xml';
  f.c.respond=async(name,body)=>{f.calls.push({name,body});return {token:'t',source:'/external/saved.xml',destination:'/A/Bin/runtimelibrary/copy.xml',runtime_name:'actual-name',out_dir:'/custom/actual-name'};};
  await f.run('previewRuntimeImport()');f.el('runtime-import-name').value='other.xml';await f.run('importRuntimeConfig()');
  assert.equal(f.calls.length,1);
});

test('result directory uses the selected schema while session lookup keeps priority',async()=>{
  const f=fixture();f.run(`S.job={...activated.job};$('result-job').value=S.job.name`);
  f.c.respond=async(name,body)=>{f.calls.push({name,body});return {exists:false};};await f.run('loadResults()');assert.match(f.calls[0].body,/schema=saved.xml/);
  f.run(`S.resultSid=9;S.resultContext={task_name:'actual-name'}`);await f.run('loadResults()');assert.equal(f.calls[1].body,'?sid=9');
});

test('successful import refreshes the catalog and preserves the imported XML selection',async()=>{
  const f=fixture();f.el('runtime-import-source').value='/external/saved.xml';f.el('runtime-import-name').value='saved.xml';
  const select=f.el('runtime-config-select');let selected='';
  Object.defineProperty(select,'value',{get:()=>selected,set:value=>{selected=(select.children || []).some(option=>option.value===value)?value:'';}});
  f.c.respond=async(name,body)=>{f.calls.push({name,body});
    if(name==='preview_runtime_import')return {token:'t',runtime_name:'actual-name'};
    if(name==='import_runtime_config')return {...f.activated,cleanup_warning:'目标已导入；临时文件被占用：/A/Bin/runtimelibrary/.saved.xml.tmp'};
    if(name==='runtime_configs')return {scope:'A-debug',directory:'/A/Bin/runtimelibrary',configs:[f.config]};
    return {groups:[],values:{}};};
  await f.run('previewRuntimeImport()');await f.run('importRuntimeConfig()');
  assert.equal(f.run('S.job.schema'),'saved.xml');assert.equal(f.run('S.runtimeCatalog.configs.length'),1);
  assert.equal(f.el('runtime-config-select').value,'saved.xml');assert.equal(f.calls.find(x=>x.name==='import_runtime_config').body.token,'t');
  assert.match(f.el('runtime-config-status').textContent,/临时文件被占用/);
});

test('saving XML advances the revision used for execution selection without reassembling',async()=>{
  const f=fixture(),field=f.el('depth');field.dataset={tag:'MaxDeepth'};field.value='12';f.c.field=field;
  f.run(`S.runtimeConfigMode='existing';S.job={...activated.job};S.runtimeRevision='r1';S.paramsData={revision:'r1',values:{},groups:[]};$('job-name').value=S.job.name;markWorkflowAssembled(S.job)`);
  f.c.respond=async(name,body)=>{f.calls.push({name,body});return name==='param_write'?{ok:true,revision:'r2'}:name==='activate_runtime_config'?{...f.activated,revision:'r2'}:{groups:[],values:{},revision:'r2'};};
  await f.run('saveParameter(field,S.job)');await f.run('runtimeExecutionSelectionChanged()');
  assert.equal(f.calls.find(x=>x.name==='activate_runtime_config').body.revision,'r2');
});

test('engineering path edits preserve CSV drafts and resolve the saved XML path after explicit save',async()=>{
  const f=fixture(),field=f.el('engineering');field.dataset={tag:'EngineeringFilePath'};field.value='../data/new.csv';f.c.field=field;
  f.run(`S.job={...activated.job};S.paramsData={revision:'r1',values:{},groups:[]};S.csvDirty=true`);
  await f.run('saveParameter(field,S.job)');assert.equal(f.calls.length,0);assert.equal(f.run('S.xmlDirty'),true);
  f.c.respond=async(name,body)=>{f.calls.push({name,body});return name==='param_write'?{ok:true,revision:'r2'}:{inputs:{engineering_file:'/A/data/new.csv'},groups:[],values:{},revision:'r2'};};
  f.run('S.csvDirty=false');await f.run('saveParameter(field,S.job)');assert.equal(f.el('csv-path').value,'/A/data/new.csv');
});

test('project A to B to A restores each project XML without retaining a verdict or session',async()=>{
  const f=fixture();f.c.fetch=()=>{};
  f.c.respond=async(name,body)=>{
    if(name==='runtime_configs')return {scope:f.run('S.project')+'-debug',configs:[f.config],selected:{schema:'saved.xml',revision:'r1',func:'pred',task_id:'4'}};
    if(name==='activate_runtime_config')return {...f.activated,job:{...f.activated.job,name:body.scope,taskId:body.task_id}};
    return {groups:[],values:{}};};
  for (const project of ['/A','/B','/A']) {
    f.c.state={project,projects:['/A','/B'],profile_id:project,profile_revision:'1',functions:['pred'],cities:[],tasks:[],project_config:{PRESET:'debug',BUILD_SUBDIR:'build/debug'},build_workflow:{built:true}};
    f.run(`S.runVerdict='success';S.sid=77;S.resultSid=77;applyProjectState(state)`);await f.run('S.runtimeRestorePromise');
    assert.equal(f.run('S.job.name'),project+'-debug');assert.equal(f.run('S.sid'),0);assert.equal(f.run('S.runVerdict'),null);assert.equal(f.run('workflowStatus().preflightCurrent'),false);
  }
});

test('Debug to Release to Debug scopes restore same filenames independently',async()=>{
  const f=fixture();f.c.fetch=()=>{};f.run(`S.profileId='A';S.configTouched=new Set();`);
  f.c.respond=async(name,body)=>{
    const mode=f.run('S.projectConfig.PRESET');
    if(name==='runtime_configs')return {scope:mode,configs:[f.config],selected:{schema:'saved.xml',revision:'r1',func:'pred',task_id:mode==='debug'?'3':'8'}};
    if(name==='activate_runtime_config')return {...f.activated,job:{...f.activated.job,name:body.scope,taskId:body.task_id}};
    return {groups:[],values:{}};};
  for (const mode of ['debug','release','debug']) {
    f.c.build={build_values:{PRESET:mode,BUILD_SUBDIR:'build/'+mode},build_workflow:{built:true}};
    f.run(`S.projectDraft={...S.projectConfig,PRESET:build.build_values.PRESET};applyBuildStatus(build)`);await f.run('S.runtimeRestorePromise');
    assert.equal(f.run('S.job.name'),mode);assert.equal(f.run('S.job.taskId'),mode==='debug'?'3':'8');
  }
});

test('restoration deferred by an active runtime resumes after it becomes idle',async()=>{
  const f=fixture();f.run('S.runtime.busy=true');
  f.c.respond=async(name,body)=>{f.calls.push({name,body});if(name==='runtime_configs')return {scope:'A-debug',configs:[f.config],selected:{schema:'saved.xml',revision:'r1',func:'pred',task_id:'1'}};return name==='activate_runtime_config'?f.activated:{groups:[],values:{}};};
  await f.run('refreshRuntimeConfigs({restore:true})');assert.equal(f.calls.length,0);
  f.run(`applyRuntimeState({busy:false})`);await f.run('S.runtimeRestorePromise');assert.equal(f.run('S.job.schema'),'saved.xml');
});

test('restoring the default engineering path cannot bypass a CSV draft',async()=>{
  const f=fixture(),button=f.el('default');button.dataset={defaultTag:'EngineeringFilePath'};f.c.button=button;
  f.run(`S.job={...activated.job};S.csvDirty=true`);await f.run('restoreParameterDefault(button,S.job)');assert.equal(f.calls.length,0);
});

test('a saved engineering path cannot leave the old CSV selected when XML reread fails',async()=>{
  const f=fixture(),field=f.el('path');field.dataset={tag:'EngineeringFilePath'};field.value='new.csv';f.c.field=field;
  f.run(`S.job={...activated.job};S.paramsData={revision:'r1',values:{},groups:[]};applyRuntimeEngineering({engineering_file:'/old.csv'})`);
  f.c.respond=async name=>name==='param_write'?{ok:true,revision:'r2'}:{error:'无法重新读取 XML'};
  await f.run('saveParameter(field,S.job)');assert.equal(f.el('csv-path').value,'');assert.match(f.el('engineering-reason').textContent,/未配置|重新读取/);
});

test('a delayed execution selection cannot roll back a later saved XML revision or engineering source',async()=>{
  const f=fixture();let resolve;f.c.respond=name=>name==='activate_runtime_config'?new Promise(r=>{resolve=r;}):Promise.resolve({groups:[],values:{}});
  f.run(`S.job={...activated.job};S.runtimeRevision='r1';$('job-name').value=S.job.name;markWorkflowAssembled(S.job)`);
  const pending=f.run('runtimeExecutionSelectionChanged()');f.run(`S.runtimeRevision='r2';S.runtimeEngineeringRequest++;applyRuntimeEngineering({engineering_file:'/new.csv'});S.xmlDirty=true`);
  resolve(f.activated);await pending;assert.equal(f.run('S.runtimeRevision'),'r2');assert.equal(f.el('csv-path').value,'/new.csv');
});

test('changing a config candidate during execution-selection persistence never leaves pending stuck',async()=>{
  const f=fixture();let resolve;f.c.respond=name=>name==='activate_runtime_config'?new Promise(r=>{resolve=r;}):Promise.resolve({groups:[],values:{}});
  f.run(`S.job={...activated.job};S.runtimeCatalog.configs=[config,{...config,schema:'other.xml'}];S.runtimeRevision='r1';$('job-name').value=S.job.name;$('runtime-config-select').value=S.job.schema;markWorkflowAssembled(S.job);initRuntimeConfigs();S.func='predindoor'`);
  const pending=f.run('runtimeExecutionSelectionChanged()');f.el('runtime-config-select').value='other.xml';f.el('runtime-config-select').onchange();
  resolve({...f.activated,job:{...f.activated.job,func:'predindoor'}});await pending;
  assert.equal(f.run('S.runtimeExecutionPending'),false);assert.equal(f.run('workflowStatus().actions.preflight.disabled'),false);
});

test('late import previews and failed imports preserve the current source and destination draft',async()=>{
  const f=fixture();f.el('runtime-import-source').value='/external/a.xml';f.el('runtime-import-name').value='a.xml';let resolve;
  f.c.respond=()=>new Promise(r=>{resolve=r;});const pending=f.run('previewRuntimeImport()');
  f.el('runtime-import-name').value='b.xml';f.run('invalidateRuntimeImport()');resolve({token:'old',runtime_name:'old'});await pending;
  assert.equal(f.run('S.runtimeImportPreview'),null);
  f.c.respond=async name=>name==='preview_runtime_import'?{token:'current'}:{error:'目标刚被其他实例创建'};
  await f.run('previewRuntimeImport()');await f.run('importRuntimeConfig()');
  assert.equal(f.el('runtime-import-source').value,'/external/a.xml');assert.equal(f.el('runtime-import-name').value,'b.xml');assert.equal(f.run('S.job'),null);
});

test('import completion warns when the selection could not be remembered',async()=>{
  const f=fixture();f.el('runtime-import-source').value='/external/a.xml';f.el('runtime-import-name').value='saved.xml';
  f.c.respond=async name=>name==='preview_runtime_import'?{token:'t'}:name==='import_runtime_config'?{...f.activated,selection_warning:'档案无法写入'}:name==='runtime_configs'?{scope:'A-debug',configs:[f.config]}:{groups:[],values:{}};
  await f.run('previewRuntimeImport()');await f.run('importRuntimeConfig()');assert.equal(f.run('S.job.schema'),'saved.xml');assert.match(f.el('runtime-config-status').textContent,/档案无法写入/);
});

test('a newly saved engineering path refreshes the radius source from that XML',async()=>{
  const f=fixture(),field=f.el('path');field.dataset={tag:'EngineeringFilePath'};field.value='new.csv';f.c.field=field;
  f.run(`S.job={...activated.job};S.paramsData={revision:'r1',values:{},groups:[],param_sources:{DefaultCalcRadius:{kind:'engineering_csv',path:'/old.csv',revision:'old'}}}`);
  f.c.respond=async name=>name==='param_write'?{ok:true,revision:'r2'}:{inputs:{engineering_file:'/new.csv'},groups:[],values:{},revision:'r2',param_sources:{DefaultCalcRadius:{kind:'engineering_csv',path:'/new.csv',revision:'new',values:['3']}}};
  await f.run('saveParameter(field,S.job)');assert.equal(f.run('S.paramsData.param_sources.DefaultCalcRadius.path'),'/new.csv');
});
