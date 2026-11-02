const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

function fixture() {
  const nodes = new Map();
  const element = id => {
    if (!nodes.has(id)) nodes.set(id, {
      value:'', innerHTML:'', textContent:'', disabled:false, style:{}, dataset:{},
      setAttribute(){}, querySelectorAll(){return [];},
      classList:{add(){},remove(){},toggle(){}},
    });
    return nodes.get(id);
  };
  const protectedIds = ['project', 'btn-project-add', 'btn-run'];
  const context = vm.createContext({console, setTimeout(){}, setInterval(){return 1;}, clearInterval(){},
    document:{getElementById:element, querySelectorAll:selector =>
      selector === '[data-runtime-write]' ? protectedIds.map(element) : []},
  });
  vm.runInContext(fs.readFileSync('platform/frontend/app.js', 'utf8').replace(/init\(\);\s*$/, ''), context);
  const run = code => vm.runInContext(code, context);
  run(`renderCities=cities=>{S.cities=cities}; renderTasks=tasks=>{S.tasks=tasks};
    renderFuncRadios=func=>{S.func=func};
    applyProjectState({project:'/old',projects:['/old','/new'],functions:['pred'],
      cities:[],tasks:[],runtime:{busy:false,phase:'idle'}});`);
  return {context, element, run};
}

const selected = runtime => ({project:'/new',projects:['/old','/new'],functions:['pred'],
  cities:[],tasks:[],runtime});

(async () => {
  // select_project returns Api.state while its own mutation lease is retained.
  const self = fixture();
  self.context.fetch = async () => ({json:async()=>selected({busy:true,phase:'preparing',sid:null,label:'切换项目'})});
  await self.run('changeProject("select_project", "/new")');
  self.run('applyRuntimeState({busy:false,phase:"idle"})');
  assert.equal(self.element('project').disabled, false, '切换结束和空闲确认后项目选择不能永久禁用');
  assert.equal(self.element('btn-project-add').disabled, false, '添加项目也应释放临时禁用');
  assert.equal(self.element('btn-run').disabled, false);
  assert.equal(self.run('S.project'), '/new');
  let switches = 0;
  self.context.fetch = async () => { switches++; return {json:async()=>selected({busy:false,phase:'idle'})}; };
  await self.run('changeProject("select_project", "/new")');
  assert.equal(switches, 1, '空闲后允许继续切换项目');

  const busy = fixture();
  busy.context.fetch = async () => ({json:async()=>({error:'平台正在运行',code:'RUNTIME_BUSY',
    runtime:{busy:true,phase:'running',sid:123,label:'pred'}})});
  await busy.run('changeProject("select_project", "/new")');
  assert.equal(busy.element('project').disabled, true, '被真实运行占用拒绝时不能在finally中提前解锁');
  assert.equal(busy.element('btn-project-add').disabled, true);
  assert.equal(busy.run('S.project'), '/old');
  assert.equal(busy.run('S.sid'), 123, '被运行占用拒绝时仍恢复实际会话供日志和取消使用');
  busy.run('applyRuntimeState({busy:false,phase:"idle"})');
  assert.equal(busy.element('project').disabled, false);
  assert.equal(busy.element('btn-project-add').disabled, false);

  const failed = fixture();
  failed.context.fetch = async () => { throw Error('network unavailable'); };
  await failed.run('changeProject("select_project", "/new")');
  assert.equal(failed.element('project').disabled, false, '请求异常后释放临时禁用');
  assert.equal(failed.element('btn-project-add').disabled, false);
  assert.equal(failed.run('S.project'), '/old');

  const polled = fixture();
  let finishSwitch;
  const response = new Promise(resolve => { finishSwitch = resolve; });
  polled.context.fetch = async () => ({json:async()=>response});
  const pending = polled.run('changeProject("select_project", "/new")');
  polled.run('applyRuntimeState({busy:true,phase:"preparing",sid:null})');
  polled.run('applyRuntimeState({busy:false,phase:"idle"})');
  assert.equal(polled.element('project').disabled, true, '请求尚未完成时仍保留本地临时锁');
  finishSwitch(selected({busy:false,phase:'idle'}));
  await pending;
  assert.equal(polled.element('project').disabled, false, '轮询先到达空闲也不能遗留临时锁');

  const intrinsic = fixture();
  intrinsic.element('btn-run').disabled = true;
  intrinsic.context.fetch = async () => ({json:async()=>selected({busy:true,phase:'preparing',sid:null})});
  await intrinsic.run('changeProject("select_project", "/new")');
  intrinsic.run('applyRuntimeState({busy:false,phase:"idle"})');
  assert.equal(intrinsic.element('btn-run').disabled, true, '其他业务条件禁用的控件不应被项目解锁放开');

  console.log('PASS: project switching releases temporary locks after idle and preserves actual runtime locks');
})().catch(error=>{console.error(error);process.exitCode=1;});
