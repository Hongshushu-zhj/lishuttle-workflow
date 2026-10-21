const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const nodes = new Map();
const element = id => {
  if (!nodes.has(id)) nodes.set(id, {value:'', textContent:'', innerHTML:'', style:{},
    disabled:false, classList:{add(){}, remove(){}}});
  return nodes.get(id);
};
let download, blob, requested;
const context = vm.createContext({
  document:{getElementById:element, body:{appendChild(){}}, createElement(){
    return {click(){download = this.download;}, remove(){}};
  }},
  Blob, URL:{createObjectURL(value){blob=value;return 'blob:log';}, revokeObjectURL(){}},
  setTimeout(){}, setInterval(){return 1;}, clearInterval(){},
});
vm.runInContext(fs.readFileSync('platform/frontend/app.js', 'utf8').replace(/init\(\);\s*$/, ''), context);
const run = code => vm.runInContext(code, context);

(async () => {
  assert.equal(run('typeof exportRunLog'), 'function', '运行页应提供日志导出');
  run('S.project = "D:/engine"; S.projectEpoch = 1;');
  context.fetch = async () => {throw new Error('不应请求无会话日志');};
  await run('exportRunLog()');
  assert.equal(download, undefined);

  run('attachConsole(12, "运行 cali：")');
  assert.equal(element('btn-export-log').disabled, false);
  element('run-console').textContent = '仅显示部分日志';
  context.fetch = async url => {
    requested = url;
    return {json:async()=>({label:'-f cali -t 1 -c task.xml', status:'running', exit:null,
      total:3, lines:['中文日志', '<ERROR> missing input', '末行']})};
  };
  await run('exportRunLog()');
  assert.equal(requested, '/api/output?sid=12&since=0');
  assert.match(download, /^run-log-.*-session-12\.log$/);
  const bytes = Buffer.from(await blob.arrayBuffer());
  assert.deepEqual([...bytes.subarray(0, 3)], [239, 187, 191]);
  const text = bytes.toString('utf8');
  assert.ok(text.includes('-f cali -t 1 -c task.xml'));
  assert.ok(text.includes('中文日志\r\n<ERROR> missing input\r\n末行'));
  assert.ok(text.includes('运行中'));
  assert.equal(element('run-console').textContent, '仅显示部分日志');
  assert.equal(element('btn-export-log').disabled, false);

  context.fetch = async () => ({json:async()=>({label:'build', status:'done', exit:2,
    total:1, lines:['build failed']})});
  await run('exportRunLog()');
  assert.ok((await blob.text()).includes('退出码：2'));

  download = undefined;
  context.fetch = async () => ({json:async()=>({error:'会话不存在'})});
  await run('exportRunLog()');
  assert.equal(download, undefined);
  assert.ok(element('hint').textContent.includes('会话不存在'));

  context.fetch = async () => ({json:async()=>{
    run('S.projectEpoch++; S.sid = 0;');
    return {label:'old', status:'done', exit:0, total:1, lines:['old project']};
  }});
  await run('exportRunLog()');
  assert.equal(download, undefined);
  assert.equal(element('btn-export-log').disabled, true);
  console.log('PASS: exports full session snapshot as UTF-8 log; handles active/completed runs, errors and stale project responses');
})().catch(error => {console.error(error); process.exitCode=1;});
