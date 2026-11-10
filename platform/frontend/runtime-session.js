/* runtime-session — plain script; shared application state is composed in app.js. */
"use strict";

async function doRun() {
  if (S.inputTransition || S.launchPending || S.pollTimer || S.runtime?.busy) return toast('平台已有任务，请等待结束或取消', false);
  if (!S.job) { focusStage("assembly"); return toast("请先装配本次任务",false); }
  if (!guardCsvChanges() || S.xmlDirty || S.parameterWrites || S.pendingRequests) return toast("请先完成当前编辑或保存操作",false);
  if (taskIdentityDirty()) return toast('任务输入已修改，请先重新装配', false);
  S.launchPending = true;
  const epoch = S.projectEpoch, job=S.job;
  const snapshot=WorkflowState.fingerprint(syncWorkflow());
  refreshWorkflow();
  const request = {schema:job.schema, func:job.func, task_id:job.taskId};
  try {
    const check = await post('preflight', request);
    if (epoch !== S.projectEpoch || job !== S.job || snapshot !== WorkflowState.fingerprint(syncWorkflow()) || S.csvDirty || S.xmlDirty || S.parameterWrites || S.pendingRequests) return;
    showPreflight(check);
    markWorkflowPreflight(check);
    if (check.error || !check.ok) return toast(check.error || '运行前检查未通过，请查看具体缺项', false);
    const r = await post('run', request);
    if (epoch !== S.projectEpoch) return;
    if (r.preflight) showPreflight(r.preflight);
    if (r.error) return toast(r.error, false);
    S.runFingerprint=S.workflow.fingerprint; S.runVerdict=null;
    rememberRunContext(r.sid, r.context);
    if (r.runtime) applyRuntimeState(r.runtime);
    attachConsole(r.sid, `运行 ${request.schema}：`);
    switchTab(document.querySelector('[data-tab="run"]'));
  } catch (error) {
    toast(`运行请求失败：${error.message}`, false);
  } finally {
    S.launchPending = false;
    refreshWorkflow();
  }
}

async function doPreflight() {
  if (!guardCsvChanges() || S.xmlDirty || S.parameterWrites || S.pendingRequests) return toast('请先完成当前编辑或保存操作',false);
  if (S.inputTransition || S.runtime?.busy || S.preflightPending) return;
  if (!S.job) return toast('请先装配运行配置',false);
  if (taskIdentityDirty()) return toast('任务设置已修改，请先重新装配',false);
  const epoch=S.projectEpoch, job=S.job;
  const snapshot=WorkflowState.fingerprint(syncWorkflow());
  S.preflightPending=true; refreshWorkflow();
  try {
    const report=await post('preflight',{schema:job.schema,func:job.func,task_id:job.taskId});
    if(epoch !== S.projectEpoch || job !== S.job || snapshot !== WorkflowState.fingerprint(syncWorkflow()) || S.csvDirty || S.xmlDirty || S.parameterWrites || S.pendingRequests) return;
    showPreflight(report); markWorkflowPreflight(report); focusStage('check');
  } catch(error) { toast('检查失败：'+error.message,false); }
  finally { S.preflightPending=false; refreshWorkflow(); }
}

function showPreflight(report) {
  const mode = report.context?.mode;
  $('preflight-report').textContent = (report.error || (report.ok ? '运行前检查通过' : '运行前检查未通过')) +
    (mode ? `\n配置模式：${mode.requested ?? '缺省 ground'}；本功能使用：${mode.effective}` : '') +
    (report.issues || []).map(issue => `\n${issue.severity === 'error' ? '阻断' : '提示'}：${issue.message}` +
      (issue.field ? ` [${issue.field}]` : '') + (issue.path ? `\n  ${issue.path}` : '')).join('');
}

const runtimeDisabled = new WeakMap();
async function withInputTransition(action) {
  if (S.inputTransition) return;
  S.inputTransition = true;
  applyRuntimeState(S.runtime || {busy:false});
  try { return await action(); }
  finally {
    S.inputTransition = false;
    applyRuntimeState(S.runtime || {busy:false});
  }
}
function applyRuntimeState(state, restore = false) {
  if (!state || state.error) return;
  S.runtime = state;
  S.runtimeSerial = (S.runtimeSerial || 0) + 1;
  const effectiveBusy = !!state.busy || !!S.inputTransition;
  const phases = {preparing:'准备中',running:'运行中',cancelling:'取消中',finalizing:'验证结果中'};
  $('runtime-status').textContent = state.busy
    ? `${state.external ? '其他平台实例正在操作；' : ''}${state.func || state.label || '任务'}：${phases[state.phase] || state.phase}；相关输入已锁定` : '平台空闲';
  const controls = [...document.querySelectorAll('[data-runtime-write]'),
    ...document.querySelectorAll('#params-area textarea, #stage-inputs textarea, #stage-assembly textarea, #params-area input, #params-area select, #params-area button, #stage-inputs input, #stage-inputs select, #stage-assembly input, #stage-build select, #btn-use-executable, #project-config-form input, #project-config-form select, #machine-config-form input')];
  controls.forEach(node => {
    if (node === $('btn-apply-schema') || node === $('btn-cleanup-apply') || (S.workflow && ['btn-run','btn-build','btn-render','btn-preflight','btn-use-executable'].some(id=>node === $(id)))) { runtimeDisabled.delete(node); return; }
    if (node.dataset?.defaultTag) {
      const d=S.paramsData?.thirdpart_defaults?.[node.dataset.defaultTag];
      node.disabled=effectiveBusy || !!S.xmlDirty || !d?.available; return;
    }
    if (effectiveBusy) {
      if (!runtimeDisabled.has(node)) runtimeDisabled.set(node, !!node.disabled);
      node.disabled = true;
    } else if (runtimeDisabled.has(node)) {
      node.disabled = runtimeDisabled.get(node);
      runtimeDisabled.delete(node);
    }
  });
  refreshSchemaApplyState();
  refreshCleanupState();
  if (S.workflow) refreshWorkflow();
  if (S.workflow) refreshCsvDirtyState();
  $("csv-wrap").querySelectorAll?.("[contenteditable]").forEach(node=>node.contentEditable=effectiveBusy ? "false" : "true");
  if (restore && state.busy && !state.external && state.sid && (S.sid !== state.sid || S.consoleHistorical)) attachConsole(state.sid, `恢复会话 ${state.sid}：`);
}

async function refreshRuntimeState(restore = false) {
  if (S.runtimeRefreshPending) return;
  S.runtimeRefreshPending = true;
  const serial = S.runtimeSerial || 0;
  const epoch = S.projectEpoch;
  try {
    const state = await get('runtime_state');
    if (epoch === S.projectEpoch && serial === (S.runtimeSerial || 0)) applyRuntimeState(state, restore);
  } catch (error) {
    if (epoch === S.projectEpoch) $('runtime-status').textContent = `运行状态暂不可用：${error.message}`;
  } finally {
    S.runtimeRefreshPending = false;
  }
}

async function stopCurrentOperation() {
  if (!S.runtime?.busy || S.runtime.external || !S.runtime.sid) return toast('当前没有可由本页面停止的操作', false);
  try {
    const result = await post('stop', {sid:S.runtime.sid});
    if (result.error) toast(result.error, false);
    if (result.runtime) applyRuntimeState(result.runtime);
  } catch (error) { toast(`停止请求失败：${error.message}`, false); }
}

function rememberRunContext(sid, context) {
  if (!context?.func) return;
  if (S.resultSid === sid) { S.resultContext = context; return; }
  S.resultSid = sid;
  S.resultContext = context;
  $('result-job').value = context.task_name || '';
}

const VERDICTS = {success:'成功',partial:'部分成功',no_update:'无模型更新',unconfirmed:'未确认',failed:'失败',cancelled:'已取消',pending:'处理中'};
function verdictClass(verdict) {
  return verdict === 'success' ? 'ok' : ['failed','cancelled'].includes(verdict) ? 'fail' : verdict === 'pending' ? 'running' : 'unknown';
}

const CURRENT_FILE_STATES = {matched:'仍匹配',changed:'已变化',missing:'有文件缺失',unconfirmed:'未确认'};
function currentFilesLabel(report) {
  return CURRENT_FILE_STATES[report.current_files?.status] || '未确认';
}
function resultBadgeClass(report) {
  const verdict = report.historical_verdict || report.verdict;
  if (report.historical && verdict === 'success' && report.current_files?.status !== 'matched') return 'unknown';
  return verdictClass(verdict);
}

function showOutcome(id, report) {
  const labels = {valid:'通过',invalid:'不完整或损坏',failed:'失败',unconfirmed:'未确认',pending:'待验证',
    usable:'可用',unusable:'不可用',success:'成功',partial:'部分成功',no_update:'无模型更新',skipped:'已跳过',
    not_applicable:'不适用',unassociated:'未关联',done:'已结束',exited:'已退出',running:'运行中',
    cancelling:'取消中',finalizing:'结果验证中',cancelled:'已取消',interrupted:'已中断'};
  const process = report.process || {}, artifacts = report.artifacts || {}, business = report.business || {};
  const exit = process.exit ?? process.exit_code ?? report.exit;
  const text = [`进程：${labels[process.status] || process.status || '未确认'}；退出码 ${exit ?? (report.status === 'interrupted' ? '未记录' : '尚未退出')}`,
    `产物验证：${labels[artifacts.status] || artifacts.status || '未确认'}`,
    `业务可用性：${labels[business.status] || business.status || '未确认'}`];
  if (report.historical) text.unshift(`当时验证结果：${VERDICTS[report.historical_verdict || report.verdict] || '未确认'}`,
    `当前文件匹配状态：${currentFilesLabel(report)}；当时结论不代表当前文件状态`);
  if (report.archive) text.push(`运行归档：${({complete:'已保存',pending:'准备中',incomplete:'不完整'})[report.archive.status] || '未确认'}` +
    (report.archive.dir || report.archive_dir ? `\n  ${report.archive.dir || report.archive_dir}` : ''));
  const mode = report.context?.mode;
  if (mode) text.push(`配置模式：${mode.requested ?? '缺省 ground'}；实际计算：${mode.effective}`);
  if (business.total != null) text.push(`校正站点：${business.total}；成功：${business.succeeded ?? 0}；更新：${business.updated ?? 0}；失败：${business.failed ?? 0}；未更新：${business.no_update ?? 0}`);
  (business.sites || []).forEach(site => text.push(`${site.site}：${site.success ? '校正成功' : '校正失败'}，${site.update ? '有更新' : '未更新'}，网格 ${site.grids}，原因码 0x${Number(site.code).toString(16)}`));
  const countText = counts => ['processed','total','succeeded','success','updated','skipped','failed','unconfirmed']
    .filter(key => counts[key] != null).map(key =>
      `${({processed:'处理',total:'总数',succeeded:'成功',success:'成功',updated:'更新',skipped:'跳过',failed:'失败',unconfirmed:'未确认'})[key]} ${counts[key]}`).join('，');
  if (business.counts) text.push('模型类别汇总：' + countText(business.counts));
  Object.entries(business.model_kinds || {}).forEach(([kind, outcome]) => {
    text.push(`${({cells:'站点模型',general:'通用模型',scenes:'场景模型'})[kind] || kind}：${labels[outcome.status] || outcome.status || '未确认'}` +
      (countText(outcome) ? `；${countText(outcome)}` : '') +
      (outcome.unit ? `；单位：${({site_groups:'站点组',models:'模型',scenes:'场景'})[outcome.unit] || outcome.unit}` : '') +
      (outcome.reason ? `；${outcome.reason}` : ''));
    (outcome.items || []).forEach((item, index) => text.push(
      `  ${item.label || item.name || item.id || item.site || index + 1}：${labels[item.status] || item.status || '未确认'}` +
      (item.reason ? `；${item.reason}` : '')));
  });
  (artifacts.checked || []).forEach(item => {
    if (item.valid != null) text.push(`${item.path || item.file || ''}：有效栅格 ${item.valid}` +
      (item.total != null ? ` / ${item.total}` : '') + (item.current === false ? '；本次归属未确认' : ''));
  });
  (report.issues || []).forEach(issue => text.push(`${issue.severity === 'error' ? '问题' : '提示'}：${issue.message}` + (issue.path ? `\n  ${issue.path}` : '')));
  if (report.internal_error) text.push(report.internal_error);
  $(id).textContent = text.join('\n');
}

function attachConsole(sid, title, onDone = null, {historical = false} = {}) {
  const epoch = S.projectEpoch, project = S.project, sentDraft = {...S.projectDraft};
  const attachment = S.consoleAttachment = (S.consoleAttachment || 0) + 1;
  const current = () => attachment === S.consoleAttachment && sid === S.sid && epoch === S.projectEpoch;
  S.sid = sid; S.since = 0; S.consoleHistorical = historical;
  showOperation(title);
  $("btn-export-log").disabled = false;
  const con = $("run-console");
  con.textContent = title + "\n";
  $('run-outcome').textContent = '';
  $("run-status").className = "badge running hidden";
  if (S.pollTimer) clearInterval(S.pollTimer);
  if (S.historyPollTimer) clearInterval(S.historyPollTimer);
  S.pollTimer = null; S.historyPollTimer = null;
  let polling = false;
  const connection = $('run-connection');
  if (connection) connection.textContent = historical ? '正在读取历史日志…' : '日志连接中…';
  const timer = setInterval(async () => {
    if (polling || !current()) return;
    polling = true;
    try {
    const cursor = S.since;
    const r = await get("output", `sid=${sid}&since=${cursor}&limit=500`);
    if (!current()) return;
    if (r.code === 'SESSION_NOT_FOUND') {
      clearInterval(timer);
      if (S.pollTimer === timer) S.pollTimer = null;
      if (S.historyPollTimer === timer) S.historyPollTimer = null;
      S.sid = 0; S.consoleHistorical = false;
      if (S.resultSid === sid) { S.resultSid = 0; S.resultContext = null; }
      $('btn-export-log').disabled = true;
      $('run-status').className = 'badge unknown';
      $('run-status').textContent = '会话已失效；结果未确认';
      $('run-outcome').textContent = `${r.error}；目录浏览不作为本次成功证据。`;
      if (connection) connection.textContent = '会话不可用';
      await refreshRuntimeState(true);
      return;
    }
    if (r.error) throw new Error(r.error);
    if (connection) connection.textContent = r.has_more ? '日志已连接；正在补读后续日志…' : '日志已连接';
    if (connection && r.cleanup_error && !['done','interrupted'].includes(r.status))
      connection.textContent = `正在等待编译进程收尾：${r.cleanup_error}`;
    rememberRunContext(sid, r.context);
    const outputLines = r.lines || [];
    const next = Number.isFinite(r.next_since) ? r.next_since : cursor + outputLines.length;
    if (next < cursor || (r.has_more && next <= cursor)) throw new Error('日志分页游标无效');
    S.since = next;
    if (outputLines.length) {
      const frag = outputLines.map(l => {
        const cls = /FATAL|ERROR/.test(l) ? "err" : /WARN/.test(l) ? "warn" : "";
        return cls ? `<span class="${cls}">${esc(l)}</span>` : esc(l);
      }).join("\n");
      con.insertAdjacentHTML("beforeend", frag + "\n");
      con.scrollTop = con.scrollHeight;
    }
    if (['done','interrupted'].includes(r.status) && !r.has_more) {
      clearInterval(timer);
      if (S.pollTimer === timer) S.pollTimer = null;
      if (S.historyPollTimer === timer) S.historyPollTimer = null;
      // A terminal response is backend evidence that this session released its
      // lease. Do not make local unlock depend on a separate refresh request.
      if (!historical && !S.runtime?.external && S.runtime?.sid === sid) applyRuntimeState({busy:false,phase:'idle'});
      else if (S.workflow) refreshWorkflow();
      const b = $("run-status");
      b.classList.remove("hidden");
      const result = r.result || {verdict:r.exit === 0 ? 'unconfirmed' : 'failed',process:{status:'done',exit:r.exit}};
      const report = {...result, status:r.status, historical:historical || r.historical, context:r.context, internal_error:r.internal_error,
        current_files:r.current_files || result.current_files, archive:r.archive || result.archive};
      b.className = 'badge ' + resultBadgeClass(report);
      b.textContent = `${historical ? '历史会话 ' + sid + '；当时：' : ''}${VERDICTS[result.verdict] || '未确认'} · 退出码 ${r.exit ?? '未记录'}`;
      if (!historical && r.context?.func) S.runVerdict=result.verdict;
      showOutcome('run-outcome', report);
      if (connection) connection.textContent = historical ? '历史日志已读取完整' : '日志已读取完整';
      if (!historical) toast(`${r.label}：${VERDICTS[result.verdict] || '未确认'}，退出码 ${r.exit}`, result.verdict === 'success');
      try {
        if (onDone) await onDone(r);
        else if (!historical && r.context?.operation === 'build' && epoch === S.projectEpoch &&
                 r.context.project?.replace(/\\/g, '/') === project) {
          const status = await post('build_status', {});
          if (!current()) return;
          if (status.error) return setupError(status);
          applyBuildStatus(status, sentDraft);
        }
      } catch (error) {
        if (attachment === S.consoleAttachment && sid === S.sid && project === S.project && connection)
          connection.textContent = `日志已读取完整；后续状态刷新失败：${error.message}。可重新检测程序状态。`;
      } finally {
        // Runtime and history discovery are independent of the completion
        // callback; a slow request must not hold the completed task's controls.
        void refreshRuntimeState();
        if (S.historyInitialized) void loadRunHistory();
        if (S.workflow) refreshWorkflow();
      }
    }
    } catch (error) {
      if (current() && connection) connection.textContent = `日志连接中断，正在重试：${error.message}`;
    } finally { polling = false; }
  }, 700);
  if (historical) S.historyPollTimer = timer;
  else S.pollTimer = timer;
  if(S.workflow) refreshWorkflow();
  return attachment;
}

async function exportRunLog() {
  const sid = S.sid, epoch = S.projectEpoch, project = S.project;
  if (!sid) return toast("尚无运行日志，请先运行程序或工具", false);
  const button = $("btn-export-log");
  button.disabled = true;
  let url;
  try {
    // Fetch from the beginning, including output not yet delivered by UI polling.
    const r = await get("output", `sid=${sid}&since=0`);
    if (sid !== S.sid || epoch !== S.projectEpoch) return;
    if (r.error) return toast(`日志导出失败：${r.error}`, false);
    const snapshotTotal = r.total;
    const outputLines = [...(r.lines || [])].slice(0, snapshotTotal);
    let cursor = Number.isFinite(r.next_since) ? r.next_since : outputLines.length;
    let more = r.has_more;
    while (more && cursor < snapshotTotal) {
      const page = await get('output', `sid=${sid}&since=${cursor}&limit=500`);
      if (sid !== S.sid || epoch !== S.projectEpoch) return;
      if (page.error) throw new Error(page.error);
      const lines = page.lines || [];
      const next = Number.isFinite(page.next_since) ? page.next_since : cursor + lines.length;
      if (next <= cursor) throw new Error('日志分页游标无效，请重试');
      outputLines.push(...lines.slice(0, snapshotTotal - outputLines.length));
      cursor = next; more = page.has_more;
    }
    if (outputLines.length < snapshotTotal) throw new Error('日志读取不完整，请重试');
    const now = new Date();
    const lines = [
      "LiShuttle 运行日志", `项目：${project || ""}`, `会话：${sid}`,
      `运行指令/工具：${r.label}`, `导出时间：${now.toISOString()}`,
      `状态：${r.status === 'interrupted' ? '已中断' : r.status === "done" ? "已结束" : "运行中（截至导出时）"}`,
      `退出码：${r.exit == null ? (r.status === 'interrupted' ? '未记录' : '尚未退出') : r.exit}`, `日志行数：${snapshotTotal}`,
      "", ...outputLines, "",
    ];
    const blob = new Blob(["\uFEFF", lines.join("\r\n")], {type:"text/plain;charset=utf-8"});
    url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `run-log-${now.toISOString().replace(/[:.]/g, "-")}-session-${sid}.log`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    toast("日志已导出；运行中的日志包含截至导出时已收集的输出");
  } catch (error) {
    if (sid === S.sid && epoch === S.projectEpoch) toast(`日志导出失败：${error.message}`, false);
  } finally {
    if (url) setTimeout(() => URL.revokeObjectURL(url), 1000);
    button.disabled = !S.sid;
  }
}

/* ---------------- 结果 ---------------- */

let lastResultsDir = "";
let lastArchiveDir = "";

function historyDate(value) {
  if (value == null || value === '') return '时间未记录';
  const date = new Date(typeof value === 'number' && value < 1e12 ? value * 1000 : value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', {hour12:false});
}

async function initRunHistory() {
  if (!$('run-history-list')) return;
  S.historyInitialized = true;
  $('btn-history-refresh').onclick = () => loadRunHistory();
  $('btn-history-prev').onclick = () => loadRunHistory(Math.max(0, S.historyState.offset - S.historyState.limit));
  $('btn-history-next').onclick = () => loadRunHistory(S.historyState.offset + S.historyState.limit);
  const archive = $('btn-open-archive');
  if (archive) archive.onclick = openRunArchive;
  return resetRunHistory();
}

function resetRunHistory() {
  if (S.historyPollTimer) {
    clearInterval(S.historyPollTimer); S.historyPollTimer = null;
    S.consoleAttachment = (S.consoleAttachment || 0) + 1;
  }
  S.historyState = {offset:0,limit:10,total:0,runs:[],request:0};
  S.consoleHistorical = false;
  lastArchiveDir = '';
  const archive = $('btn-open-archive');
  if (archive) archive.disabled = true;
  const connection = $('run-connection');
  if (connection) connection.textContent = '';
  $('btn-open-dir').disabled = true;
  $('run-outcome').textContent = '';
  $('result-validation').textContent = '';
  if (!S.historyInitialized) return;
  $('run-history-list').innerHTML = '';
  $('run-history-page').textContent = '';
  return loadRunHistory(0);
}

async function loadRunHistory(offset = S.historyState?.offset || 0) {
  if (!S.historyInitialized) return;
  if (!S.project) {
    $('run-history-status').textContent = '请先选择项目，再查看最近运行。';
    $('run-history-list').textContent = '尚未选择项目。';
    return;
  }
  const state = S.historyState, epoch = S.projectEpoch;
  const request = ++state.request;
  const current = () => state === S.historyState && epoch === S.projectEpoch && request === state.request;
  $('run-history-status').textContent = '正在读取最近运行…';
  $('btn-history-prev').disabled = true;
  $('btn-history-next').disabled = true;
  try {
    const report = await get('history', `limit=${state.limit}&offset=${offset}`);
    if (!current()) return;
    if (report.error) throw new Error(report.error);
    state.offset = offset; state.total = report.total || 0; state.runs = report.runs || [];
    const list = $('run-history-list');
    if (!state.runs.length) { list.innerHTML = ''; list.textContent = '当前项目暂无运行记录。'; }
    else {
      list.innerHTML = state.runs.map(run => {
        const sid = esc(String(run.sid)).replace(/"/g, '&quot;');
        return `<button type="button" class="history-run${String(run.sid) === String(S.resultSid) ? ' selected' : ''}" data-history-sid="${sid}">` +
          `<span class="history-name">${esc(run.context?.task_name || run.label || '本地任务')} <small>会话 ${esc(run.sid)}</small></span>` +
          `<span class="history-meta">${esc(historyDate(run.created_at))} · 当时：${esc(VERDICTS[run.result?.verdict] || (run.status === 'running' ? '运行中' : '未确认'))}</span></button>`;
      }).join('');
      list.querySelectorAll('[data-history-sid]').forEach(button => { button.onclick = () => selectHistoryRun(button.dataset.historySid); });
    }
    $('run-history-status').textContent = '历史结论仅描述运行当时；选择记录后检查当前文件是否匹配。';
    $('run-history-page').textContent = state.total ? `${offset + 1}–${Math.min(offset + state.limit, state.total)} / ${state.total} 条` : '0 条';
    $('btn-history-prev').disabled = offset === 0;
    $('btn-history-next').disabled = offset + state.limit >= state.total;
  } catch (error) {
    if (!current()) return;
    $('run-history-status').textContent = `最近运行读取失败：${error.message}；可点击刷新重试。`;
    $('btn-history-prev').disabled = state.offset === 0;
    $('btn-history-next').disabled = state.offset + state.limit >= state.total;
  }
}

async function selectHistoryRun(sid) {
  const run = S.historyState?.runs.find(item => String(item.sid) === String(sid));
  if (!run) return;
  if (S.runtime?.busy || S.pollTimer || S.launchPending || S.inputTransition) {
    return toast(S.runtime?.external
      ? '其他平台实例正在操作，请等待结束后再查看历史日志与结果。'
      : '当前运行或编译尚未结束，请等待结束后再查看历史日志与结果。', false);
  }
  S.resultSid = run.sid; S.resultContext = run.context || {};
  $('result-job').value = run.context?.task_name || '';
  $('result-directory-only').checked = false;
  attachConsole(run.sid, `历史会话 ${run.sid}：${run.label || run.context?.task_name || ''}`, null, {historical:true});
  return loadResults();
}

async function openRunArchive() {
  if (!lastArchiveDir) return toast('此记录暂无可用归档目录', false);
  try {
    const result = await post('open_folder', {path:lastArchiveDir});
    if (result.error) toast(result.error, false);
  } catch (error) { toast(`归档目录打开失败：${error.message}`, false); }
}

async function loadResults() {
  const epoch = S.projectEpoch;
  const request = S.resultRequest = (S.resultRequest || 0) + 1;
  const enteredJob = $('result-job').value.trim();
  const job = enteredJob || (S.job && S.job.name);
  const sid = !$("result-directory-only").checked && S.resultSid && (!enteredJob || enteredJob === S.resultContext?.task_name) ? S.resultSid : 0;
  if (!job && !sid) return toast("填任务名或先运行任务", false);
  lastArchiveDir = ''; lastResultsDir = '';
  const archiveButton = $('btn-open-archive');
  if (archiveButton) archiveButton.disabled = true;
  $('btn-open-dir').disabled = true;
  $('result-status').className = 'badge running';
  $('result-status').textContent = sid ? `正在读取会话 ${sid}…` : '正在读取任务目录…';
  $('result-validation').textContent = '';
  $('result-files').innerHTML = ''; $('result-log').textContent = '';
  try {
  const r = await get("results", sid ? `sid=${sid}` : `job=${encodeURIComponent(job)}`);
  if (epoch !== S.projectEpoch || request !== S.resultRequest) return;
  if (r.error) throw new Error(r.error);
  lastResultsDir = r.dir || "";
  $('btn-open-dir').disabled = !lastResultsDir || !r.exists;
  lastArchiveDir = r.archive?.dir || r.archive_dir || '';
  const archive = $('btn-open-archive');
  if (archive) archive.disabled = !lastArchiveDir;
  const b = $("result-status");
  showOutcome('result-validation', r);
  if (!r.exists && !r.historical) {
    b.className = "badge fail"; b.textContent = "输出目录不存在";
    $("result-files").innerHTML = ""; $("result-log").textContent = "";
    return;
  }
  b.classList.remove("hidden");
  b.className = 'badge ' + (r.associated ? resultBadgeClass(r) : 'unknown');
  b.textContent = r.historical
    ? `历史会话 ${sid}；当时：${VERDICTS[r.historical_verdict || r.verdict] || '未确认'}；当前文件：${currentFilesLabel(r)}`
    : r.associated ? `会话 ${sid}：${VERDICTS[r.verdict] || '未确认'}` : '目录浏览：未关联本次运行';
  $("result-files").innerHTML = (r.files || []).map(f =>
    `<div><span>${esc(f.rel)}</span><span class="muted">${f.size}</span></div>`).join("");
  if (!r.exists && r.historical) $('result-files').textContent = '当前输出目录不存在；可查看本次运行归档。';
  const src = r.log_file
    ? `\n（历史目录日志：${esc(r.log_file)}；不作为本次成功证据）` : "";
  $("result-log").innerHTML =
    (r.log_tail || []).map(l => {
      const cls = /FATAL|ERROR/.test(l) ? "err" : /WARN/.test(l) ? "warn" : "";
      return cls ? `<span class="${cls}">${esc(l)}</span>` : esc(l);
    }).join("\n") + src || "（无日志）";
  } catch (error) {
    if (epoch === S.projectEpoch && request === S.resultRequest) {
      $('result-status').className = 'badge unknown';
      $('result-status').textContent = '读取失败；结果未确认';
      $('result-validation').textContent = `结果读取失败：${error.message}`;
      toast(`结果读取失败：${error.message}`, false);
    }
  }
}
