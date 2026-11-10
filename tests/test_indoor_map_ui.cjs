const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

const MAP_ROOT='D:/fixture/maps', SCENE='test-indoor-map';
const MAP_PATH=`${MAP_ROOT}/${SCENE}`, DAS_PATH=`${MAP_PATH}/test-indoor.das`;

function fixture() {
  const nodes=new Map(),calls=[];
  const el=id=>{
    if(!nodes.has(id)) nodes.set(id,{value:'',checked:false,disabled:false,innerHTML:'',textContent:'',style:{},dataset:{},
      classList:{add(){},remove(){},toggle(){},contains(){return false;}},
      setAttribute(){},removeAttribute(){},addEventListener(){},querySelectorAll(){return [];},scrollIntoView(){}});
    return nodes.get(id);
  };
  const city={dataset:{name:SCENE},classList:{add(){},remove(){}}};
  const radios=['pred','predindoor'].map(value=>({value}));
  const ctx=vm.createContext({console,document:{getElementById:el,
    querySelector(selector){return selector === '[data-tab="params"]' ? {dataset:{tab:'params'}} : null;},
    querySelectorAll(selector){return selector === '#city-list .city' ? [city]
      : selector === '#func-radios input' ? radios : [];}},setTimeout(){}});
  vm.runInContext(require('./frontend_source.cjs')(),ctx);
  const run=source=>vm.runInContext(source,ctx);
  run(`S.project='D:/fixture/project';S.profileId='fixture';S.profileRevision='1';S.projectEpoch=1;
    S.projectConfig={PRESET:'release',BUILD_SUBDIR:'build/release',MAP_ROOT:'D:/old/maps'};
    S.projectDraft={...S.projectConfig};S.buildWorkflow={built:true};S.functions=['pred','predindoor'];
    S.task={name:'indoor-task',kind:'indoor',dir:'D:/fixture/tasks',engineering_file:'D:/fixture/tasks/indoor.csv',
      schema_candidates:[{path:'D:/fixture/tasks/indoor.xml',path_values:{MapPath:'X:/old/map'}}]};
    S.city={name:'old',kind:'outdoor'};renderProjectConfig=()=>{};loadParams=async()=>{};
    renderFuncRadios('pred');$('schema-source').value='D:/fixture/tasks/indoor.xml';
    $('job-name').value='indoor-ui-fixture';$('task-id').value='1';`);
  el('map-root').value=MAP_ROOT;
  ctx.fetch=async(url,options={})=>{
    const body=options.body ? JSON.parse(options.body) : {};
    calls.push({url,body});
    const response=url.endsWith('/set_map_root')
      ? {map_root:MAP_ROOT,cities:[{name:SCENE,kind:'indoor',checks:[['test-indoor.das',DAS_PATH,true]]}],profile_revision:'2'}
      : url.endsWith('/local_paths') ? {values:{MapPath:MAP_PATH,PathlossDirectory:'D:/fixture/output'},warnings:[],unresolved:{}}
      : url.endsWith('/validate_setup') ? {ok:true,issues:[]}
      : url.endsWith('/preview_render') ? {source:'D:/fixture/tasks/indoor.xml',destination:'D:/fixture/project/Bin/indoor-ui-fixture.xml',
          runtime_name:'indoor-ui-fixture',out_dir:'D:/fixture/output/indoor-ui-fixture',token:'indoor-ui-token',warnings:[],
          changes:[{tag:'MapPath',old:'X:/old/map',new:MAP_PATH}]}
      : url.endsWith('/render') ? {schema_ok:true,generated:true,render_status:'ready',schema_name:'indoor-ui-fixture.xml',
          runtime_name:'indoor-ui-fixture',func:body.func,task_id:body.task_id,copied:[],render_output:'fixture only'}
      : {error:'Unexpected fixture endpoint '+url};
    return {json:async()=>response};
  };
  const select=async()=>{
    await run('rescanMap()');
    city.onclick();
    await new Promise(setImmediate);
  };
  return {ctx,run,el,city,calls,select};
}

test('扫描返回任意DAS文件名的室内场景时能展示和选择',async()=>{
  const f=fixture();
  await f.run('rescanMap()');
  assert.equal(f.calls[0].body.path,MAP_ROOT);
  assert.equal(f.run('S.city'),null);
  assert.match(f.el('city-list').innerHTML,/室内场景/);
  assert.match(f.el('city-list').innerHTML,/test-indoor-map/);
  assert.doesNotMatch(f.el('city-list').innerHTML,/缺1项/);
  f.city.onclick();
  await new Promise(setImmediate);
  assert.equal(f.run('S.city.name'),SCENE);
  assert.equal(f.run('S.city.kind'),'indoor');
  assert.equal(f.run('S.func'),'predindoor');
  assert.match(f.el('func-radios').innerHTML,/value="predindoor" checked/);
  assert.match(f.el('selection-note').textContent,/室内场景 test-indoor-map/);
});

test('室内场景选择把场景名送至本地路径接口并保留后端MapPath目录',async()=>{
  const f=fixture();await f.select();
  const request=f.calls.find(call=>call.url.endsWith('/local_paths'));
  assert.equal(request.body.city,SCENE);
  assert.equal(request.body.schema_source,'D:/fixture/tasks/indoor.xml');
  assert.equal(f.run('S.projectConfig.MAP_ROOT'),MAP_ROOT);
  assert.equal(f.run('S.localPathDefaults.MapPath'),MAP_PATH);
  assert.match(f.el('local-path-fields').innerHTML,/value="D:\/fixture\/maps\/test-indoor-map"/);
  assert.doesNotMatch(f.el('local-path-fields').innerHTML,/building\.das/);
  assert.deepEqual(JSON.parse(f.run('JSON.stringify(collectLocalPaths())')),{});
});

test('新建室内装配提交predindoor和场景名，不替换DAS文件名或自动覆盖MapPath',async()=>{
  const f=fixture();await f.select();
  await f.run('doRender()');
  const request=f.calls.find(call=>call.url.endsWith('/render'));
  assert.equal(request.body.func,'predindoor');
  assert.equal(request.body.city,SCENE);
  assert.equal(request.body.city_kind,'indoor');
  assert.equal(request.body.engineering_file,'D:/fixture/tasks/indoor.csv');
  assert.equal(request.body.use_existing_schema,false);
  assert.deepEqual(request.body.path_overrides,{});
  assert.equal(f.run('S.job.func'),'predindoor');
});

test('复用XML的室内地图预览和确认保持同一场景及本地路径',async()=>{
  const f=fixture();await f.select();
  f.el('use-existing-schema').checked=true;
  await f.run('doRender()');
  const preview=f.calls.find(call=>call.url.endsWith('/preview_render'));
  assert.equal(preview.body.city,SCENE);
  assert.equal(preview.body.city_kind,'indoor');
  assert.equal(preview.body.func,'predindoor');
  assert.match(f.el('schema-preview-text').textContent,/D:\/fixture\/maps\/test-indoor-map/);
  await f.el('btn-apply-schema').onclick();
  const render=f.calls.find(call=>call.url.endsWith('/render'));
  assert.equal(render.body.city,SCENE);
  assert.equal(render.body.preview_token,'indoor-ui-token');
  assert.equal(render.body.use_existing_schema,true);
  assert.equal(f.run('S.job.func'),'predindoor');
});
