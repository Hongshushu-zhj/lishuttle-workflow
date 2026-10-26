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
ctx.catalog={file:'/project/Bin/runtimelibrary/job.xml',schema_name:'job',function:'pl',
 counts:{total:4,recommended:1,other:1,unclassified:2},values:{DefaultCalcResolution:'5',MinK0:'10',Vendor:'<raw>',Structured:'<Item>1</Item>'},
 groups:[{group:'范围',rows:[{name:'DefaultCalcResolution',label:'分辨率',type:'float',classification:'recommended',recommended:true}]},
 {group:'校正',rows:[{name:'MinK0',label:'K0下限',type:'float',classification:'other',recommended:false,func:'cali,dt'}]},
 {group:'未分类',rows:[{name:'Vendor',label:'Vendor',type:'text',classification:'unclassified',recommended:true},
 {name:'Structured',label:'Structured',type:'text',classification:'unclassified',recommended:true,read_only:true,read_only_reason:'结构化配置',display_value:'<Item>1</Item>'}]}]};
(async()=>{
  run("S.job={schema:'job.xml',func:'pl'};S.func='pl';renderParams(catalog)");
  assert.equal(rows.length,4,'all actual XML fields appear by default');
  assert.match(el('params-summary').textContent,/4/);
  assert.match(el('params-source').textContent,/job.xml/);
  assert.ok(rows.some(r=>r.innerHTML.includes('其他功能')));
  assert.ok(rows.some(r=>r.innerHTML.includes('未分类')));
  const structured=rows.find(r=>r.innerHTML.includes('Structured'));
  assert.match(structured.innerHTML,/readonly/);
  assert.doesNotMatch(structured.innerHTML,/data-tag="Structured"/);
  assert.match(structured.innerHTML,/&lt;Item>/);
  rows.length=0;el('params-scope').value='current';el('params-scope').onchange();
  assert.equal(rows.length,3,'function filter retains unknown fields, excludes known other-function fields');
  rows.length=0;el('params-scope').value='all';el('params-scope').onchange();
  assert.equal(rows.length,4);
  rows.length=0;el('params-search').value='Vendor';el('params-search').oninput();
  assert.equal(rows.length,1);
  assert.match(rows[0].innerHTML,/&lt;raw>/);
  let release;
  ctx.pending=new Promise(resolve=>{release=resolve;});
  run("S.func='cali';S.paramsSearch='';api=async()=>pending");
  const old=run('loadParams()');
  run("S.func='pl'");release(ctx.catalog);await old;
  assert.equal(run('S.paramsData.function'),'pl','late response from an earlier function does not replace current view');
  ctx.fetch=async(url)=>{ctx.requestUrl=url;return {json:async()=>ctx.catalog};};
  run("api=async(name,qs)=>{requestQuery=qs;return catalog};S.func='cali'");
  await run('loadParams()');
  assert.match(run('requestQuery'),/func=cali/,'uses current selected simulation function');
  assert.match(run('requestQuery'),/all=1/,'always fetches the complete actual inventory');
  const input={dataset:{tag:'DefaultCalcResolution'},value:'7',listeners:{},classList:{remove(){}},
    addEventListener(name,handler){this.listeners[name]=handler;}};
  el('params-area').querySelectorAll=selector=>selector.startsWith('input') ? [input] : [];
  ctx.savedCatalog=JSON.parse(JSON.stringify(ctx.catalog));
  ctx.savedCatalog.values.DefaultCalcResolution='7';
  ctx.savedCatalog.groups[0].rows[0].display_value='7';
  run("S.func='pl';S.paramsSearch='';renderParams(catalog);api=async name=>name==='param_write' ? {ok:true,target:'schema',values:savedCatalog.values} : savedCatalog;");
  await input.listeners.change();
  rows.length=0;el('params-scope').value='all';el('params-scope').onchange();
  assert.ok(rows.some(row=>row.innerHTML.includes('value="7"')),'filtering after a successful save keeps the actual saved value');
  console.log('PASS: full inventory, per-function filter, search, source/counts, readonly fields and stale function responses');
})().catch(e=>{console.error(e);process.exitCode=1;});
