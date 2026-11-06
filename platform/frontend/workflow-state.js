(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.WorkflowState = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // Snapshots contain JSON data only. View and runtime session state belong elsewhere.
  function canonical(value) {
    if (Array.isArray(value)) return value.map(canonical);
    if (value && typeof value === 'object') {
      const result = {};
      Object.keys(value).sort().forEach(function (key) {
        if (value[key] !== undefined) result[key] = canonical(value[key]);
      });
      return result;
    }
    return value;
  }
  function snapshot(value) { return canonical(JSON.parse(JSON.stringify(value || {}))); }
  function fingerprint(value) { return JSON.stringify(snapshot(value)); }
  function create(input) {
    const draft = snapshot(input);
    return {snapshot: draft, fingerprint: fingerprint(draft), revision: 0,
      contentRevision: 0, assembled: null, preflight: null, staleReason: ''};
  }
  function update(state, input, reason) {
    const draft = snapshot(input);
    const key = fingerprint(draft);
    if (key === state.fingerprint) return state;
    return Object.assign({}, state, {snapshot: draft, fingerprint: key,
      revision: state.revision + 1, staleReason: reason || '输入或项目配置已改变，请重新装配'});
  }
  function markAssembled(state, context) {
    return Object.assign({}, state, {assembled: {snapshot: snapshot(state.snapshot),
      fingerprint: state.fingerprint, revision: state.revision, context: snapshot(context)},
      preflight: null, staleReason: ''});
  }
  function contentChanged(state, reason) {
    return Object.assign({}, state, {contentRevision: state.contentRevision + 1,
      staleReason: reason || '参数内容已保存，请重新检查'});
  }
  function markPreflight(state, report) {
    return Object.assign({}, state, {preflight: {revision: state.revision,
      contentRevision: state.contentRevision, fingerprint: state.fingerprint,
      report: snapshot(report)}});
  }
  function availability(reason) { return {disabled: !!reason, reason: reason || ''}; }
  function getStatus(state, facts) {
    facts = facts || {};
    const project = facts.project || {}, build = facts.build || {}, inputs = facts.inputs || {};
    const pending = facts.pending || {}, runtime = facts.runtime || {};
    const assembled = state.assembled;
    const assemblyCurrent = !!assembled && assembled.fingerprint === state.fingerprint;
    const preflightCurrent = assemblyCurrent && !!state.preflight &&
      state.preflight.revision === state.revision &&
      state.preflight.contentRevision === state.contentRevision &&
      state.preflight.fingerprint === state.fingerprint;
    const checked = preflightCurrent && state.preflight.report.ok === true;
    const busy = runtime.busy ? (runtime.reason || '当前操作进行中，请等待完成') : '';
    const dirty = pending.csvDirty || pending.xmlDirty ? '请先保存或放弃未保存的参数编辑' : '';
    const projectReason = project.ready ? '' : (project.reason || '请先保存项目配置');
    const buildReason = build.ready ? '' : (build.reason || '请先应用程序目录与构建选择');
    const selectionReady = build.selectionReady === undefined ? build.ready : build.selectionReady;
    const selectionReason = selectionReady ? '' : (build.selectionReason || buildReason || '请选择有效构建目标');
    const inputReason = inputs.ready ? '' : (inputs.reason || '请先补全任务输入');
    const assemblyReason = assemblyCurrent ? '' : (state.staleReason || '请先装配当前配置');
    const executableReason = build.executableReady ? '' : (build.executableReason || '未找到匹配的可执行程序');
    const checkReason = checked ? '' : (preflightCurrent ? '运行前检查未通过' : '请重新进行运行前检查');
    const actions = {
      saveProject: availability(busy || pending.saveProjectReason),
      compile: availability(busy || projectReason || selectionReason ||
        (build.compilerReady ? '' : (build.compilerReason || '请先配置编译工具'))),
      assemble: availability(busy || dirty || projectReason || buildReason || inputReason || pending.assembleReason),
      preflight: availability(busy || dirty || projectReason || buildReason || inputReason || assemblyReason || pending.preflightReason),
      run: availability(busy || dirty || projectReason || buildReason || inputReason || assemblyReason || executableReason || checkReason || pending.runReason),
      cancel: availability(runtime.busy && runtime.cancellable ? '' : '当前没有可取消的操作')
    };
    function stage(id, title, status, reason) { return {id: id, title: title, status: status, reason: reason || ''}; }
    const stages = [
      stage('project', '项目与环境', project.ready ? 'complete' : 'pending', projectReason),
      stage('build', '程序准备', build.ready && build.executableReady ? 'complete' : 'pending', buildReason || executableReason),
      stage('inputs', '任务与输入', inputs.ready ? 'complete' : 'pending', inputReason),
      stage('assembly', '装配与确认', assemblyCurrent ? 'complete' : assembled ? 'stale' : 'pending', assemblyReason),
      stage('check', '参数与运行前检查', checked ? 'complete' : preflightCurrent ? 'failed' : state.preflight ? 'stale' : 'pending', checkReason),
      stage('run', '运行与结果', runtime.busy && runtime.stage === 'run' ? 'active' : runtime.failed ? 'failed' : runtime.completed ? 'complete' : actions.run.disabled ? 'pending' : 'ready', actions.run.reason)
    ];
    // Callers supply operation identity from the backend; never infer it from a draft.
    if (runtime.busy && runtime.stage) {
      stages.forEach(function (item) { if (item.id === runtime.stage) { item.status = 'active'; item.reason = busy; } });
    }
    return {assemblyCurrent: assemblyCurrent, preflightCurrent: preflightCurrent,
      preflightPassed: checked, actions: actions, stages: stages};
  }
  return {create: create, update: update, markAssembled: markAssembled,
    markPreflight: markPreflight, contentChanged: contentChanged,
    getStatus: getStatus, fingerprint: fingerprint};
}));
