// Exercise selection, editor synchronization and render payload with a minimal DOM.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');

const nodes = new Map();
function element(id) {
  if (!nodes.has(id)) nodes.set(id, {
    value: '', textContent: '', innerHTML: '', disabled: false, options: [], style: {},
    classList: { add() {}, remove() {} },
    replaceChildren(...options) { this.options = options; this.value = options[0]?.value || ''; },
    add(option) { this.options.push(option); },
  });
  return nodes.get(id);
}
const taskNode = { dataset: { name: 'task' }, classList: { add() {}, remove() {} } };
const context = vm.createContext({
  document: { getElementById: element, querySelectorAll: () => [taskNode] },
  Option: function (text, value) { this.text = text; this.value = value; },
  setTimeout() {},
});
const source = fs.readFileSync(path.join(__dirname, '../platform/frontend/app.js'), 'utf8');
vm.runInContext(source.replace(/init\(\);\s*$/, ''), context);
vm.runInContext(`
  const task = { name: 'task', dir: '/task', engineering_candidates: ['/task/a.csv', '/task/b.csv'],
    engineering_file: '', engineering_reason: '存在多个工参候选，请手动选择',
    engineering_kinds: { '/task/a.csv': 'outdoor', '/task/b.csv': 'indoor' } };
  renderTasks([task]);
`, context);

(async () => {
  await taskNode.onclick();
  assert.equal(element('engineering-path').value, '');
  assert.equal(element('csv-path').value, '');
  assert.equal(element('engineering-path').options.length, 3);
  vm.runInContext(`csvData = {path: '/task/a.csv'}; selectEngineering('/task/b.csv', true);`, context);
  assert.equal(element('engineering-path').value, '/task/b.csv');
  assert.equal(element('csv-path').value, '/task/b.csv');
  assert.equal(vm.runInContext('csvData', context), null);
  assert.equal(vm.runInContext('S.task.kind', context), 'indoor');
  element('job-name').value = 'job';
  vm.runInContext(`S.city = {name:'city', kind:'indoor'};`, context);
  context.fetch = async (url, options) => {
    context.request = JSON.parse(options.body);
    return { json: async () => ({error: 'test response'}) };
  };
  await vm.runInContext('doRender()', context);
  assert.equal(context.request.engineering_file, '/task/b.csv');
  vm.runInContext('renderTasks([])', context);
  assert.equal(element('engineering-path').disabled, true);
  assert.equal(element('csv-path').value, '');
  console.log('PASS: ambiguous selection, editor sync, classification, render payload, rescan reset');
})().catch(err => { console.error(err); process.exitCode = 1; });
