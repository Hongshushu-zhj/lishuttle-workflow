const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const nodes = new Map();
function el(id) {
  if (!nodes.has(id)) nodes.set(id, {value:'', textContent:'', innerHTML:'', checked:false, style:{},
    listeners:{}, addEventListener(event, fn){this.listeners[event] = fn;},
    classList:{add(){}, remove(){}, toggle(){}}, querySelectorAll(){return [];}});
  return nodes.get(id);
}
const cityNode = {dataset:{name:'city-B'},classList:{add(){},remove(){}}};
const ctx = vm.createContext({document:{getElementById:el,querySelectorAll(selector){
  return selector === '#city-list .city' ? [cityNode] : [];
}},setTimeout(){}});
vm.runInContext(fs.readFileSync('platform/frontend/app.js','utf8').replace(/init\(\);\s*$/, ''),ctx);
vm.runInContext(`S.project='/project'; S.profileId='profile'; S.profileRevision='1'; S.projectEpoch=1;
  S.task={name:'task',dir:'/task',engineering_file:'/task/cells.csv',schema_candidates:[{
    path:'/task/task.xml',path_values:{SceneSettingsPath:'/old/scene.xml',HeightIndexPath:'/old/index.txt',
    PathlossDirectory:'/old/output',PolygonFilePath:'/old/region.txt'}}]};
  S.city={name:'city-A',kind:'outdoor'};`,ctx);
el('schema-source').value='/task/task.xml';
let requested=[];
ctx.fetch=async (url,options)=>{
  const body=JSON.parse(options.body); requested.push({url,body});
  return {json:async()=>({values:{SceneSettingsPath:'/project/build/Bin/runtimelibrary/scenesettings.xml',
    HeightIndexPath:`/maps/${body.city}/heights/index.txt`,PathlossDirectory:'/output'},warnings:[]})};
};
(async()=>{
  await vm.runInContext('refreshLocalPaths()',ctx);
  assert.match(el('local-path-fields').innerHTML,/value="\/maps\/city-A\/heights\/index.txt"/);
  assert.match(el('local-path-fields').innerHTML,/value="\/output"/);
  assert.doesNotMatch(el('local-path-fields').innerHTML,/data-local-path-tag="PolygonFilePath"/);
  vm.runInContext(`renderCities([{name:'city-B',kind:'outdoor',checks:[]}]);`,ctx);
  cityNode.onclick();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(requested.at(-1).body.city,'city-B');
  assert.match(el('local-path-fields').innerHTML,/\/maps\/city-B\/heights\/index.txt/);
  // Automatically supplied paths must not become persistent manual overrides.
  el('local-path-fields').querySelectorAll=()=>[
    {dataset:{localPathTag:'HeightIndexPath',autoPath:'/maps/city-B/heights/index.txt'},value:'/maps/city-B/heights/index.txt'},
    {dataset:{localPathTag:'SceneSettingsPath',autoPath:'/auto/scene.xml'},value:'/manual/scene.xml'},
    {dataset:{localPathTag:'PolygonFilePath'},value:'/old/region.txt'}];
  assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(collectLocalPaths())',ctx)),{SceneSettingsPath:'/manual/scene.xml'});
  // A stale response for the former city must never replace the new city's paths.
  let release;
  ctx.fetch=async()=>({json:()=>new Promise(resolve=>{release=resolve;})});
  const old=vm.runInContext('refreshLocalPaths()',ctx);
  await new Promise(resolve=>setImmediate(resolve));
  vm.runInContext(`S.city={name:'city-C',kind:'outdoor'};`,ctx);
  release({values:{HeightIndexPath:'/stale/index.txt'},warnings:[]});
  await old;
  assert.doesNotMatch(el('local-path-fields').innerHTML,/\/stale\/index.txt/);
  // A partially configured real project still fills known paths and explains missing values locally.
  el('local-path-fields').querySelectorAll=()=>[];
  ctx.fetch=async()=>({json:async()=>({values:{HeightIndexPath:'/maps/city-C/heights/index.txt',
    SceneSettingsPath:'/project/ThirdPart/Config/runtimelibrary/scenesettings.xml',PathlossDirectory:''},
    warnings:[],unresolved:{PathlossDirectory:'当前项目未配置 OUT_ROOT，请在项目配置填写'}})});
  await vm.runInContext('refreshLocalPaths({})',ctx);
  assert.match(el('local-path-fields').innerHTML,/value="\/maps\/city-C\/heights\/index.txt"/);
  assert.match(el('local-path-fields').innerHTML,/OUT_ROOT/);
  assert.match(el('local-path-status').textContent,/OUT_ROOT/);
  ctx.fetch=async()=>({json:async()=>({error:'本地路径接口暂不可用'})});
  await vm.runInContext('refreshLocalPaths({})',ctx);
  assert.match(el('local-path-status').textContent,/本地路径接口暂不可用/);
  // The radius control displays CSV values and sends edits through the CSV write route.
  const rows=[];
  ctx.document.createElement=()=>({innerHTML:'',querySelector(){return {appendChild(row){rows.push(row);}};}});
  el('params-area').appendChild=()=>{};
  const input={dataset:{tag:'DefaultCalcRadius'},value:'300',classList:{remove(){}},listeners:{},
    addEventListener(event,fn){this.listeners[event]=fn;}};
  el('params-area').querySelectorAll=selector=>selector.startsWith('input') ? [input] : [];
  vm.runInContext(`S.job={schema:'job.xml'};
    renderParams({values:{DefaultCalcRadius:'800'},groups:[{group:'范围',rows:[
      {name:'DefaultCalcRadius',label:'小区计算半径',type:'int'}]}],param_sources:{
      DefaultCalcRadius:{kind:'engineering_csv',values:['100','250'],fallback:'800',editable:true,
      column:'Main Calculation Radius (m)',path:'/task/cells.csv'}}});`,ctx);
  assert.match(rows[0].innerHTML,/各小区半径不同/);
  assert.match(rows[0].innerHTML,/100 \/ 250/);
  assert.doesNotMatch(rows[0].innerHTML,/data-default-tag="DefaultCalcRadius"/);
  assert.doesNotMatch(rows[0].innerHTML,/value="800"/);
  let radiusRequest;
  ctx.fetch=async(url,options)=>{radiusRequest={url,body:JSON.parse(options.body)};
    return {json:async()=>({ok:true,target:'engineering_csv',message:'CSV saved'})};};
  vm.runInContext('loadParams=async()=>{};',ctx);
  await input.listeners.change();
  assert.equal(radiusRequest.body.tag,'DefaultCalcRadius');
  assert.equal(radiusRequest.body.value,'300');
  assert.match(el('csv-wrap').textContent,/CSV/);
  console.log('PASS: auto local paths, map changes, single polygon control, manual overrides and stale response guard');
  console.log('PASS: CSV radius values, mixed cell radii, fallback display and CSV edit feedback');
})().catch(error=>{console.error(error);process.exitCode=1;});
