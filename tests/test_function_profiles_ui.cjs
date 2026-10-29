const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),rows=[];
function el(id){
  if(!nodes.has(id)) nodes.set(id,{value:'',innerHTML:'',textContent:'',style:{},children:[],
    classList:{add(){},remove(){}},querySelectorAll(){return [];},appendChild(child){this.children.push(child);}});
  return nodes.get(id);
}
const ctx=vm.createContext({document:{getElementById:el,querySelectorAll:()=>[],createElement(){return {
  innerHTML:'',querySelector(){return {appendChild(row){rows.push(row);}};}};}},setTimeout(){}});
vm.runInContext(fs.readFileSync('platform/frontend/app.js','utf8').replace(/init\(\);\s*$/,''),ctx);
const run=code=>vm.runInContext(code,ctx);
ctx.catalog={file:'/project/job.xml',function:'acp',values:{IsOptEleTilt:'false',MaxEleTilt:'6',SigmaRCS:'1',Vendor:'x'},
  counts:{total:4,recommended:2,other:1,unclassified:1},profile:{reviewed:true,description:'基于覆盖指标的优化',
    scene_warning:'当前地图与功能不匹配',missing_required:['PolygonFilePath'],missing_optional:['MaxVarJitter'],
    source_review:{status:'changed',changed:['ACP/Common/src/ACPCommonParams.cpp']},notes:[]},
  groups:[{group:'优化',rows:[
    {name:'IsOptEleTilt',type:'bool',recommended:true,classification:'recommended',usage:{kind:'function',active:true,source:'ACP.cpp:376',required:true}},
    {name:'MaxEleTilt',recommended:true,classification:'recommended',usage:{kind:'function',active:false,condition:'IsOptEleTilt=true',source:'ACP.cpp:381'}},
    {name:'SigmaRCS',recommended:false,classification:'other',usage:{kind:'startup',active:true,note:'仅共用解析器读取',source:'ACP.cpp:329'}},
    {name:'Vendor',recommended:true,classification:'unclassified'}]}]};
run("S.job={schema:'job.xml',func:'acp'};S.func='acp';S.paramsScope=null;renderParams(catalog)");
assert.equal(el('params-scope').value,'current','reviewed function defaults to its own configurable parameters');
assert.equal(rows.length,3,'function view includes conditional parameters and visible unclassified fields');
assert.ok(rows.some(row=>row.innerHTML.includes('条件未启用')));
assert.match(el('params-profile').innerHTML,/PolygonFilePath/);
assert.match(el('params-profile').innerHTML,/源码.*差异/);
assert.match(el('params-profile').innerHTML,/当前地图与功能不匹配/);
rows.length=0;el('params-scope').value='active';el('params-scope').onchange();
assert.equal(rows.length,1,'active view excludes disabled conditions, unrelated startup values and unknown fields');
rows.length=0;el('params-scope').value='all';el('params-scope').onchange();
assert.equal(rows.length,4);
assert.ok(rows.some(row=>row.innerHTML.includes('仅启动读取')));
assert.ok(rows.some(row=>row.innerHTML.includes('ACP.cpp:329')));
ctx.catalog.profile.scene_warning='<script>unsafe</script>';
run('renderParams(catalog)');
assert.doesNotMatch(el('params-profile').innerHTML,/<script>/,'source diagnostics are safely escaped');
console.log('PASS: personalized default scope, conditional fields, active-only filter, source evidence and missing-field guidance');
