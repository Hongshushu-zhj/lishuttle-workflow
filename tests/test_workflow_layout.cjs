const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../platform/frontend/index.html'), 'utf8');
// Small structural HTML walk: containment matters, not whitespace or exact copy.
const nodes = [], stack = [];
for (const match of html.matchAll(/<\/?([a-z][\w-]*)\b([^>]*)>/gi)) {
  const [tag, name, attrs] = match;
  if (tag.startsWith('</')) { while (stack.length && stack.pop().name !== name) {} continue; }
  const id = attrs.match(/\bid="([^"]+)"/)?.[1];
  const node = { name, id, attrs, parents: stack.slice() }; nodes.push(node);
  if (!/^(?:area|base|br|col|embed|hr|img|input|link|meta|param|source|track|wbr)$/.test(name)) stack.push(node);
}
const ids = nodes.filter(n => n.id).map(n => n.id);
assert.equal(ids.length, new Set(ids).size, 'Every control ID must be unique');
const get = id => { const n = nodes.find(n => n.id === id); assert.ok(n, `Missing ${id}`); return n; };
const inside = (id, parent) => assert.ok(get(id).parents.includes(get(parent)), `${id} belongs in ${parent}`);
const stages = nodes.filter(n => /\bclass="[^"]*\bworkflow-stage\b/.test(n.attrs));
assert.deepEqual(stages.map(n => n.id), ['stage-project','stage-build','stage-inputs','stage-assembly','stage-check','stage-run']);
for (const stage of stages) { assert.equal(stage.name, 'details'); assert.ok(nodes.some(n => n.name === 'summary' && n.parents.at(-1) === stage), `${stage.id} has a native summary`); }
get('workflow-nav');
for (const id of ['project','env-note','current-project-path','btn-project-add','btn-project-config']) inside(id, 'stage-project');
assert.ok(!get('project').parents.some(n => n.name === 'header'), 'Project selection stays beside project settings');
for (const stage of stages) {
  const summary = nodes.find(n => n.name === 'summary' && n.parents.at(-1) === stage);
  const toggle = nodes.find(n => /\bclass="stage-toggle"/.test(n.attrs) && n.parents.at(-1) === summary);
  assert.ok(toggle, `${stage.id} has a visible expand/collapse control in its native summary`);
  for (const state of ['expand', 'collapse']) {
    assert.ok(nodes.some(n => new RegExp(`\\bclass="stage-toggle-${state}"`).test(n.attrs) && n.parents.includes(toggle)), `${stage.id} labels ${state}`);
  }
  assert.ok(!nodes.some(n => n.name === 'button' && n.parents.includes(summary)), 'Keep one native keyboard toggle without nested buttons');
}
assert.match(html, /id="build-help"[^>]*>[\s\S]*?增量编译/);
for (const id of ['build-mode','build-preset','btn-build','btn-doctor','btn-use-executable']) inside(id, 'stage-build');
for (const id of ['city-list','task-list','map-root','gongcan-root','job-name','task-id','func-radios','engineering-path','schema-source','csv-editor']) inside(id, 'stage-inputs');
for (const id of ['schema-preview','btn-apply-schema','assembly-summary','schema-apply-status']) inside(id, 'stage-assembly');
for (const id of ['params-area','btn-preflight','preflight-report']) inside(id, 'stage-check');
for (const id of ['btn-run','result-files']) inside(id, 'stage-run');
for (const id of ['run-console','btn-stop','btn-export-log']) { inside(id, 'operation-panel'); assert.ok(!get(id).parents.some(n => stages.includes(n)), `${id} remains accessible outside stages`); }
assert.match(get('schema-apply-status').attrs, /role="status"/);
assert.match(html, /<script src="app.js"><\/script>/);
console.log('workflow layout: six ordered stages, unique controls, shared operation panel passed');
