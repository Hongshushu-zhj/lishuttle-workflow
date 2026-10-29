const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const nodes = new Map();
function el(id) {
  if (!nodes.has(id)) {
    const classes = new Set(['hidden']);
    nodes.set(id, {value:'',textContent:'',innerHTML:'',style:{},
      classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x)},
      setAttribute(){}, querySelectorAll(){return [];}});
  }
  return nodes.get(id);
}
const ctx = vm.createContext({document:{getElementById:el,querySelectorAll:()=>[]},setTimeout(){}});
vm.runInContext(fs.readFileSync('platform/frontend/app.js','utf8').replace(/init\(\);\s*$/, ''),ctx);
const run = code => vm.runInContext(code,ctx);
const result = {values:{PRESET:'release',BUILD_SUBDIR:'build/release',CMAKE:'/tools/cmake.exe'},
  fields:{PRESET:{source:'CMakePresets.json',candidates:[{value:'release',label:'Release · 已编译'},{value:'debug',label:'Debug'}]},
    CMAKE:{source:'本机检测',candidates:[{value:'/tools/cmake.exe',label:'CMake'}]}},
  presets:{release:{values:{BUILD_SUBDIR:'build/release',DLL_SRC:'dll/release'}},debug:{values:{BUILD_SUBDIR:'build/debug',DLL_SRC:'dll/debug'}}},warnings:[]};
ctx.result = result;
run(`renderCities=()=>{};renderTasks=()=>{};renderFuncRadios=()=>{};
  S.project='/A';S.profileId='A';S.profileRevision='1';S.projectEpoch=1;
  S.projectConfig={OUT_ROOT:'/saved/output'};S.projectDraft={...S.projectConfig};
  S.configTouched=new Set();S.projectManualFields=new Set();api=async()=>result;`);
(async()=>{
  assert.equal(run('typeof refreshProjectDetection'),'function','initial project detection must exist');
  await run('refreshProjectDetection()');
  assert.equal(run('S.projectDraft.PRESET'),'release');
  assert.equal(run('S.projectDraft.OUT_ROOT'),'/saved/output');
  assert.match(el('build-preset').innerHTML,/release/);
  assert.match(el('build-summary').textContent,/build\/release/);
  assert.equal(el('project-config-form').classList.contains('hidden'),false);
  run(`changeProjectConfigChoice('PRESET','debug')`);
  assert.equal(run('S.projectDraft.BUILD_SUBDIR'),'build/debug');
  run(`editProjectConfig('BUILD_SUBDIR','custom/build');changeProjectConfigChoice('PRESET','release')`);
  assert.equal(run('S.projectDraft.BUILD_SUBDIR'),'custom/build');
  run(`delete S.projectDetection.presets.debug.values.DLL_SRC;changeProjectConfigChoice('PRESET','debug')`);
  assert.equal(run('S.projectDraft.DLL_SRC'),'','a missing Debug DLL must not retain the Release recommendation');
  run(`S.projectDetection.presets.debug.values.DLL_SRC='dll/debug'`);
  let resolve;
  ctx.delayed = new Promise(r=>{resolve=r;});
  run(`api=()=>delayed;S.projectDraft.CMAKE='';S.configTouched.delete('CMAKE')`);
  const pending = run('refreshProjectDetection()');
  run(`editProjectConfig('CMAKE','/typed/cmake.exe')`);
  resolve(result);await pending;
  assert.equal(run('S.projectDraft.CMAKE'),'/typed/cmake.exe');
  let presetResponse;
  ctx.delayed = new Promise(r=>{presetResponse=r;});
  run(`S.projectDraft={};S.configTouched.clear();S.projectManualFields.clear()`);
  const presetPending = run('refreshProjectDetection()');
  run(`editProjectConfig('PRESET','debug')`);
  presetResponse(result);await presetPending;
  assert.equal(run('S.projectDraft.PRESET'),'debug');
  assert.equal(run('S.projectDraft.BUILD_SUBDIR'),'build/debug');
  assert.equal(run('S.projectDraft.DLL_SRC'),'dll/debug');
  let stale;
  ctx.delayed = new Promise(r=>{stale=r;});
  const old = run('refreshProjectDetection()');
  run(`S.project='/B';S.projectEpoch++;S.projectDraft={PRESET:'B'}`);
  stale(result);await old;
  assert.equal(run('S.projectDraft.PRESET'),'B');
  run(`api=async()=>{throw Error('offline')}`);
  await run('refreshProjectDetection()');
  assert.match(el('project-config-note').textContent,/offline/);
  // Loading a fresh state starts detection without requiring the form button.
  run(`api=async()=>result;fetch=()=>{};applyProjectState({project:'/C',profile_id:'C',profile_revision:'2',
    project_config:{OUT_ROOT:'/C/out'},functions:[],projects:['/C'],cities:[],tasks:[]})`);
  await new Promise(r=>setImmediate(r));
  assert.equal(run('S.projectDraft.PRESET'),'release');
  console.log('PASS: initial autofill, dropdown linkage, custom drafts, stale responses and retry status');
})().catch(e=>{console.error(e);process.exitCode=1;});

