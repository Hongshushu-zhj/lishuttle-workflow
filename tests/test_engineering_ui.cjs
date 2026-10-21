// Exercise selection, editor synchronization and render payload with a minimal DOM.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');

const nodes = new Map();
function element(id) {
  const classes = new Set();
  if (!nodes.has(id)) nodes.set(id, {
    value: '', textContent: '', innerHTML: '', checked: false, disabled: false, options: [], style: {},
    classList: {
      add(c) { classes.add(c); }, remove(c) { classes.delete(c); },
      toggle(c, on) { if (on) classes.add(c); else classes.delete(c); },
      contains(c) { return classes.has(c); },
    },
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
    engineering_kinds: { '/task/a.csv': 'outdoor', '/task/b.csv': 'indoor' },
    schema_candidates: [{path:'/task/schema.xml', name:'old-name', kind:'indoor'}], txts: ['/task/area.txt'],
    has_antennas: true, antenna_dir: '/task/antenna' };
  renderTasks([task]);
`, context);

(async () => {
  await taskNode.onclick();
  assert.equal(element('antenna-option').classList.contains('hidden'), false);
  assert.equal(element('copy-antennas').disabled, false);
  assert.equal(element('copy-antennas').checked, true);
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
  assert.equal(element('schema-source').value, '/task/schema.xml');
  element('use-existing-schema').checked = true;
  element('copy-antennas').checked = true;
  vm.runInContext('updateSchemaMode()', context);
  assert.equal(element('copy-files').disabled, true);
  assert.equal(element('copy-antennas').disabled, false);
  const urls = [];
  context.fetch = async (url, options) => {
    urls.push(url);
    context.request = JSON.parse(options.body);
    return { json: async () => url.endsWith('preview_render')
      ? {source:'/task/schema.xml', destination:'/bin/job.xml', runtime_name:'old-name', out_dir:'/outputs/old-name',
         changes:[{tag:'MapPath',old:'old-map',new:'new-map'}], warnings:[], token:'preview-token'}
      : {error:'test response'} };
  };
  await vm.runInContext('doRender()', context);
  assert.deepEqual(urls, ['/api/preview_render']);
  assert.equal(context.request.copy_files, false);
  assert.equal('max_calc_height' in context.request, false);
  assert.equal('floor_height' in context.request, false);
  assert.equal(context.request.copy_antennas, true);
  assert.equal(context.request.sync_engineering, false);
  assert.match(element('schema-preview-text').textContent, /old-name/);
  await element('btn-apply-schema').onclick();
  assert.deepEqual(urls, ['/api/preview_render', '/api/render']);
  assert.equal(context.request.preview_token, 'preview-token');
  assert.equal(context.request.copy_antennas, true);
  vm.runInContext('task.has_antennas = false; renderTasks([task]);', context);
  await taskNode.onclick();
  assert.equal(element('antenna-option').classList.contains('hidden'), true);
  assert.equal(element('copy-antennas').disabled, true);
  assert.equal(element('copy-antennas').checked, false);
  vm.runInContext('renderTasks([])', context);
  assert.equal(element('engineering-path').disabled, true);
  assert.equal(element('csv-path').value, '');
  console.log('PASS: engineering sync, existing XML selection, preview before copy, token, height/resource protection, rescan reset');
})().catch(err => { console.error(err); process.exitCode = 1; });
