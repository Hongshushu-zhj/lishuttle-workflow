const test = require('node:test'), assert = require('node:assert/strict');
const vm = require('node:vm'), fs = require('node:fs');
function fixture() {
  const nodes = {};
  const el = id => nodes[id] ??= {value: id === 'csv-path' ? 'a.csv' : '', textContent:'', innerHTML:'',
    classList:{add(){},remove(){}}, querySelector(){return this.table}, querySelectorAll(){return []}};
  const posts = [], messages = [];
  const c = vm.createContext({S:{job:{schema:'a.xml'},runtime:{busy:false},paramsData:{revision:'xml-1',values:{}}},
    $:el, post:(name,body)=>new Promise(resolve=>posts.push({name,body,resolve})), get:async()=>({}),
    toast:(...args)=>messages.push(args), refreshWorkflow(){},workflowContentChanged(){},focusStage(){},esc:String});
  vm.runInContext(fs.readFileSync('platform/frontend/editors.js','utf8'),c);
  return {c,el,posts,messages,run:s=>vm.runInContext(s,c)};
}
function parameter(f, name, value) {
  const el = f.el(name); el.dataset = {tag:name}; el.value = value;
  f.c[name] = el; return el;
}
test('parameter writes queue with saved versions and retain later draft', async()=>{
  const f=fixture(),a=parameter(f,'Alpha','1'); parameter(f,'Beta','2');
  const first=f.run('saveParameter(Alpha,S.job)'), second=f.run('saveParameter(Beta,S.job)');
  assert.equal(f.posts.length,1); assert.equal(f.posts[0].body.revision,'xml-1');
  a.value='new draft'; f.run('markParamDirty(Alpha)');
  f.posts[0].resolve({ok:true,revision:'xml-2',target:'schema'}); await first;
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.posts[1].body.revision,'xml-2');
  f.posts[1].resolve({ok:true,revision:'xml-3',target:'schema'}); await second;
  assert.equal(f.c.S.paramsData.revision,'xml-3'); assert.equal(f.c.S.xmlDirty,true);
  assert.equal(a.value,'new draft');
});
test('conflict keeps parameter value and its old version for explicit reload', async()=>{
  const f=fixture(); parameter(f,'Alpha','draft');
  const p=f.run('saveParameter(Alpha,S.job)'); f.posts[0].resolve({ok:false,code:'FILE_CONFLICT',error:'changed'}); await p;
  assert.equal(f.c.S.xmlDirty,true); assert.equal(f.c.S.paramsData.revision,'xml-1');
  assert.equal(f.c.Alpha.value,'draft'); assert.match(f.messages.at(-1)[0],/草稿/);
});
for(const headers of [[],[['Cell ID']],[['编号'],['Cell ID']]]) {
  test(`CSV save includes all records with ${headers.length} header rows`,async()=>{
    const f=fixture(); f.c.grid={path:'a.csv',header_rows:headers,header_lines:headers.length,rows:[['first'],['second']],
      editable:true,revision:'csv-1',format_revision:'format-1'};
    f.run('csvData=grid;markCsvDirty()');
    const trs=[...headers,["first"],["second"]].map(row=>({children:row.map(textContent=>({textContent}))}));
    f.el('csv-wrap').table={querySelectorAll:()=>trs};
    const p=f.run('saveCsv()'); assert.equal(f.posts[0].body.revision,'csv-1');
    assert.equal(f.posts[0].body.format_revision,'format-1');
    assert.deepEqual(JSON.parse(JSON.stringify(f.posts[0].body.rows)),[['first'],['second']]);
    assert.deepEqual(JSON.parse(JSON.stringify(f.posts[0].body.header_rows)),headers);
    f.run('markCsvDirty()'); f.posts[0].resolve({ok:true,revision:'csv-2'}); await p;
    assert.equal(f.c.S.csvDirty,true); assert.equal(f.run('csvData.revision'),'csv-2');
  });
}
test('unknown CSV layout disables writes and renders records read only',async()=>{
  const f=fixture(); f.run("csvData={path:'a.csv',header_rows:[],header_lines:0,rows:[['first']],editable:false,read_only_reason:'未知格式'};renderCsv()");
  assert.doesNotMatch(f.el('csv-wrap').innerHTML,/contenteditable/);
  assert.match(f.el('csv-msg').textContent,/未知格式/);
  await f.run('saveCsv()'); await f.run('setColumn()'); assert.equal(f.posts.length,0);
});
test('radius sends all dependency versions and advances only the CSV version', async()=>{
  const f=fixture(); parameter(f,'DefaultCalcRadius','300');
  f.c.S.paramsData.values.DefaultCalcRadius='800';
  f.c.S.paramsData.param_sources={DefaultCalcRadius:{kind:'engineering_csv',values:['100'],revision:'csv-1',format_revision:'format-1'}};
  const pending=f.run('saveParameter(DefaultCalcRadius,S.job)');
  assert.equal(f.posts[0].body.revision,'xml-1');
  assert.equal(f.posts[0].body.source_revision,'csv-1');
  assert.equal(f.posts[0].body.format_revision,'format-1');
  f.posts[0].resolve({ok:true,target:'engineering_csv',revision:'xml-1',source_revision:'csv-2'}); await pending;
  assert.equal(f.c.S.paramsData.revision,'xml-1');
  assert.equal(f.c.S.paramsData.param_sources.DefaultCalcRadius.revision,'csv-2');
  assert.equal(f.c.S.paramsData.values.DefaultCalcRadius,'800');
});
test('default restore includes revision and preserves an input typed during saving', async()=>{
  const f=fixture(), input=parameter(f,'Alpha','draft'), button=f.el('restore');
  button.dataset={defaultTag:'Alpha'}; f.c.button=button;
  const pending=f.run('restoreParameterDefault(button,S.job)');
  assert.equal(f.posts[0].body.revision,'xml-1');
  f.run('markParamDirty(Alpha)');
  f.posts[0].resolve({ok:true,revision:'xml-2'}); await pending;
  assert.equal(f.c.S.paramsData.revision,'xml-2');
  assert.equal(f.c.S.xmlDirty,true); assert.equal(input.value,'draft');
});
