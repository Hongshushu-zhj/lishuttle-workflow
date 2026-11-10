const test = require('node:test'), assert = require('node:assert/strict');
const vm = require('node:vm'), fs = require('node:fs');

function fixture() {
  const nodes = {}, posts = [], gets = [];
  const el = id => nodes[id] ??= {value:id === 'csv-path' ? 'a.csv' : '', textContent:'', innerHTML:'',
    classList:{add(){},remove(){}}, querySelector(){return this.table}, querySelectorAll(){return []}};
  const c = vm.createContext({S:{job:{schema:'a.xml'},projectEpoch:1,runtime:{busy:false},paramsData:{revision:'xml-1',values:{},
    param_sources:{DefaultCalcRadius:{kind:'engineering_csv',path:'a.csv',revision:'csv-1',column_index:1,values:['100']}}}},
    $:el, post:(name,body)=>new Promise(resolve=>posts.push({name,body,resolve})),
    get:(name,query)=>new Promise(resolve=>gets.push({name,query,resolve})),
    toast(){},refreshWorkflow(){},workflowContentChanged(){},focusStage(){},esc:String});
  vm.runInContext(fs.readFileSync('platform/frontend/editors.js','utf8'), c);
  const run = source => vm.runInContext(source,c);
  const grid = {path:'a.csv',header_rows:[['Cell ID','CalcRadius','Comment']],header_lines:1,
    rows:[['c1','100','old comment']],editable:true,revision:'csv-1',format_revision:'format-1'};
  c.grid = grid;
  run('csvData=grid');
  const rows = [...grid.header_rows,...grid.rows].map(row=>({children:row.map(textContent=>({textContent}))}));
  el('csv-wrap').table = {querySelectorAll:()=>rows};
  return {c,el,posts,gets,run,rows};
}
const tick = () => new Promise(resolve=>setImmediate(resolve));

test('draft entered while column reload is pending cannot overwrite the saved column with an old grid',async()=>{
  const f = fixture();
  f.el('csv-col').value = 'CalcRadius'; f.el('csv-val').value = '200';
  const pending = f.run('setColumn()');
  f.posts[0].resolve({ok:true,revision:'csv-2'}); await tick();
  assert.equal(f.gets.length,1);
  f.rows[1].children[2].textContent = 'new draft'; f.run('markCsvDirty()');
  f.gets[0].resolve({path:'a.csv',header_rows:[['Cell ID','CalcRadius','Comment']],header_lines:1,
    rows:[['c1','200','old comment']],editable:true,revision:'csv-2',format_revision:'format-1'});
  await pending;
  assert.equal(f.c.S.csvDirty,true);
  assert.equal(f.rows[1].children[2].textContent,'new draft');
  assert.notEqual(f.run('csvData.revision'),'csv-2',
    'The displayed grid still contains radius 100; using csv-2 would allow a later full save to undo radius 200.');
});

test('radius summary tracks the committed CSV snapshot when a newer draft is typed during save',async()=>{
  const f = fixture();
  f.rows[1].children[1].textContent = '200'; f.run('markCsvDirty()');
  const pending = f.run('saveCsv()');
  assert.equal(f.posts[0].body.rows[0][1],'200');
  f.rows[1].children[1].textContent = '300'; f.run('markCsvDirty()');
  f.posts[0].resolve({ok:true,revision:'csv-2'}); await pending;
  assert.equal(f.c.S.csvDirty,true);
  assert.equal(f.rows[1].children[1].textContent,'300');
  assert.equal(f.c.S.paramsData.param_sources.DefaultCalcRadius.revision,'csv-2');
  assert.deepEqual(JSON.parse(JSON.stringify(f.c.S.paramsData.param_sources.DefaultCalcRadius.values)),['200']);
});

test('saving the table does not silently rebase an older unsaved radius draft',async()=>{
  const f = fixture(), input = f.el('radius');
  input.dataset = {tag:'DefaultCalcRadius'}; input.value = '120'; f.c.radius = input;
  f.run('markParamDirty(radius)');
  f.rows[1].children[1].textContent = '200'; f.run('markCsvDirty()');
  const pending = f.run('saveCsv()');
  f.posts[0].resolve({ok:true,revision:'csv-2'}); await pending;
  assert.equal(f.c.S.xmlDirty,true);
  assert.equal(input.value,'120');
  assert.equal(f.c.S.paramsData.param_sources.DefaultCalcRadius.revision,'csv-1',
    'The radius draft was created from csv-1; accepting csv-2 here would let that older draft overwrite the newly saved table.');
  const retry = f.run('savePendingParameters()');
  assert.equal(f.posts[1].body.source_revision,'csv-1');
  f.posts[1].resolve({ok:false,code:'FILE_CONFLICT',message:'文件已修改'}); await retry;
  assert.equal(f.c.S.xmlDirty,true);
  assert.equal(input.value,'120');
});

test('an older parameter load cannot roll back the baseline after a parameter save completes',async()=>{
  const f = fixture(), input = f.el('alpha');
  input.dataset = {tag:'Alpha'}; input.value = '2'; f.c.alpha = input;
  f.c.FUNC_INFO = {};
  const loading = f.run('loadParams()');
  const saving = f.run('saveParameter(alpha,S.job)');
  f.posts[0].resolve({ok:true,revision:'xml-2',target:'schema'}); await saving;
  assert.equal(f.c.S.xmlDirty,false);
  assert.equal(f.c.S.paramsData.revision,'xml-2');
  f.gets[0].resolve({revision:'xml-1',values:{Alpha:'1'},groups:[],function:'pred'}); await loading;
  assert.equal(f.c.S.paramsData.revision,'xml-2');
  assert.equal(f.c.S.paramsData.values.Alpha,'2');
});

test('a CSV load started before a radius save cannot restore the old table afterward',async()=>{
  const f = fixture(), input = f.el('radius');
  input.dataset = {tag:'DefaultCalcRadius'}; input.value = '200'; f.c.radius = input;
  const loading = f.run('loadCsv()');
  const saving = f.run('saveParameter(radius,S.job)');
  f.posts[0].resolve({ok:true,revision:'xml-1',source_revision:'csv-2',target:'engineering_csv'}); await saving;
  assert.equal(f.run('csvData'),null);
  f.gets[0].resolve({path:'a.csv',header_rows:[['Cell ID','CalcRadius','Comment']],header_lines:1,
    rows:[['c1','100','old comment']],editable:true,revision:'csv-1',format_revision:'format-1'});
  await loading;
  assert.equal(f.run('csvData'),null,
    'The old GET was sent before the radius save; the user must load the newly written CSV instead.');
});
