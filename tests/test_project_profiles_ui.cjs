const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const nodes = new Map();
const el = id => {
  if (!nodes.has(id)) nodes.set(id, {value:'',textContent:'',innerHTML:'',style:{},listeners:{},
    addEventListener(event, handler){(this.listeners[event] ||= []).push(handler);},
    classList:{add(){},remove(){},toggle(){}}, querySelectorAll(){return [];}});
  return nodes.get(id);
};
const context = vm.createContext({document:{getElementById:el,querySelectorAll(){return [];}}, setTimeout(){}});
vm.runInContext(fs.readFileSync('platform/frontend/app.js','utf8').replace(/init\(\);\s*$/, ''), context);
vm.runInContext(`
renderCities = cities => { S.cities = cities; };
renderTasks = tasks => { S.tasks = tasks; S.task = null; };
renderFuncRadios = () => {};
applyProjectState({project:'/A',projects:['/A'],functions:[],cities:[{name:'city',kind:'outdoor'}],tasks:[],
 map_root:'/map',gongcan_root:'/tasks',profile_id:'A',profile_revision:'7',
 project_config:{PRESET:'preset-A',CMAKE:'/A/cmake.exe'}});
`, context);
assert.equal(vm.runInContext('S.profileRevision',context), '7');
assert.ok(el('project-config-fields').innerHTML.includes('preset-A'));
assert.ok(el('project-config-fields').innerHTML.includes('CMAKE'));
el('local-path-fields').querySelectorAll = () => [{dataset:{localPathTag:'SceneSettingsPath'},value:'/local/scene.xml'},
  {dataset:{localPathTag:'DriverTestFileDictionaryPath'},value:''}];
assert.equal(vm.runInContext('collectLocalPaths().SceneSettingsPath',context), '/local/scene.xml');
assert.equal(vm.runInContext('Object.keys(collectLocalPaths()).length',context), 1);
let request;
context.fetch = async (url, options) => {
  request = {url,body:JSON.parse(options.body)};
  return {json:async()=>({binding:{city:'city',engineering_file:'/task/a.csv',schema_source:'/task/schema.xml',
    path_overrides:{SceneSettingsPath:'/local/scene.xml'},sync_engineering:true,polygon_file:''}})};
};
(async () => {
  vm.runInContext(`S.task={name:'task',dir:'/task',engineering_file:'/task/a.csv',schema_candidates:[]};`,context);
  el('schema-source').value = '/task/schema.xml';
  await vm.runInContext('restoreTaskBinding()',context);
  assert.equal(request.body._revision, '7');
  assert.equal(request.body._project, '/A');
  assert.equal(vm.runInContext('S.city.name',context), 'city');
  assert.equal(el('sync-engineering').checked, true);
  assert.ok(el('local-path-fields').innerHTML.includes('/local/scene.xml'));
  vm.runInContext('bindActions(); S.city=null;',context);
  el('schema-source').onchange();
  for (const handler of el('schema-source').listeners.change || []) handler();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(vm.runInContext('S.city?.name',context), 'city', 'manual XML selection restores its saved map');
  vm.runInContext('S.city=null;',context);
  context.fetch = async () => ({json:async()=>{
    vm.runInContext('S.projectEpoch++;',context);
    return {binding:{city:'city'}};
  }});
  await vm.runInContext('restoreTaskBinding()',context);
  assert.equal(vm.runInContext('S.city',context), null);
  console.log('PASS: project profile form, revision guard, local paths and task-map restoration');
})().catch(error=>{console.error(error);process.exitCode=1;});
