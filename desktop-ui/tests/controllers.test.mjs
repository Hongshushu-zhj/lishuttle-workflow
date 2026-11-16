import test from 'node:test';
import assert from 'node:assert/strict';
import { Scope, EditorLedger, LogSession, PreviewGate, Workflow } from '../src/domain/controllers.ts';

test('responses from prior projects and earlier reads never apply', () => {
  const scope=new Scope(); scope.update('C:/engine-a','r1','m1');
  const old=scope.read('params'); const newer=scope.read('params');
  assert.equal(scope.current(old),false); assert.equal(scope.current(newer),true);
  scope.update('C:/engine-b','r2','m1'); assert.equal(scope.current(newer),false);
});
test('revision changes invalidate reads and request context carries all three guards',()=>{
  const scope=new Scope(); scope.update('C:/a','r1','m1'); const read=scope.read('csv');
  scope.update('C:/a','r2','m1'); assert.equal(scope.current(read),false);
  assert.deepEqual(scope.context(),{_project:'C:/a',_revision:'r2',_machine_revision:'m1'});
});
test('save completion clears only the exact submitted editor draft',()=>{
  const editor=new EditorLedger(); editor.edit('A','one'); const sent=editor.capture('A');
  editor.edit('A','two'); editor.saved(sent); assert.equal(editor.dirty,true); assert.equal(editor.value('A'),'two');
  editor.saved(editor.capture('A')); assert.equal(editor.dirty,false);
});
test('failed save preserves drafts and CSV is dirty until explicit save',()=>{
  const xml=new EditorLedger(); xml.edit('x','v'); assert.equal(xml.dirty,true);
  const csv=new EditorLedger(); csv.edit('0:1','23'); assert.equal(csv.dirty,true); csv.discard(); assert.equal(csv.dirty,false);
});
test('log pagination is pinned to sid and rejects a previous attachment',()=>{
  const log=new LogSession(); const old=log.attach(71); const now=log.attach(92);
  assert.equal(log.accept(old,{lines:['wrong'],next_since:1}),false);
  assert.equal(log.accept(now,{lines:['right'],next_since:1,has_more:false}),true);
  assert.equal(log.sid,92); assert.deepEqual(log.lines,['right']); assert.equal(log.cursor,1);
});
test('log cursor never advances on an invalid page',()=>{
  const log=new LogSession(); const token=log.attach(8); log.accept(token,{lines:['a'],next_since:1});
  assert.throws(()=>log.accept(token,{lines:[],next_since:1,has_more:true}),/游标/); assert.equal(log.cursor,1);
});
test('assembly preview tokens expire on any selected input change',()=>{
  const gate=new PreviewGate(); gate.set({mode:'adapt',source:'a'},'t1',{});
  assert.equal(gate.valid({mode:'adapt',source:'a'}),true);
  assert.equal(gate.valid({mode:'adapt',source:'b'}),false);
});
test('three XML modes retain distinct semantics and edits invalidate preflight',()=>{
  const flow=new Workflow(); flow.update({mode:'existing',schema:'x.xml'}); flow.assembled(); flow.checked({ok:true});
  assert.equal(flow.canRun,true); flow.contentChanged(); assert.equal(flow.canRun,false);
  flow.update({mode:'import',schema:'x.xml'}); assert.equal(flow.assemblyCurrent,false);
  flow.update({mode:'adapt',schema:'x.xml'}); assert.equal(flow.assemblyCurrent,false);
});
test('historical success with changed or missing current files is warning',async()=>{const {resultPresentation}=await import('../src/domain/controllers.ts');assert.equal(resultPresentation({historical:true,verdict:'success',current_files:{status:'changed'}}).type,'warning');assert.match(resultPresentation({historical:true,verdict:'success',current_files:{status:'missing'}}).label,/当时成功.*缺失/);assert.equal(resultPresentation({associated:true,verdict:'success'}).type,'success');});
test('ordinary refresh preserves edited configuration fields including intentional blanks',async()=>{const {rebaseDraft}=await import('../src/domain/controllers.ts');assert.deepEqual(rebaseDraft({MAP_ROOT:'old',CMAKE:'cmake-a',OUT_ROOT:'output-a'},{MAP_ROOT:'draft',CMAKE:'cmake-a',OUT_ROOT:''},{MAP_ROOT:'external',CMAKE:'cmake-b',OUT_ROOT:'output-b'}),{MAP_ROOT:'draft',CMAKE:'cmake-b',OUT_ROOT:''});});
test('bounded log follow key changes after 3000 entries without relying on display length',async()=>{const {logFollowKey}=await import('../src/domain/controllers.ts');const log=new LogSession();const generation=log.attach(8);log.accept(generation,{lines:Array.from({length:3000},(_,n)=>String(n)),next_since:3000});const before=logFollowKey(log);log.accept(generation,{lines:['next'],next_since:3001});assert.equal(log.lines.length,3000);assert.notDeepEqual(logFollowKey(log),before);});
test('remembered log height leaves working space in a short viewport',async()=>{const {clampLogHeight}=await import('../src/domain/controllers.ts');assert.ok(clampLogHeight(600,384)<=134);assert.ok(clampLogHeight(600,768)<=518);assert.ok(clampLogHeight(50,384)>=80);});
