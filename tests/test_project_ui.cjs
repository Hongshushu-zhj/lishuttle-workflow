const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const nodes = new Map();
const element = id => {
  if (!nodes.has(id)) nodes.set(id, {value:'', innerHTML:'', textContent:'', style:{}, classList:{add(){},remove(){}}});
  return nodes.get(id);
};
const context = vm.createContext({document:{getElementById:element}, setTimeout(){}});
vm.runInContext(fs.readFileSync('platform/frontend/app.js','utf8').replace(/init\(\);\s*$/, ''), context);
vm.runInContext(`
renderCities = cities => { S.cities = cities; };
renderTasks = tasks => { S.tasks = tasks; S.task = null; };
renderFuncRadios = f => { S.func = f; };
invalidateSchemaPreview = () => { S.previewCleared = true; };
S.job = {schema:'old.xml'}; S.city = {name:'old'};
applyProjectState({project:'/new',projects:['/new'],functions:['cali'],function_info:[{name:'cali'}],
 cities:[],tasks:[],map_root:'/maps',gongcan_root:'/tasks',preset:'custom',out_root:'/outputs'});
`, context);
assert.equal(vm.runInContext('S.job',context), null);
assert.equal(vm.runInContext('S.city',context), null);
assert.equal(vm.runInContext('S.func',context), 'cali');
assert.equal(vm.runInContext('S.project',context), '/new');
assert.equal(element('params-area').innerHTML, '');
assert.equal(element('project').value, '/new');
assert.equal(element('run-info').textContent, '尚未渲染');
assert.equal(vm.runInContext('S.previewCleared',context), true);
console.log('PASS: project switch refreshes functions and clears prior schema, preview and results');

// Exercise a real rendered default button and its write request.
const button = {dataset:{defaultTag:'SceneSettingsPath'}, disabled:false};
const rows = [];
context.document.createElement = tag => ({
  innerHTML:'', appendChild(child){rows.push(child);},
  querySelector(){return {appendChild(child){rows.push(child);}};}
});
element('params-area').appendChild = () => {};
element('params-area').querySelectorAll = selector => selector.startsWith('button') ? [button] : [];
context.fetch = async (url, options) => {
  context.request = {url, body:JSON.parse(options.body)};
  return {json:async()=>({ok:true})};
};
vm.runInContext(`
S.job = {schema:'new.xml'};
loadParams = async () => { S.reloaded = true; };
renderParams({values:{SceneSettingsPath:''},groups:[{group:'paths',rows:[
 {name:'SceneSettingsPath',label:'Scene',type:'path'}]}],thirdpart_defaults:{
 SceneSettingsPath:{available:true,value:'/new/ThirdPart/Config/config/scenesettings.xml',source:'/new/sample.xml'}}});
`, context);
assert.ok(rows.some(row=>row.innerHTML.includes('ThirdPart 默认')));
(async () => {
  await button.onclick();
  assert.equal(context.request.url, '/api/param_default');
  assert.equal(context.request.body.schema, 'new.xml');
  assert.equal(context.request.body.tag, 'SceneSettingsPath');
  assert.equal(vm.runInContext('S.reloaded',context), true);
  console.log('PASS: parameter default button writes selected field and reloads saved XML');
  element('result-job').value = 'old-job';
  context.fetch = async () => ({json: async () => {
    vm.runInContext('S.projectEpoch++; lastResultsDir = "";',context);
    return {dir:'/old/results',exists:true,files:[{rel:'old.csv',size:1}],log_tail:['old log']};
  }});
  element('result-files').innerHTML = '';
  await vm.runInContext('loadResults()',context);
  assert.equal(element('result-files').innerHTML, '');
  assert.equal(vm.runInContext('lastResultsDir',context), '');
  console.log('PASS: delayed results cannot restore an old project after switching');
})().catch(error=>{console.error(error);process.exitCode=1;});
