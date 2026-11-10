/* lishuttle 本地平台前端（原生 JS，无依赖） */
"use strict";

const $ = (id) => document.getElementById(id);
const S = {  // 全局状态
  cities: [], tasks: [], functions: [],
  city: null,          // {name, kind}
  task: null,          // 任务对象
  func: "pred",
  job: null,           // {name, schema, func, taskId}
  sid: 0, since: 0, pollTimer: null,
  resultSid: 0, resultContext: null, runtime: {busy:false}, launchPending: false,
};

function workflowSnapshot() {
  const config = Object.fromEntries(Object.entries(S.projectConfig || {}).filter(([key]) => !MACHINE_KEYS.includes(key)));
  const draft = Object.fromEntries(Object.entries(S.projectDraft || {}).filter(([key]) => !MACHINE_KEYS.includes(key)));
  if (S.job?.mode === 'existing') return {project:S.project,config,draft,mode:'existing',
    scope:S.runtimeCatalog?.scope,schema:S.job.schema,func:S.func,name:S.job.name,taskId:$('task-id').value || '1'};
  return {project:S.project, config, draft, func:S.func, city:S.city?.name || '',
    task:S.task?.dir || S.task?.name || '', csv:S.task?.engineering_file || '',
    name:$('job-name').value.trim(), taskId:$('task-id').value || '1',
    schema:$('schema-source').value, polygon:$('schema-polygon').value,
    reuse:$('use-existing-schema').checked, sync:$('sync-engineering').checked,
    copy:$('copy-files').checked, antennas:$('copy-antennas').checked, paths:collectLocalPaths()};
}
function syncWorkflow(reason) {
  const snapshot = workflowSnapshot();
  S.workflow = S.workflow ? WorkflowState.update(S.workflow, snapshot, reason) : WorkflowState.create(snapshot);
  return S.workflow;
}
function markWorkflowAssembled(job) {
  S.assemblyUnconfirmed=false;
  S.workflow = WorkflowState.markAssembled(syncWorkflow(), job);
  refreshWorkflow();
}
function markWorkflowPreflight(report) {
  S.workflow = WorkflowState.markPreflight(syncWorkflow(), report);
  refreshWorkflow();
}
function workflowContentChanged(reason) {
  S.workflow = WorkflowState.contentChanged(syncWorkflow(), reason);
  refreshWorkflow();
}
function workflowStatus() {
  const applied = !BUILD_KEYS.some(key => (S.projectDraft?.[key] || '') !== (S.projectConfig?.[key] || ''));
  const reuse = $('use-existing-schema').checked;
  const existing = S.job?.mode === 'existing';
  const inputsReady = existing || (!!S.city && !!S.task && !!$('job-name').value.trim() &&
    (!reuse || !!$('schema-source').value) && ((reuse && !$('sync-engineering').checked) || !!S.task?.engineering_file));
  const status = WorkflowState.getStatus(syncWorkflow(), {
    project:{ready:!!S.project},
    build:{ready:applied && !!S.buildWorkflow?.built, executableReady:applied && !!S.buildWorkflow?.built,
      selectionReady:!!S.projectDraft?.PRESET && !!S.projectDraft?.BUILD_SUBDIR,
      compilerReady:['CMAKE','NINJA','VCVARS'].every(key=>!!S.projectConfig?.[key]),
      reason:!applied ? '构建选择已改变，请编译或使用已识别程序' : '请先准备匹配的程序'},
    inputs:{ready:inputsReady, reason:'请选择功能、地图、任务及所需输入，并填写任务名'},
    pending:{csvDirty:S.csvDirty, xmlDirty:S.xmlDirty,
      assembleReason:schemaSubmissionPending || S.assemblyPending ? '正在装配，请稍候' : '',
      preflightReason:S.preflightPending || S.parameterWrites || S.runtimeExecutionPending ? '正在检查或保存选择，请稍候' : '',
      runReason:S.launchPending || S.parameterWrites || S.runtimeExecutionPending ? '正在提交运行或保存选择，请稍候' : ''},
    runtime:{busy:!!S.runtime?.busy || !!S.pollTimer || !!S.inputTransition,
      cancellable:!S.runtime?.external && !!S.runtime?.sid && ['running','preparing','cancelling'].includes(S.runtime?.phase),
      stage:S.runtime?.operation === 'build' || /build|编译/.test(S.runtime?.label || '') ? 'build' : S.runtime?.func ? 'run' : '',
      completed:S.runFingerprint === S.workflow?.fingerprint && S.runVerdict === 'success', failed:S.runFingerprint === S.workflow?.fingerprint && ['failed','cancelled'].includes(S.runVerdict)}
  });
  if (existing || (S.runtimeCatalog && S.runtimeConfigMode !== 'new')) status.actions.assemble = {
    disabled:true,reason:'已有 XML 可直接编辑和检查；新建配置请切换到“从样例新建／从任务包适配”'};
  return status;
}
function refreshWorkflow() {
  const status = workflowStatus();
  const names = {pending:'待准备',ready:'可执行',active:'进行中',complete:'已就绪',stale:'需更新',failed:'需处理'};
  const navigation=status.stages.map((stage,index)=>`<button type="button" data-workflow-stage="${stage.id}" class="workflow-link ${stage.status}"><span>${String(index+1).padStart(2,'0')} · ${stage.title}</span><small>${names[stage.status]}</small></button>`).join('');
  if($('workflow-nav').innerHTML !== navigation) $('workflow-nav').innerHTML=navigation;
  $('workflow-nav').querySelectorAll('[data-workflow-stage]').forEach(button=>button.onclick=()=>focusStage(button.dataset.workflowStage));
  status.stages.forEach(stage=>{
    const node=$('stage-'+stage.id+'-status'); node.textContent=names[stage.status]; node.title=stage.reason;
    node.className='stage-status '+stage.status;
  });
  const buttons={compile:'btn-build',assemble:'btn-render',preflight:'btn-preflight',run:'btn-run',cancel:'btn-stop'};
  Object.entries(buttons).forEach(([key,id])=>{ const node=$(id), action=status.actions[key]; node.disabled=action.disabled; node.title=action.reason; });
  [['build','compile'],['assembly','assemble'],['check','preflight'],['run','run']].forEach(([id,key])=>{
    $(''+id+'-action-reason').textContent=(id === 'build' && selectedBuildStatus()?.built && !S.runtime?.busy ? '可直接使用已识别程序。' : '') + (status.actions[key].reason || ({build:'可编译所选配置，或继续使用匹配的已有程序',assembly:'输入已准备，可以装配',check:'可以检查当前配置',run:'本次检查通过，可以启动'})[id]);
  });
  refreshSchemaApplyState();
  $('btn-use-executable').disabled=!!S.inputTransition || !!S.runtime?.busy || !!S.pollTimer || !!S.csvDirty || !!S.xmlDirty || !selectedBuildStatus()?.built;
  if (typeof refreshIndoorBuildingButtons === 'function') refreshIndoorBuildingButtons();
  ['btn-params-save','btn-params-discard'].forEach(id=>{
    $(id).classList[S.xmlDirty ? 'remove' : 'add']('hidden');
    $(id).disabled=!!S.inputTransition || !!S.parameterWrites || !!S.runtime?.busy;
  });
  $('assembly-summary').textContent=!S.job ? '尚未加载或装配运行配置' : status.assemblyCurrent
    ? `${S.job.mode === 'existing' ? '已加载' : '已装配'}：${S.job.schema} · XML name=${S.job.name} · ${S.job.func} · 任务 ${S.job.taskId}`
    : `先前装配：${S.job.schema}；输入已改变，请重新装配`;
  if (S.workflow.preflight && !status.preflightCurrent) $('preflight-report').textContent='检查已过期：'+(S.workflow.staleReason || '输入内容已变化')+'。请重新检查。';
  refreshActiveStage();
  refreshRuntimeConfigActions();
  return status;
}
function refreshActiveStage() {
  $('workflow-nav').querySelectorAll('[data-workflow-stage]').forEach(node=>{
    if(node.dataset.workflowStage === S.activeStage) node.setAttribute('aria-current','step');
    else node.removeAttribute('aria-current');
  });
}
function focusStage(id) {
  const stage=$('stage-'+id); if (!stage) return;
  stage.open=true; S.activeStage=id; refreshActiveStage();
  stage.scrollIntoView?.({behavior:'smooth',block:'start'});
}
function showOperation(title) {
  const panel=$('operation-panel'); panel.open=true;
  if (title) $('operation-title').textContent=title;
  panel.scrollIntoView?.({behavior:'smooth',block:'start'});
}

function toast(msg, ok = true) {
  const el = $("hint");
  el.textContent = msg;
  el.style.background = ok ? "#fffbe6" : "#fee2e2";
  setTimeout(() => { el.style.background = "#fffbe6"; }, 4000);
}

/* ---------------- 初始化 ---------------- */

async function init() {
  const st = await get("state");
  if (st.error) return toast(st.error, false);
  applyProjectState(st);

  $("project").onchange = () => changeProject("select_project", $("project").value);
  $("btn-project-add").onclick = () => {
    const open = $("project-add-form").classList.contains("hidden");
    $("project-add-form").classList.toggle("hidden", !open);
    $("btn-project-add").setAttribute("aria-expanded", String(open));
    if (open) $("project-path").focus();
  };
  $("project-add-form").onsubmit = async event => {
    event.preventDefault();
    await changeProject("add_project", $("project-path").value.trim());
  };
  bindActions();
  initRuntimeConfigs();
  if (S.runtimeRestorePromise) await S.runtimeRestorePromise;
  await initRunHistory();
  globalThis.addEventListener?.('beforeunload',event=>{
    if(S.csvDirty || S.xmlDirty) { event.preventDefault(); event.returnValue=''; }
  });
  await refreshRuntimeState(true);
  S.runtimeTimer = setInterval(() => refreshRuntimeState(true), 1200);
  $("btn-project-config").onclick = () => {
    const open = $("project-config-form").classList.contains("hidden");
    $("project-config-form").classList.toggle("hidden", !open);
    $("btn-project-config").setAttribute("aria-expanded", String(open));
  };
  $("project-config-form").onsubmit = async event => {
    event.preventDefault();
    if (!guardCsvChanges() || S.xmlDirty) return toast('请先保存或放弃未保存的编辑',false);
    if (S.inputTransition || S.parameterWrites || S.pollTimer || S.pendingRequests) return toast('当前操作结束后再修改项目配置', false);
    const values = {};
    $("project-config-fields").querySelectorAll('[data-config-key]').forEach(input => {
      values[input.dataset.configKey] = input.value.trim();
    });
    BUILD_KEYS.forEach(key => { values[key] = S.projectDraft[key] || ''; });
    try {
      await withInputTransition(async () => {
        const st = await post('save_project_config', {values});
        if (st.error) return toast(st.error, false);
        applyProjectState(st, {preserveMachineDraft:true});
        $("project-config-note").textContent = '当前项目配置已保存，任务选择与旧预览已清理。';
        toast('当前项目配置已保存');
      });
    } catch(error) { toast('保存项目配置失败：'+error.message,false); }
  };
  $("btn-project-detect").onclick = () => refreshProjectDetection();
  $("btn-machine-config").onclick = () => {
    const open = $("machine-config-form").classList.contains('hidden');
    $("machine-config-form").classList.toggle('hidden', !open);
    $("btn-machine-config").setAttribute('aria-expanded', String(open));
  };
  $("machine-config-form").onsubmit = event => {
    event.preventDefault();
    const values = {};
    $("machine-config-fields").querySelectorAll('[data-config-key]').forEach(input => {
      values[input.dataset.configKey] = input.value.trim();
    });
    return updateMachineConfig('save_machine_config', {values});
  };
  $("btn-machine-detect").onclick = () => updateMachineConfig('detect_machine_config', {});
}

function bindActions() {
  $("btn-doctor").onclick = () => toolkit("doctor");
  $("btn-use-executable").onclick = useExecutable;
  $("btn-show-operation").onclick = () => showOperation();
  $("btn-csv-discard").onclick = discardCsvChanges;
  $("btn-params-save").onclick=savePendingParameters;
  $("btn-params-discard").onclick=discardParameterChanges;
  $("btn-build").onclick = () => toolkit("build");
  $("btn-rescan-map").onclick = rescanMap;
  $("btn-rescan-task").onclick = rescanTasks;
  $("btn-render").onclick = doRender;
  $("btn-cleanup-preview").onclick = previewCleanup;
  $("btn-run").onclick = doRun;
  $("btn-preflight").onclick = doPreflight;
  $("btn-stop").onclick = stopCurrentOperation;
  $("btn-export-log").onclick = exportRunLog;
  $("btn-csv-load").onclick = loadCsv;
  $("engineering-path").onchange = () => selectEngineering($("engineering-path").value, true);
  $("csv-path").onchange = () => selectEngineering($("csv-path").value, true);
  $("use-existing-schema").onchange = updateSchemaMode;
  $("schema-source").onchange = () => { refreshLocalPaths({}); invalidateSchemaPreview(); restoreTaskBinding(); };
  $("btn-save-task-binding").onclick = saveTaskBinding;
  ["sync-engineering", "schema-polygon", "job-name", "task-id", "copy-antennas", "copy-files"].forEach(id => {
    $(id).addEventListener("change", invalidateSchemaPreview);
    $(id).addEventListener("input", invalidateSchemaPreview);
  });
  ['job-name', 'task-id'].forEach(id => {
    $(id).addEventListener('input', () => S.job?.mode === 'existing'
      ? runtimeExecutionSelectionChanged({persist:false}) : taskIdentityChanged());
    $(id).addEventListener('change', () => S.job?.mode === 'existing'
      ? runtimeExecutionSelectionChanged() : taskIdentityChanged());
  });
  $("btn-csv-save").onclick = saveCsv;
  $("btn-csv-col").onclick = setColumn;
  $("btn-results").onclick = loadResults;
  $("btn-open-dir").onclick = () => post("open_folder", { path: lastResultsDir || "" });
  document.querySelectorAll(".tabs button").forEach(b => b.onclick = () => switchTab(b));
}

function switchTab(btn) {
  const name=btn?.dataset?.tab;
  focusStage(({params:'check',csv:'inputs',run:'run',results:'run'})[name] || 'inputs');
  if (name === 'csv') $('csv-editor').open=true;
}

function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;"); }

/* ---------------- 运行与工具链 ---------------- */

init();
