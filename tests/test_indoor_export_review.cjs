const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function fixture() {
  const nodes = new Map(), calls = [];
  const $ = id => {
    if (!nodes.has(id)) nodes.set(id, {textContent:'', disabled:false,
      classList:{toggle(){},add(){},remove(){}}});
    return nodes.get(id);
  };
  const info = {supported:true, enabled:false, revision:'source-v1', requires_rebuild:true};
  const catalog = {function:'predindoor', indoor_building_export:info};
  const S = {project:'same-project', projectEpoch:1, func:'predindoor',
    job:{schema:'indoor.xml'}, runtime:{busy:false}, paramsData:catalog};
  const context = vm.createContext({S,$,focusStage(){},guardCsvChanges:()=>true,
    workflowContentChanged(){},toast:message=>calls.push({toast:message}),
    post:async(name,body)=>{calls.push({name,body});return context.response;},
    get:async name=>{calls.push({name});return context.response;}});
  vm.runInContext(fs.readFileSync('platform/frontend/indoor-building.js','utf8'), context);
  const run = source => vm.runInContext(source,context);
  run('renderIndoorBuildingExport(S.paramsData)');
  return {S,$,calls,context,run,info};
}

test('开启成功后参数搜索或范围重绘保留最新源码状态和版本',async()=>{
  const f=fixture();
  f.context.response={...f.info,enabled:true,revision:'source-v2',ok:true};
  await f.run('enableIndoorBuildingExport()');
  assert.equal(f.S.indoorBuildingExport.info.enabled,true);
  // renderParams calls the switch renderer with the cached parameter catalog.
  f.run('renderIndoorBuildingExport(S.paramsData)');
  assert.equal(f.S.indoorBuildingExport.info.enabled,true);
  assert.equal(f.S.indoorBuildingExport.info.revision,'source-v2');
  assert.equal(f.$('btn-enable-indoor-building').disabled,true);
});

test('开启请求期间同项目参数重绘不会丢弃成功响应',async()=>{
  const f=fixture();let release;
  f.context.post=()=>new Promise(resolve=>release=resolve);
  const pending=f.run('enableIndoorBuildingExport()');
  f.run('renderIndoorBuildingExport(S.paramsData)');
  release({...f.info,enabled:true,revision:'source-v2',ok:true});
  await pending;
  assert.equal(f.S.indoorBuildingExport.info.enabled,true);
  assert.equal(f.S.indoorBuildingExport.info.revision,'source-v2');
  assert.match(f.$('indoor-building-status').textContent,/重新编译/);
});

test('重新检查取得新版本后参数重绘不会回退旧版本',async()=>{
  const f=fixture();
  f.context.response={...f.info,enabled:true,revision:'external-v3'};
  await f.run('reloadIndoorBuildingExport()');
  assert.equal(f.S.indoorBuildingExport.info.revision,'external-v3');
  f.run('renderIndoorBuildingExport(S.paramsData)');
  assert.equal(f.S.indoorBuildingExport.info.revision,'external-v3');
  assert.equal(f.S.indoorBuildingExport.info.enabled,true);
});

test('重新检查失败保留原revision且不自动写入，后端冲突仍明确显示',async()=>{
  const f=fixture();
  f.context.get=async()=>{throw Error('offline');};
  await f.run('reloadIndoorBuildingExport()');
  assert.equal(f.S.indoorBuildingExport.info.revision,'source-v1');
  assert.match(f.$('indoor-building-status').textContent,/读取失败.*offline/);
  assert.equal(f.calls.filter(call=>call.name).length,0);
  f.context.response={ok:false,error:'源码已变化',code:'FILE_CONFLICT'};
  await f.run('enableIndoorBuildingExport()');
  assert.equal(f.calls.find(call=>call.name)?.body.revision,'source-v1');
  assert.match(f.$('indoor-building-status').textContent,/源码已变化/);
  assert.equal(f.S.indoorBuildingExport.info.enabled,false);
});

test('开启前发出的参数读取迟到时不能覆盖新源码开关',async()=>{
  const f=fixture();let release;
  vm.runInContext(fs.readFileSync('platform/frontend/editors.js','utf8'),f.context);
  f.run('renderParams = r => {S.paramsData=r;renderIndoorBuildingExport(r)};S.paramsForJob=S.job');
  f.context.get=()=>new Promise(resolve=>release=resolve);
  const pending=f.run('loadParams()');
  f.context.response={...f.info,enabled:true,revision:'source-v2',ok:true};
  await f.run('enableIndoorBuildingExport()');
  release({function:'predindoor',indoor_building_export:f.info});
  await pending;
  assert.equal(f.S.indoorBuildingExport.info.enabled,true);
  assert.equal(f.S.paramsData.indoor_building_export.revision,'source-v2');
});

test('开启前发出的重新检查迟到时不能覆盖成功提示',async()=>{
  const f=fixture();let release;
  f.context.get=()=>new Promise(resolve=>release=resolve);
  const pending=f.run('reloadIndoorBuildingExport()');
  f.context.response={...f.info,enabled:true,revision:'source-v2',ok:true};
  await f.run('enableIndoorBuildingExport()');
  release({...f.info,enabled:false,revision:'source-v1'});
  await pending;
  assert.equal(f.S.indoorBuildingExport.info.enabled,true);
  assert.equal(f.S.indoorBuildingExport.info.revision,'source-v2');
  assert.match(f.$('indoor-building-status').textContent,/重新编译/);
});
