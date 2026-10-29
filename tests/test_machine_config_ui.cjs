const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const nodes=new Map();
function el(id){
  if(!nodes.has(id)){
    const classes=new Set(['hidden']);
    nodes.set(id,{value:'',innerHTML:'',textContent:'',style:{},setAttribute(){},addEventListener(){},
      classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x),toggle(){}},querySelectorAll:()=>[]});
  }return nodes.get(id);
}
const machine={VS_ROOT:'/VS',CMAKE:'/VS/cmake.exe',NINJA:'/VS/ninja.exe',VCVARS:'/VS/vcvars64.bat'};
let state={project:'',projects:[],profile_id:'',profile_revision:'',machine_revision:'1',functions:[],cities:[],tasks:[],
  project_config:{...machine},machine_config:{...machine},machine_detection:{filled:[],candidates:{}}};
let sent;
const ctx=vm.createContext({document:{getElementById:el,querySelectorAll:()=>[]},setTimeout(){},
  fetch:async(url,opts)=>{sent={url,body:opts.body?JSON.parse(opts.body):null};return {json:async()=>state};}});
vm.runInContext(fs.readFileSync('platform/frontend/app.js','utf8').replace(/init\(\);\s*$/,''),ctx);
const run=code=>vm.runInContext(code,ctx);
run('renderCities=()=>{};renderTasks=()=>{};renderFuncRadios=()=>{}');
(async()=>{
  await run('init()');
  assert.ok(el('machine-config-fields').innerHTML.includes('/VS/cmake.exe'),'global tools must be visible without an engine project');
  assert.ok(!el('project-config-fields').innerHTML.includes('data-config-key="CMAKE"'),'tools must leave the per-project form');
  assert.match(el('machine-config-note').textContent,/所有项目/);
  run(`S.projectDraft.PRESET='unsaved-project';editProjectConfig('CMAKE','/chosen/cmake.exe')`);
  el('machine-config-fields').querySelectorAll=()=>Object.entries({...machine,CMAKE:'/chosen/cmake.exe'})
    .map(([key,value])=>({dataset:{configKey:key},value}));
  state={...state,machine_revision:'2',project_config:{...machine,CMAKE:'/chosen/cmake.exe'},machine_config:{...machine,CMAKE:'/chosen/cmake.exe'}};
  await el('machine-config-form').onsubmit({preventDefault(){}});
  assert.equal(sent.url,'/api/save_machine_config');
  assert.equal(sent.body._machine_revision,'1');
  assert.equal(sent.body.values.CMAKE,'/chosen/cmake.exe');
  assert.equal(sent.body.values.PRESET,undefined);
  assert.equal(run('S.projectDraft.PRESET'),'unsaved-project','saving global tools preserves project drafts');
  assert.equal(run('S.machineRevision'),'2');
  await el('btn-machine-detect').onclick();
  assert.equal(sent.url,'/api/detect_machine_config');
  assert.match(el('machine-config-note').textContent,/保存/);
  run(`editProjectConfig('CMAKE','/pending/cmake.exe')`);
  el('project-config-fields').querySelectorAll=()=>[{dataset:{configKey:'PRESET'},value:'release'}];
  await el('project-config-form').onsubmit({preventDefault(){}});
  assert.equal(sent.url,'/api/save_project_config');
  assert.equal(run('S.projectDraft.CMAKE'),'/pending/cmake.exe','saving a project must retain global tool drafts');
  run(`S.configTouched.clear();S.projectDraft={VS_ROOT:'/vs',CMAKE:'/VS/cmake.exe',NINJA:'/VS/ninja.exe',VCVARS:'/VS/vcvars64.bat'};
    S.machineDetection={candidates:{toolchains:{'/VS':{VS_ROOT:'/VS',CMAKE:'/VS/cmake.exe',NINJA:'/VS/ninja.exe',VCVARS:'/VS/vcvars64.bat'},
    '/OtherVS':{VS_ROOT:'/OtherVS',CMAKE:'/OtherVS/cmake.exe',NINJA:'/OtherVS/ninja.exe',VCVARS:'/OtherVS/vcvars64.bat'}}}};
    changeProjectConfigChoice('VS_ROOT','/OTHERVS')`);
  assert.equal(run('S.projectDraft.NINJA'),'/OtherVS/ninja.exe','Windows VS linkage is case insensitive');
  await el('project-config-form').onsubmit({preventDefault(){}});
  assert.equal(run('S.projectDraft.NINJA'),'/OtherVS/ninja.exe','project save preserves tools linked to a draft VS choice');
  assert.equal(run("S.configTouched.has('NINJA')"),false,'linked defaults remain eligible for later VS linkage');
  run(`changeProjectConfigChoice('VS_ROOT','/VS')`);
  assert.equal(run('S.projectDraft.NINJA'),'/VS/ninja.exe');
  console.log('PASS: global tools, separate form, machine revision, auto save and preserved project draft');
})().catch(e=>{console.error(e);process.exitCode=1;});
