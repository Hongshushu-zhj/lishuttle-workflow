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
    ? `${state.func || state.label || '任务'}：${phases[state.phase] || state.phase}；相关输入已锁定` : '平台空闲';
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
  if (restore && state.busy && state.sid && S.sid !== state.sid) attachConsole(state.sid, `恢复会话 ${state.sid}：`);
}

async function refreshRuntimeState(restore = false) {
  if (S.runtimeRefreshPending) return;
  S.runtimeRefreshPending = true;
  const serial = S.runtimeSerial || 0;
  try {
    const state = await get('runtime_state');
    if (serial === (S.runtimeSerial || 0)) applyRuntimeState(state, restore);
  } catch (error) {
    $('runtime-status').textContent = `运行状态暂不可用：${error.message}`;
  } finally {
    S.runtimeRefreshPending = false;
  }
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

function showOutcome(id, report) {
  const labels = {valid:'通过',invalid:'不完整或损坏',failed:'失败',unconfirmed:'未确认',pending:'待验证',
    usable:'可用',unusable:'不可用',success:'成功',partial:'部分成功',no_update:'无模型更新',skipped:'已跳过',
    not_applicable:'不适用',unassociated:'未关联',done:'已结束',exited:'已退出',running:'运行中',
    cancelling:'取消中',finalizing:'结果验证中',cancelled:'已取消'};
  const process = report.process || {}, artifacts = report.artifacts || {}, business = report.business || {};
  const exit = process.exit ?? process.exit_code ?? report.exit;
  const text = [`进程：${labels[process.status] || process.status || '未确认'}；退出码 ${exit ?? '尚未退出'}`,
    `产物验证：${labels[artifacts.status] || artifacts.status || '未确认'}`,
    `业务可用性：${labels[business.status] || business.status || '未确认'}`];
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

function attachConsole(sid, title, onDone = null) {
  const epoch = S.projectEpoch, project = S.project, sentDraft = {...S.projectDraft};
  S.sid = sid; S.since = 0;
  showOperation(title);
  $("btn-export-log").disabled = false;
  const con = $("run-console");
  con.textContent = title + "\n";
  $('run-outcome').textContent = '';
  $("run-status").className = "badge running hidden";
  if (S.pollTimer) clearInterval(S.pollTimer);
  S.pollTimer = setInterval(async () => {
    const r = await get("output", `sid=${sid}&since=${S.since}`);
    if (sid !== S.sid) return;
    if (r.code === 'SESSION_NOT_FOUND') {
      clearInterval(S.pollTimer);
      S.pollTimer = null;
      S.sid = 0;
      if (S.resultSid === sid) { S.resultSid = 0; S.resultContext = null; }
      $('btn-export-log').disabled = true;
      $('run-status').className = 'badge unknown';
      $('run-status').textContent = '会话已失效；结果未确认';
      $('run-outcome').textContent = `${r.error}；目录浏览不作为本次成功证据。`;
      await refreshRuntimeState(true);
      return;
    }
    if (r.error) return;
    rememberRunContext(sid, r.context);
    if (r.lines.length) {
      S.since = r.total;
      const frag = r.lines.map(l => {
        const cls = /FATAL|ERROR/.test(l) ? "err" : /WARN/.test(l) ? "warn" : "";
        return cls ? `<span class="${cls}">${esc(l)}</span>` : esc(l);
      }).join("\n");
      con.insertAdjacentHTML("beforeend", frag + "\n");
      con.scrollTop = con.scrollHeight;
    }
    if (r.status === "done") {
      clearInterval(S.pollTimer);
      S.pollTimer = null;
      const b = $("run-status");
      b.classList.remove("hidden");
      const result = r.result || {verdict:r.exit === 0 ? 'unconfirmed' : 'failed',process:{status:'done',exit:r.exit}};
      b.className = 'badge ' + verdictClass(result.verdict);
      b.textContent = `${VERDICTS[result.verdict] || '未确认'} · 退出码 ${r.exit}`;
      if(r.context?.func) S.runVerdict=result.verdict;
      showOutcome('run-outcome', {...result, context:r.context, internal_error:r.internal_error});
      toast(`${r.label}：${VERDICTS[result.verdict] || '未确认'}，退出码 ${r.exit}`, result.verdict === 'success');
      await refreshRuntimeState();
      if (onDone) await onDone(r);
      else if (r.context?.operation === 'build' && epoch === S.projectEpoch &&
               r.context.project?.replace(/\\/g, '/') === project) {
        const status = await post('build_status', {});
        if (epoch !== S.projectEpoch) return;
        if (status.error) return setupError(status);
        applyBuildStatus(status, sentDraft);
      }
    }
  }, 700);
  if(S.workflow) refreshWorkflow();
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
    const now = new Date();
    const lines = [
      "LiShuttle 运行日志", `项目：${project || ""}`, `会话：${sid}`,
      `运行指令/工具：${r.label}`, `导出时间：${now.toISOString()}`,
      `状态：${r.status === "done" ? "已结束" : "运行中（截至导出时）"}`,
      `退出码：${r.exit == null ? "尚未退出" : r.exit}`, `日志行数：${r.total}`,
      "", ...r.lines, "",
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

async function loadResults() {
  const epoch = S.projectEpoch;
  const job = $("result-job").value.trim() || (S.job && S.job.name);
  const sid = !$("result-directory-only").checked && S.resultSid && (!job || job === S.resultContext?.task_name) ? S.resultSid : 0;
  if (!job && !sid) return toast("填任务名或先运行任务", false);
  const r = await get("results", sid ? `sid=${sid}` : `job=${encodeURIComponent(job)}`);
  if (epoch !== S.projectEpoch) return;
  if (r.error) return toast(r.error, false);
  lastResultsDir = r.dir || "";
  const b = $("result-status");
  showOutcome('result-validation', r);
  if (!r.exists) {
    b.className = "badge fail"; b.textContent = "输出目录不存在";
    $("result-files").innerHTML = ""; $("result-log").textContent = "";
    return;
  }
  b.classList.remove("hidden");
  b.className = 'badge ' + (r.associated ? verdictClass(r.verdict) : 'unknown');
  b.textContent = r.associated ? `会话 ${sid}：${VERDICTS[r.verdict] || '未确认'}` : '目录浏览：未关联本次运行';
  $("result-files").innerHTML = r.files.map(f =>
    `<div><span>${esc(f.rel)}</span><span class="muted">${f.size}</span></div>`).join("");
  const src = r.log_file
    ? `\n（历史目录日志：${esc(r.log_file)}；不作为本次成功证据）` : "";
  $("result-log").innerHTML =
    r.log_tail.map(l => {
      const cls = /FATAL|ERROR/.test(l) ? "err" : /WARN/.test(l) ? "warn" : "";
      return cls ? `<span class="${cls}">${esc(l)}</span>` : esc(l);
    }).join("\n") + src || "（无日志）";
}
