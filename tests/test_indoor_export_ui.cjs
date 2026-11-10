const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function fixture() {
  const nodes = new Map(), calls = [];
  const $ = id => {
    if (!nodes.has(id)) {
      const classes = new Set();
      nodes.set(id, {textContent:'',disabled:false,onclick:null,
        classList:{add:c=>classes.add(c),remove:c=>classes.delete(c),contains:c=>classes.has(c),
          toggle(c,force){if(force) classes.add(c); else classes.delete(c);}}});
    }
    return nodes.get(id);
  };
  const S = {project:'fixture',projectEpoch:1,func:'predindoor',job:{schema:'indoor.xml'},runtime:{busy:false}};
  const ctx = vm.createContext({S,$,focusStage:id=>calls.push({focus:id}),
    toast:message=>calls.push({message}),refreshWorkflow(){},guardCsvChanges:()=>true,
    post:async (name,body)=>{calls.push({name,body});return ctx.response;},
    get:async name=>{calls.push({name});return ctx.response;}});
  assert.ok(fs.existsSync('platform/frontend/indoor-building.js'), '缺少室内建筑导出交互');
  vm.runInContext(fs.readFileSync('platform/frontend/indoor-building.js','utf8'),ctx);
  const status = {supported:true,enabled:false,revision:'v1',path:'project/indoor.cpp',requires_rebuild:true};
  ctx.catalog = {function:'predindoor',indoor_building_export:status};
  return {S,$,ctx,calls,run:code=>vm.runInContext(code,ctx),status};
}

test('室内参数显示源码开关，其他功能隐藏，源码true仍提醒重新编译',()=>{
  const f=fixture(); f.run('renderIndoorBuildingExport(catalog)');
  assert.equal(f.$('indoor-building-panel').classList.contains('hidden'),false);
  assert.equal(f.$('btn-enable-indoor-building').disabled,false);
  assert.match(f.$('indoor-building-status').textContent,/未开启/);
  f.ctx.catalog.indoor_building_export.enabled=true;
  f.run('renderIndoorBuildingExport(catalog)');
  assert.equal(f.$('btn-enable-indoor-building').disabled,true);
  assert.match(f.$('indoor-building-status').textContent,/重新编译/);
  f.S.func='pred'; f.ctx.catalog.function='pred';
  f.run('renderIndoorBuildingExport(catalog)');
  assert.equal(f.$('indoor-building-panel').classList.contains('hidden'),true);
});

test('用户点击才按读取版本开启，明确源码保存与重新编译提醒',async()=>{
  const f=fixture(); f.run('renderIndoorBuildingExport(catalog)');
  assert.equal(f.calls.length,0);
  f.ctx.response={...f.status,enabled:true,revision:'v2',ok:true};
  await f.run('enableIndoorBuildingExport()');
  assert.equal(f.calls[0].name,'enable_indoor_building_export');
  assert.equal(f.calls[0].body.revision,'v1');
  assert.match(f.$('indoor-building-status').textContent,/重新编译/);
  f.$('btn-indoor-building-build').onclick();
  assert.equal(f.calls.at(-1).focus,'build');
});

test('源码冲突不自动换版本重试，保留重新检查入口',async()=>{
  const f=fixture(); f.run('renderIndoorBuildingExport(catalog)');
  f.ctx.response={error:'源码已变化',code:'FILE_CONFLICT'};
  await f.run('enableIndoorBuildingExport()');
  assert.equal(f.S.indoorBuildingExport.info.revision,'v1');
  assert.match(f.$('indoor-building-status').textContent,/源码已变化/);
  assert.match(f.$('indoor-building-status').textContent,/重新检查/);
});

test('运行中或有未保存编辑不修改源码，未知格式禁用开启',async()=>{
  const f=fixture(); f.run('renderIndoorBuildingExport(catalog)');
  f.S.runtime={busy:true}; await f.run('enableIndoorBuildingExport()');
  f.S.runtime={busy:false}; f.S.xmlDirty=true; await f.run('enableIndoorBuildingExport()');
  assert.equal(f.calls.filter(call=>call.name).length,0);
  f.S.xmlDirty=false; f.ctx.catalog.indoor_building_export={supported:false,reason:'未知源码布局'};
  f.run('renderIndoorBuildingExport(catalog)');
  assert.equal(f.$('btn-enable-indoor-building').disabled,true);
  assert.match(f.$('indoor-building-status').textContent,/未知源码布局/);
});

test('切换项目后的迟到开启响应不能恢复旧项目提示',async()=>{
  const f=fixture(); f.run('renderIndoorBuildingExport(catalog)');
  let release;
  f.ctx.post=()=>new Promise(resolve=>release=resolve);
  const pending=f.run('enableIndoorBuildingExport()');
  f.S.project='next'; f.S.projectEpoch=2; f.$('indoor-building-status').textContent='新项目';
  release({...f.status,enabled:true}); await pending;
  assert.equal(f.$('indoor-building-status').textContent,'新项目');
});

test('重新检查读取最新版本，不触发写入或自动编译',async()=>{
  const f=fixture(); f.run('renderIndoorBuildingExport(catalog)');
  f.ctx.response={...f.status,revision:'v3'};
  await f.run('reloadIndoorBuildingExport()');
  assert.equal(f.S.indoorBuildingExport.info.revision,'v3');
  assert.deepEqual(f.calls.map(call=>call.name),['indoor_building_export']);
});
