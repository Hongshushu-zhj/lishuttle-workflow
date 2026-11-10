const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

const spec = JSON.parse(fs.readFileSync('platform/backend/params_spec.json','utf8'));
const controls = ['MaxRayNumber','MaxDeepth','MaxDiffraction','MaxReflection','MaxPenetration',
  'IndoorRxPowerSF','IndoorSinrSF','IsForcedCalc','DefaultUEHeight'];

function fixture({missing=[],duplicateHeight=false}={}) {
  const nodes=new Map(),rows=[],calls=[],inputs=new Map();
  const el=id=>{
    if(!nodes.has(id)) nodes.set(id,{value:'',checked:false,textContent:'',innerHTML:'',style:{},disabled:false,
      classList:{add(){},remove(){},toggle(){}},querySelectorAll(){return [];},appendChild(){}});
    return nodes.get(id);
  };
  const ctx=vm.createContext({console,document:{getElementById:el,querySelectorAll(){return [];},
    createElement(){return {innerHTML:'',querySelector(){return {appendChild(row){rows.push(row);}};}};}},setTimeout(){}});
  vm.runInContext(require('./frontend_source.cjs')(),ctx);
  const run=source=>vm.runInContext(source,ctx);
  const present=controls.filter(name=>!missing.includes(name));
  const catalog={function:'predindoor',file:'D:/fixture/Bin/runtimelibrary/indoor.xml',schema_name:'indoor',revision:'xml-1',
    values:Object.fromEntries(present.map(name=>[name,name==='IsForcedCalc'?'false':name==='DefaultUEHeight'?'1.2':'5'])),
    profile:{reviewed:true,label:'室内覆盖预测',scene:'indoor',description:'室内路损与预测',
      source_review:{status:'matched'},missing_required:[],missing_optional:missing,notes:[]},
    groups:[{group:'室内参数',rows:present.map(name=>({...spec.params.find(row=>row.name===name),
      recommended:true,classification:'recommended',usage:{kind:'dependency',active:true,source:'indoor.cpp'},
      ...(name==='DefaultUEHeight'&&duplicateHeight ? {read_only:true,occurrences:2,display_value:'[1] 1.2\n[2] 1.5',
        read_only_reason:'同名字段重复，已列出各项原值；请在 XML 中明确配置，平台不猜测修改哪一项'} : {})}))}]};
  ctx.catalog=catalog;
  run(`S.job={schema:'indoor.xml',func:'predindoor'};S.func='predindoor';S.projectEpoch=1;
    refreshWorkflow=()=>{};workflowContentChanged=reason=>{S.changedReason=reason};`);
  el('params-area').querySelectorAll=selector=>selector.startsWith('input') ? [...inputs.values()] : [];
  ctx.fetch=async(url,options={})=>{
    calls.push({url,body:options.body?JSON.parse(options.body):null});
    return {json:async()=>({ok:true,target:'schema',revision:'xml-2'})};
  };
  const addInput=(tag,value)=>{
    const input={dataset:{tag},value,listeners:{},classList:{add(){},remove(){}},
      addEventListener(name,handler){this.listeners[name]=handler;}};
    inputs.set(tag,input);return input;
  };
  const render=()=>{rows.length=0;run('renderParams(catalog)');};
  return {run,el,catalog,rows,calls,addInput,render};
}

test('室内射线与缩放参数在本功能视图提供XML编辑，并说明无需重编译',()=>{
  const f=fixture();f.render();
  assert.equal(f.el('params-scope').value,'current');
  for(const name of controls) assert.ok(f.rows.some(row=>row.innerHTML.includes(`data-tag="${name}"`)),name);
  assert.match(f.el('params-source').textContent,/XML.*无需.*编译/);
  assert.match(f.el('params-source').textContent,/indoor\.xml/);
});

test('旧室内任务缺少射线字段时提示从室内样例重新装配，不展示假默认值或自动写入',()=>{
  const f=fixture({missing:['MaxDeepth','MaxReflection','MaxDiffraction','MaxPenetration']});
  f.render();
  assert.match(f.el('params-profile').innerHTML,/室内样例.*重新装配/);
  assert.match(f.el('params-profile').innerHTML,/MaxDeepth/);
  assert.match(f.el('params-profile').innerHTML,/不会自动.*(添加|补写)/);
  for(const tag of ['MaxDeepth','MaxReflection','MaxDiffraction','MaxPenetration'])
    assert.ok(f.rows.every(row=>!row.innerHTML.includes(`data-tag="${tag}"`)),tag);
  assert.equal(f.calls.length,0);
});

test('室内样例重复DefaultUEHeight保留各项原值且只读，不猜测写哪一项',()=>{
  const f=fixture({duplicateHeight:true});f.render();
  const row=f.rows.find(row=>row.innerHTML.includes('DefaultUEHeight'));
  assert.match(row.innerHTML,/readonly/);
  assert.match(row.innerHTML,/\[1\] 1\.2/);
  assert.match(row.innerHTML,/\[2\] 1\.5/);
  assert.match(row.innerHTML,/同名字段重复.*不猜测/);
  assert.doesNotMatch(row.innerHTML,/data-(?:tag|default-tag)="DefaultUEHeight"/);
  assert.equal(f.calls.length,0);
});

test('修改MaxDeepth仅保存当前XML参数，保持原字段拼写且不自动切换强制重算',async()=>{
  const f=fixture();const depth=f.addInput('MaxDeepth','7');f.render();
  await depth.listeners.change();
  assert.equal(f.calls.length,1);
  assert.equal(f.calls[0].url,'/api/param_write');
  assert.equal(f.calls[0].body.tag,'MaxDeepth');
  assert.equal(f.calls[0].body.schema,'indoor.xml');
  assert.equal(f.calls[0].body.value,'7');
  assert.equal(f.calls[0].body.revision,'xml-1');
  assert.equal(f.run('S.paramsData.values.IsForcedCalc'),'false');
  assert.equal(f.run('S.changedReason'),'XML 参数已保存');
});
