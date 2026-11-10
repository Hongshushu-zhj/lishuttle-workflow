/* Existing runtime XML is read in place; importing is an explicit separate operation. */
"use strict";

function runtimeConfigGuard({internal = false} = {}) {
  if (!guardCsvChanges() || S.xmlDirty || S.parameterWrites) {
    if (S.xmlDirty) toast('请先保存或放弃未保存的参数编辑', false);
    return false;
  }
  if ((!internal && S.inputTransition) || S.runtime?.busy || S.pollTimer || S.launchPending ||
      S.assemblyPending || schemaSubmissionPending || S.runtimeExecutionPending || (!internal && S.pendingRequests)) {
    toast('当前操作结束后再切换运行配置', false); return false;
  }
  return true;
}

function clearRuntimeEvidence() {
  S.sid = 0; S.since = 0; S.resultSid = 0; S.resultContext = null;
  S.runVerdict = null; S.runFingerprint = null; S.consoleHistorical = false;
  S.consoleAttachment = (S.consoleAttachment || 0) + 1;
  S.resultRequest = (S.resultRequest || 0) + 1;
  if (S.historyPollTimer) clearInterval(S.historyPollTimer);
  S.historyPollTimer = null;
  lastResultsDir = ''; lastArchiveDir = '';
  ['run-console','run-outcome','result-validation','result-log'].forEach(id => $(id).textContent = '');
  $('result-files').innerHTML = '';
  ['run-status','result-status'].forEach(id => $(id).classList.add('hidden'));
  ['btn-export-log','btn-open-dir','btn-open-archive'].forEach(id => $(id).disabled = true);
  $('preflight-report').textContent = '已加载运行 XML；请重新进行运行前检查。启动时还会再次检查。';
}

function resetRuntimeConfigs() {
  S.runtimeListRequest = (S.runtimeListRequest || 0) + 1;
  S.runtimeSelectionRequest = (S.runtimeSelectionRequest || 0) + 1;
  S.runtimeEngineeringRequest = (S.runtimeEngineeringRequest || 0) + 1;
  S.runtimeCatalog = {directory:'',scope:'',configs:[],selected:null};
  S.runtimeRevision = null; S.runtimeInputs = null; S.runtimeConfigMode = 'existing';
  S.runtimeActivationPending = false; S.runtimeExecutionPending = false; S.runtimeExecutionOwner = null; S.runtimeRestoreDeferred = false;
  invalidateRuntimeImport();
  $('runtime-config-select').replaceChildren(new Option('正在读取当前构建运行配置…', ''));
  $('runtime-config-status').textContent = '读取当前 Bin/runtimelibrary；加载配置会保留 XML 中的参数。';
  $('runtime-config-details').textContent = '';
  renderRuntimeConfigMode();
}

function renderRuntimeConfigMode() {
  const mode = S.runtimeConfigMode || 'existing';
  $('runtime-config-mode').value = mode;
  $('runtime-existing-panel').classList.toggle('hidden', mode !== 'existing');
  $('runtime-import-panel').classList.toggle('hidden', mode !== 'import');
  ['task-catalogs','assembly-input-files','assembly-resource-options'].forEach(id => $(id).classList.toggle('hidden', mode !== 'new'));
  $('job-name').readOnly = mode !== 'new';
  if (mode !== 'new' && S.job?.mode === 'existing') $('job-name').value = S.job.name;
  refreshRuntimeConfigActions();
}

function setRuntimeConfigMode(mode) {
  if (!['existing','new','import'].includes(mode)) return;
  if (!runtimeConfigGuard()) { renderRuntimeConfigMode(); return; }
  if (mode !== S.runtimeConfigMode) {
    S.runtimeConfigMode = mode;
    S.runtimeSelectionRequest = (S.runtimeSelectionRequest || 0) + 1;
    invalidateRuntimeImport(); invalidateSchemaPreview();
    S.job = null; S.workflow = null; S.runtimeRevision = null; S.runtimeInputs = null;
    invalidateParameterReads(); S.paramsData = null; S.paramsForJob = null;
    $('params-area').innerHTML = ''; $('params-toolbar').classList.add('hidden');
    clearCsvEditor(); clearRuntimeEvidence();
    $('run-info').textContent = mode === 'new' ? '从样例新建，或选择任务包配置进行适配' : '请选择并使用运行 XML';
    if (mode !== 'new') $('job-name').value = '';
    else renderTasks(S.tasks || []);
  }
  renderRuntimeConfigMode(); refreshWorkflow();
}

function runtimeConfigEntry() {
  return S.runtimeCatalog?.configs?.find(item => item.schema === $('runtime-config-select').value);
}

function refreshRuntimeConfigActions() {
  const entry = runtimeConfigEntry(), locked = !!S.inputTransition || !!S.runtime?.busy || !!S.pollTimer ||
    !!S.csvDirty || !!S.xmlDirty || !!S.parameterWrites || !!S.runtimeActivationPending || !!S.runtimeExecutionPending;
  $('runtime-config-select').disabled = locked;
  $('runtime-config-mode').disabled = locked;
  $('btn-runtime-config-use').disabled = locked || !entry || entry.loadable === false;
  $('btn-runtime-config-refresh').disabled = locked;
  const preview = S.runtimeImportPreview;
  $('btn-runtime-import-apply').disabled = locked || !preview || preview.context !== runtimeImportContext() ||
    !!preview.report.conflict || !preview.report.token;
  $('btn-runtime-import-existing').disabled = locked || !preview?.report.conflict ||
    !(S.runtimeCatalog?.configs || []).some(item => item.schema === preview.body.destination_schema && item.loadable !== false);
}

function showRuntimeConfigDetails() {
  const entry = runtimeConfigEntry();
  $('runtime-config-details').textContent = !entry ? '' :
    `文件：${entry.file || entry.path || entry.schema}\nXML 任务名：${entry.runtime_name || entry.name || '未识别'}\n` +
    `修改时间：${entry.modified ? historyDate(entry.modified) : '未记录'}` +
    (entry.scene ? `\n场景：${entry.scene}` : '') + (entry.reason ? `\n${entry.reason}` : '');
  refreshRuntimeConfigActions();
}

async function refreshRuntimeConfigs({restore = false, internal = false} = {}) {
  if (restore && (S.runtime?.busy || S.pollTimer || S.launchPending)) {
    S.runtimeRestoreDeferred = true;
    $('runtime-config-status').textContent = '当前操作结束后恢复此构建上次使用的运行 XML。';
    return;
  }
  if (!runtimeConfigGuard({internal:restore || internal})) return;
  S.runtimeRestoreDeferred = false;
  const epoch = S.projectEpoch, project = S.project;
  const request = S.runtimeListRequest = (S.runtimeListRequest || 0) + 1;
  const selection = S.runtimeSelectionRequest || 0;
  const current = () => epoch === S.projectEpoch && project === S.project && request === S.runtimeListRequest &&
    selection === (S.runtimeSelectionRequest || 0);
  $('runtime-config-status').textContent = '正在读取当前构建中的运行 XML…';
  try {
    const result = await get('runtime_configs');
    if (!current()) return;
    if (result.error) throw Error(result.error);
    const previous = $('runtime-config-select').value || (S.job?.mode === 'existing' ? S.job.schema : '');
    S.runtimeCatalog = {...result,configs:result.configs || []};
    const select = $('runtime-config-select');
    select.replaceChildren(new Option(result.configs?.length ? '请选择运行 XML' : '当前运行目录没有运行 XML', ''));
    S.runtimeCatalog.configs.forEach(item => {
      const option = new Option(`${item.schema} · name=${item.runtime_name || item.name || '未识别'}${item.loadable === false ? ' · 不可加载：' + item.reason : ''}`, item.schema);
      option.disabled = item.loadable === false; select.add(option);
    });
    const selected = restore ? result.selected : null;
    select.value = selected?.schema || (S.runtimeCatalog.configs.some(item=>item.schema === previous) ? previous : '');
    $('runtime-config-status').textContent = `当前运行目录：${result.directory || '未配置'}；共 ${S.runtimeCatalog.configs.length} 份配置。`;
    showRuntimeConfigDetails();
    if (!selected?.schema) return;
    const entry = S.runtimeCatalog.configs.find(item => item.schema === selected.schema);
    if (!entry || entry.loadable === false) {
      $('runtime-config-status').textContent = `上次使用的 ${selected.schema} ${entry ? '不可加载：' + entry.reason : '已不存在'}；请选择其他配置。`; return;
    }
    if (!S.functions.includes(selected.func)) {
      $('runtime-config-status').textContent = `上次配置 ${selected.schema} 的功能 ${selected.func || '未指定'} 当前不支持；请明确选择功能后使用此配置。`; return;
    }
    const changed = selected.revision && selected.revision !== entry.revision;
    await activateRuntimeConfig(entry.schema, {restore:true,func:selected.func,taskId:selected.task_id,changed});
  } catch(error) {
    if (current()) $('runtime-config-status').textContent = `运行配置读取失败：${error.message}；可刷新重试。`;
  }
}

function applyRuntimeEngineering(inputs = {}) {
  if (!S.job || S.job.mode !== 'existing' || S.csvDirty) return;
  const path = inputs.engineering_file || '';
  const changed = path !== $('csv-path').value;
  S.runtimeInputs = {...(S.runtimeInputs || {}), ...inputs, engineering_file:path};
  for (const id of ['engineering-path','csv-path']) {
    const select = $(id);
    select.replaceChildren(new Option(path || '当前 XML 没有可用工参路径', path));
    select.value = path; select.disabled = true;
  }
  $('engineering-reason').textContent = path ? `当前 XML 实际工参：${path}；路径在参数面板中修改。` :
    `当前 XML 未配置可用工参路径${inputs.reason ? '：' + inputs.reason : ''}；请在参数中核对 EngineeringFilePath。`;
  if (changed) {
    csvRequest++; csvData = null;
    $('csv-wrap').textContent = path ? '已切换到当前 XML 的工参文件，请点击加载。' : '当前 XML 没有可用工参，不能加载上一次任务的 CSV。';
    $('csv-msg').textContent = '';
  }
}

async function reloadRuntimeEngineering(job) {
  const epoch = S.projectEpoch;
  const request = S.runtimeEngineeringRequest = (S.runtimeEngineeringRequest || 0) + 1;
  applyRuntimeEngineering({engineering_file:''});
  try {
    const data = await get('params', `schema=${encodeURIComponent(job.schema)}&func=${encodeURIComponent(job.func)}&all=1`);
    if (epoch !== S.projectEpoch || job !== S.job || request !== S.runtimeEngineeringRequest) return;
    if (data.error) throw Error(data.error);
    applyRuntimeEngineering(data.inputs || {engineering_file:''});
    if (!S.xmlDirty) renderParams(data);
    else if (S.paramsData) {
      const radiusDraft = [...parameterDrafts.keys()].some(el=>el.dataset.tag === 'DefaultCalcRadius');
      if (!radiusDraft) S.paramsData.param_sources = {...(S.paramsData.param_sources || {}),
        DefaultCalcRadius:data.param_sources?.DefaultCalcRadius};
    }
  } catch(error) {
    if (epoch === S.projectEpoch && job === S.job && request === S.runtimeEngineeringRequest) {
      $('engineering-reason').textContent = `工参路径已保存，但重新读取来源失败：${error.message}；请刷新配置后加载工参。`;
      toast($('engineering-reason').textContent,false);
    }
  }
}

function rememberRuntimeRevision(revision) {
  if (!revision || S.job?.mode !== 'existing') return;
  S.runtimeRevision = revision;
  const entry = S.runtimeCatalog?.configs?.find(item=>item.schema === S.job.schema);
  if (entry) entry.revision = revision;
}

function applyActivatedRuntimeConfig(result, {changed = false} = {}) {
  S.runtimeConfigMode = 'existing'; S.job = {...result.job,mode:'existing'};
  S.runtimeRevision = result.revision;
  S.func = S.job.func; $('job-name').value = S.job.name; $('task-id').value = String(S.job.taskId);
  renderFuncRadios(S.func);
  invalidateSchemaPreview(); invalidateRuntimeImport(); invalidateParameterReads();
  S.paramsData = null; S.paramsForJob = null; $('params-area').innerHTML = '';
  $('params-toolbar').classList.add('hidden');
  clearRuntimeEvidence(); applyRuntimeEngineering(result.inputs || {});
  $('runtime-config-select').value = S.job.schema;
  $('result-job').value = S.job.name;
  markWorkflowAssembled(S.job); updateNote(); renderRuntimeConfigMode();
  $('runtime-config-status').textContent = `${changed ? '文件内容已变化，已加载最新内容。' : ''}已加载 ${S.job.schema}；保留 XML 原参数，运行前需重新检查。` +
    (result.selection_warning ? `\n选择记忆提示：${result.selection_warning}` : '') +
    (result.cleanup_warning ? `\n${result.cleanup_warning}` : '');
  focusStage('check');
}

async function activateRuntimeConfig(schema = $('runtime-config-select').value, options = {}) {
  if (!runtimeConfigGuard({internal:options.restore})) return;
  const entry = S.runtimeCatalog?.configs?.find(item => item.schema === schema);
  if (!entry || entry.loadable === false) return toast(entry?.reason || '请选择可加载的运行 XML', false);
  const epoch = S.projectEpoch, scope = S.runtimeCatalog.scope;
  const request = S.runtimeSelectionRequest = (S.runtimeSelectionRequest || 0) + 1;
  const current = () => epoch === S.projectEpoch && scope === S.runtimeCatalog?.scope && request === S.runtimeSelectionRequest;
  const operation = async () => {
    S.runtimeActivationPending = true; refreshRuntimeConfigActions();
    try {
      const result = await post('activate_runtime_config', {schema,revision:entry.revision,scope,
        func:options.func || S.func,task_id:String(options.taskId || $('task-id').value || '1')});
      if (!current()) return;
      if (result.error || !result.ok || !result.job) throw Error(result.error || '配置加载未确认');
      applyActivatedRuntimeConfig(result, options);
      await loadParams();
    } catch(error) { if (current()) $('runtime-config-status').textContent = `配置加载失败：${error.message}；原文件未重新装配，可刷新后重试。`; }
    finally { if (current()) {S.runtimeActivationPending = false; refreshRuntimeConfigActions();refreshWorkflow();} }
  };
  return S.inputTransition && options.restore ? operation() : withInputTransition(operation);
}

async function runtimeExecutionSelectionChanged({persist = true} = {}) {
  if (S.job?.mode !== 'existing') return;
  if (!runtimeConfigGuard()) { $('task-id').value = String(S.job.taskId); renderFuncRadios(S.job.func); return; }
  const func = S.func, taskId = $('task-id').value || '1';
  const changed = func !== S.job.func || String(taskId) !== String(S.job.taskId);
  if (changed) {
    S.job = {...S.job,func,taskId:String(taskId)};
    S.runVerdict = null; S.runFingerprint = null;
    invalidateParameterReads(); markWorkflowAssembled(S.job); taskIdentityChanged();
    $('preflight-report').textContent = '运行功能或任务 ID 已改变，请重新进行运行前检查。';
  }
  if (!persist) return;
  const job = S.job, epoch = S.projectEpoch, scope = S.runtimeCatalog?.scope;
  const revision = S.runtimeRevision, engineeringRequest = S.runtimeEngineeringRequest;
  const request = S.runtimeSelectionRequest = (S.runtimeSelectionRequest || 0) + 1;
  const owner = S.runtimeExecutionOwner = {};
  S.runtimeExecutionPending = true; refreshWorkflow();
  try {
    const result = await post('activate_runtime_config',{schema:job.schema,revision,scope,func,task_id:String(taskId)});
    if (epoch !== S.projectEpoch || job !== S.job || request !== S.runtimeSelectionRequest || scope !== S.runtimeCatalog?.scope) return;
    if (result.error || !result.ok) throw Error(result.error || '执行选择保存失败');
    if (S.runtimeRevision === revision) rememberRuntimeRevision(result.revision);
    if (S.runtimeRevision === result.revision && engineeringRequest === S.runtimeEngineeringRequest)
      applyRuntimeEngineering(result.inputs || S.runtimeInputs || {});
    await loadParams();
  } catch(error) {
    if (epoch === S.projectEpoch && job === S.job) toast(`执行选择保存失败：${error.message}；请刷新配置后重试`,false);
  } finally {
    if (owner === S.runtimeExecutionOwner) { S.runtimeExecutionPending = false; S.runtimeExecutionOwner = null; refreshWorkflow(); }
  }
}

function runtimeImportContext() {
  return JSON.stringify([S.projectEpoch,S.runtimeCatalog?.scope,$('runtime-import-source').value.trim(),$('runtime-import-name').value.trim()]);
}
function invalidateRuntimeImport() {
  S.runtimeImportPreview = null; S.runtimeImportRequest = (S.runtimeImportRequest || 0) + 1;
  $('runtime-import-preview').classList.add('hidden');
  refreshRuntimeConfigActions();
}
async function previewRuntimeImport() {
  if (!runtimeConfigGuard()) return;
  invalidateRuntimeImport();
  const context = runtimeImportContext(), request = S.runtimeImportRequest;
  const body = {source:$('runtime-import-source').value.trim(),destination_schema:$('runtime-import-name').value.trim(),scope:S.runtimeCatalog?.scope};
  if (!body.source || !body.destination_schema) return toast('请填写本机 XML 路径和目标文件名',false);
  try {
    const report = await post('preview_runtime_import',body);
    if (context !== runtimeImportContext() || request !== S.runtimeImportRequest) return;
    if (report.error) throw Error(report.error);
    S.runtimeImportPreview = {context,body,report};
    const description = report.description || {};
    $('runtime-import-preview-text').textContent = `源文件：${report.source?.path || report.source || body.source}\n目标文件：${report.destination?.path || report.destination || body.destination_schema}\n` +
      `XML 任务名：${report.runtime_name || description.runtime_name || description.name || '未识别'}\n实际输出：${report.out_dir || description.out_dir || '未配置'}\n` +
      '只复制 XML；改文件名不会修改根任务名、输出目录或资源路径。相对路径按当前 Bin 目录解释。\n' +
      (report.same_file ? '源目标是同一文件：确认后直接加载，不复制。\n' : '') +
      (report.conflict ? '目标 XML 或同名装配记录已存在：请改目标名，或直接使用当前文件。\n' : '') +
      (report.warnings || description.warnings || []).join('\n');
    $('runtime-import-preview').classList.remove('hidden'); refreshRuntimeConfigActions();
  } catch(error) { if (context === runtimeImportContext()) toast(`导入预览失败：${error.message}`,false); }
}
async function importRuntimeConfig() {
  if (!runtimeConfigGuard()) return;
  const preview = S.runtimeImportPreview;
  if (!preview || preview.context !== runtimeImportContext() || preview.report.conflict || !preview.report.token) {
    invalidateRuntimeImport(); return toast('请按当前源路径和目标名称重新预览',false);
  }
  return withInputTransition(async () => {
    S.runtimeActivationPending = true; refreshRuntimeConfigActions();
    try {
      const result = await post('import_runtime_config',{...preview.body,token:preview.report.token,func:S.func,task_id:$('task-id').value || '1'});
      if (preview !== S.runtimeImportPreview || preview.context !== runtimeImportContext()) return;
      if (result.error || !result.ok || !result.job) throw Error(result.error || '导入未确认');
      applyActivatedRuntimeConfig(result); await loadParams();
      // Refresh the catalog without changing the just-loaded selection or parameters.
      S.runtimeActivationPending = false;
      await refreshRuntimeConfigs({restore:false,internal:true});
      if (result.selection_warning) $('runtime-config-status').textContent += `\n选择记忆提示：${result.selection_warning}`;
      if (result.cleanup_warning) $('runtime-config-status').textContent += `\n${result.cleanup_warning}`;
    } catch(error) { if (preview === S.runtimeImportPreview) toast(`导入失败：${error.message}；源路径和目标名已保留`,false); }
    finally { S.runtimeActivationPending = false; refreshRuntimeConfigActions(); }
  });
}

function initRuntimeConfigs() {
  $('runtime-config-mode').onchange = () => setRuntimeConfigMode($('runtime-config-mode').value);
  $('runtime-config-select').onchange = () => {
    if (!runtimeConfigGuard()) { $('runtime-config-select').value = S.job?.schema || ''; return; }
    S.runtimeSelectionRequest = (S.runtimeSelectionRequest || 0) + 1; showRuntimeConfigDetails();
  };
  $('btn-runtime-config-use').onclick = () => activateRuntimeConfig();
  $('btn-runtime-config-refresh').onclick = () => refreshRuntimeConfigs();
  $('btn-runtime-import-preview').onclick = previewRuntimeImport;
  $('btn-runtime-import-apply').onclick = importRuntimeConfig;
  $('btn-runtime-import-existing').onclick = () => activateRuntimeConfig(S.runtimeImportPreview?.body.destination_schema);
  ['runtime-import-source','runtime-import-name'].forEach(id => $(id).oninput = invalidateRuntimeImport);
  $('runtime-import-candidate').onchange = () => {
    const path = $('runtime-import-candidate').value;
    if (!path) return;
    $('runtime-import-source').value = path;
    $('runtime-import-name').value = path.split(/[\\/]/).pop(); invalidateRuntimeImport();
  };
}

function refreshRuntimeImportCandidates() {
  const select = $('runtime-import-candidate');
  select.replaceChildren(new Option('也可选择已识别的任务包 XML', ''));
  (S.tasks || []).forEach(task => (task.schema_candidates || []).forEach(item =>
    select.add(new Option(`${task.name} · ${item.path}`,item.path))));
}
