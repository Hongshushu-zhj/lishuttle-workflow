let parameterRequest = 0;
function invalidateParameterReads() { parameterRequest++; }
async function loadParams() {
  const job = S.job;
  if (!job || S.xmlDirty) return;
  const func = S.func || job.func, request = ++parameterRequest, editRevision = parameterEditRevision;
  if (S.paramsForJob !== job) {
    $('params-area').innerHTML = '';
    $('params-toolbar').classList.add('hidden');
  }
  const r = await get("params", `schema=${encodeURIComponent(job.schema)}&func=${encodeURIComponent(func)}&all=1`);
  if (S.xmlDirty || job !== S.job || func !== (S.func || S.job.func) || request !== parameterRequest || editRevision !== parameterEditRevision) return;
  if (r.error) return toast(r.error, false);
  S.paramsForJob = job;
  renderParams(r);
}

function renderParams(r) {
  if (S.xmlDirty) return;
  S.paramsData = r;
  if (S.job?.mode === 'existing' && r.revision) rememberRuntimeRevision(r.revision);
  if (S.job?.mode === 'existing' && r.inputs) applyRuntimeEngineering(r.inputs);
  if (typeof renderIndoorBuildingExport === 'function') renderIndoorBuildingExport(r);
  const area = $("params-area");
  const job = S.job;
  const profile = r.profile || {};
  const scope = S.paramsScope || (profile.reviewed ? 'current' : 'all'), search = (S.paramsSearch || '').trim().toLowerCase();
  const groups = r.groups.map(group=>({...group, rows:group.rows.filter(p=>
    (scope === 'all' || (p.recommended !== false && (scope !== 'active' ||
      (p.classification !== 'unclassified' && p.usage?.active !== false)))) && (!search ||
      [p.name,p.label,p.desc,p.group,p.display_value ?? r.values[p.name]].some(v=>String(v || '').toLowerCase().includes(search))))})).filter(g=>g.rows.length);
  const shown = groups.reduce((sum,g)=>sum+g.rows.length,0);
  const counts = r.counts || {total:r.groups.reduce((sum,g)=>sum+g.rows.length,0)};
  const info = S.functionInfo?.[r.function] || FUNC_INFO[r.function];
  const label = info?.label || info?.zh || r.function || S.func || '';
  const indoor = r.function === 'predindoor';
  $('params-toolbar').classList.remove('hidden');
  $('params-scope').value = scope;
  $('params-search').value = S.paramsSearch || '';
  $('params-scope').onchange = () => { if (!guardParameterFilter()) return; S.paramsScope = $('params-scope').value; renderParams(S.paramsData); };
  $('params-search').oninput = () => { if (!guardParameterFilter()) return; S.paramsSearch = $('params-search').value; renderParams(S.paramsData); };
  $('params-summary').textContent = `XML 已识别 ${counts.total} 项 · 当前显示 ${shown} 项 · 推荐功能：${label}` +
    (r.counts ? ` · 本功能可配置 ${counts.recommended} 项 · 其他功能/场景 ${counts.other} 项 · 未分类 ${counts.unclassified} 项` : '');
  $('params-source').textContent = `实际读取与编辑文件：${r.file || '当前运行 XML'}${r.schema_name ? ` · name=${r.schema_name}` : ''}。字典中但当前 XML 未定义的字段不作为已配置参数显示。` +
    (indoor ? '下方室内射线与接收参数直接保存到当前 XML，无需重新编译程序。' : '');
  const review = profile.source_review || {};
  const reviewText = review.status === 'matched' ? '当前项目源码与调研版本一致' : review.status === 'changed'
    ? `当前项目源码存在差异，功能范围待复核：${(review.changed || []).join('、')}` : '当前项目源码不完整，使用已调研版本的参考范围';
  const required = profile.missing_required || [], optional = profile.missing_optional || [];
  const missingIndoor = indoor ? [...new Set([...required, ...optional])].filter(tag =>
    ['MaxRayNumber','MaxDeepth','MaxReflection','MaxDiffraction','MaxPenetration','IndoorRxPowerSF','IndoorSinrSF','IsForcedCalc'].includes(tag)) : [];
  $('params-profile').innerHTML = profile.reviewed
    ? `<p><strong>${esc(profile.label || label)}</strong>：${esc(profile.description || '')}</p>` +
      `<p class="${review.status === 'matched' ? '' : 'param-warning'}">${esc(reviewText)}</p>` +
      (profile.scene_warning ? `<p class="param-warning">${esc(profile.scene_warning)}</p>` : '') +
      (missingIndoor.length ? `<p class="param-warning">当前 XML 缺少室内参数：${esc(missingIndoor.join('、'))}。如需调整这些参数，请从室内样例重新装配运行单，再核对当前任务设置；平台不会自动添加缺失参数。</p>` : '') +
      (required.length ? `<p class="param-warning">本功能强制读取的元素在当前 XML 中缺失：${esc(required.join('、'))}。请核对所选运行配置；不会自动补写或覆盖参数。</p>` : '') +
      (optional.length ? `<details><summary>本功能另有 ${optional.length} 项可选参数未在 XML 中定义</summary><p>${esc(optional.join('、'))}</p><p>这些是可配置项，不是已配置值；缺失时由引擎默认或条件分支处理。</p></details>` : '') +
      (profile.notes || []).map(note=>`<p>${esc(note)}</p>`).join('')
    : '<p>该功能暂沿用参数字典推荐范围；尚未完成逐项源码调研，可切换到全部已识别参数核对。</p>';
  area.innerHTML = "";
  if (!shown) area.textContent = '当前筛选下没有匹配参数，请更换关键词或选择“全部已识别参数”。';
  for (const g of groups) {
    const div = document.createElement("div");
    div.className = "pgroup";
    div.innerHTML = `<h4>${esc(g.group)} <span class="muted">${g.rows.length} 项</span></h4><table class="ptable"></table>`;
    const tb = div.querySelector("table");
    for (const p of g.rows) {
      const source = (r.param_sources || {})[p.name];
      const csvRadius = source?.kind === 'engineering_csv';
      const d = (r.thirdpart_defaults || {})[p.name];
      const available = !p.read_only && d && d.available && r.values[p.name] !== undefined;
      const reason = r.values[p.name] === undefined ? "当前 XML 没有此字段" : d ? (d.reason || `恢复为：${d.value || "（空）"}；来源：${d.source}`) : "当前项目 ThirdPart 样例没有此参数默认值";
      const defaultButton = csvRadius || p.read_only ? '' : `<button type="button" class="mini param-default" data-default-tag="${attr(p.name)}" ${available ? "" : "disabled"} title="${attr(reason)}">ThirdPart 默认</button>`;
      const v = csvRadius ? (source.values.length === 1 ? source.values[0] : '')
        : p.display_value ?? (r.values[p.name] !== undefined ? r.values[p.name] : (p.default || ""));
      const tr = document.createElement("tr");
      const input = p.read_only ? `<textarea readonly aria-label="${attr(p.name)} 原始配置">${esc(v)}</textarea>` : p.type === "bool"
        ? `<select data-tag="${attr(p.name)}">${!['true','false'].includes(v) ? `<option value="${attr(v)}" selected>当前值：${esc(v) || '（空）'}</option>` : ''}<option ${v === "true" ? "selected" : ""}>true</option><option ${v === "false" ? "selected" : ""}>false</option></select>`
        : `<input data-tag="${attr(p.name)}" value="${attr(v)}" ${csvRadius ? `${source.editable ? '' : 'disabled'} placeholder="${source.values.length > 1 ? '各小区半径不同；填写后统一修改 CSV' : '请在工参 CSV 中配置'}"` : ''}>`;
      const description = csvRadius ? `优先读取工参 CSV 的 ${esc(source.column || 'CalcRadius')} 列；在此填写将统一修改所有小区，逐小区修改请使用工参编辑。<br>` +
        `当前 CSV：${esc(source.values.join(' / ') || '未配置')} 米；XML 默认值：${esc(source.fallback || '未配置')} 米（仅作默认，不随此处修改）。<br>` +
        esc(source.reason || source.path) : esc(p.desc || '');
      const usage = p.usage;
      const badge = usage?.kind === 'startup' ? '仅启动读取' : p.classification === 'other' ? '其他功能/场景' : p.classification === 'unclassified' ? '未分类'
        : usage?.active === false ? '条件未启用' : usage?.kind === 'dependency' ? '功能依赖' : usage?.required ? '强制读取' : '本功能参数';
      const scopeHint = usage ? [usage.required ? '源码强制读取元素' : '',usage.condition ? `条件：${usage.condition}` : '',usage.note,
        usage.source ? `源码依据：${usage.source}` : ''].filter(Boolean).join('；')
        : p.classification === 'unclassified' ? '适用功能尚未确认' : `功能范围：${p.func || '通用'}；场景：${p.applies || 'both'}`;
      tr.innerHTML = `<td title="${attr(p.desc)}">${esc(p.label || p.name)}<br><span class="muted" style="font-size:11px">${esc(p.name)}</span><br><span class="param-badge">${badge}</span></td>
                      <td><div class="param-control">${input}${defaultButton}</div></td>
                      <td>${description}<br><small class="field-help">${esc(scopeHint)}${p.read_only ? `<br>${esc(p.read_only_reason)}` : ''}</small></td>`;
      tb.appendChild(tr);
    }
    area.appendChild(div);
  }
  area.querySelectorAll("input[data-tag],select[data-tag]").forEach(el => {
    el.addEventListener("input", () => markParamDirty(el));
    el.addEventListener("change", () => saveParameter(el, job));
  });
  area.querySelectorAll("button[data-default-tag]").forEach(button => {
    button.onclick = () => restoreParameterDefault(button, job);
  });
}

const parameterDrafts = new Map();
let parameterEditRevision = 0;
const parameterWriteQueue = [];
let parameterQueueRunning = false;
function queueParameterWrite(write) {
  return new Promise(resolve => {
    parameterWriteQueue.push({write, resolve});
    drainParameterWrites();
  });
}
async function drainParameterWrites() {
  if (parameterQueueRunning) return;
  parameterQueueRunning = true;
  try {
    while (parameterWriteQueue.length) {
      const item = parameterWriteQueue.shift();
      try { await item.write(); }
      finally { item.resolve(); }
    }
  } finally { parameterQueueRunning = false; }
}
function editorFailure(result) {
  const reason = result.message || result.error || '保存失败';
  return ['FILE_CONFLICT','REVISION_REQUIRED'].includes(result.code)
    ? `${reason}；草稿已保留，请使用“放弃编辑并重新加载”或“放弃参数编辑”查看最新文件` : reason;
}
function parameterWriteStarted() { parameterRequest++; S.parameterWrites = (S.parameterWrites || 0) + 1; refreshWorkflow(); }
function parameterWriteFinished() { S.parameterWrites = Math.max(0, (S.parameterWrites || 0) - 1); refreshWorkflow(); }
function guardParameterFilter() {
  if (!S.xmlDirty && !S.parameterWrites) return true;
  $('params-scope').value = S.paramsScope || (S.paramsData?.profile?.reviewed ? 'current' : 'all');
  $('params-search').value = S.paramsSearch || '';
  toast('参数有未保存编辑或正在保存，请先点击“保存未保存参数”重试，或“放弃参数编辑”后筛选', false);
  return false;
}
async function savePendingParameters() {
  if (S.parameterWrites || S.runtime?.busy) return;
  const job = S.job;
  for (const el of [...parameterDrafts.keys()]) {
    if (job !== S.job) return;
    await saveParameter(el, job);
  }
}
async function discardParameterChanges() {
  if (!S.job || S.parameterWrites || S.runtime?.busy) return;
  const job = S.job, func = S.func || job.func, epoch = S.projectEpoch;
  const request = ++parameterRequest, revision = parameterEditRevision;
  try {
    const r = await get('params', `schema=${encodeURIComponent(job.schema)}&func=${encodeURIComponent(func)}&all=1`);
    if (job !== S.job || epoch !== S.projectEpoch || func !== (S.func || S.job.func) || request !== parameterRequest || revision !== parameterEditRevision || S.parameterWrites) return;
    if (r.error) return toast(r.error, false);
    parameterDrafts.clear();
    S.xmlDirty = false;
    S.paramsForJob = job;
    renderParams(r);
    refreshWorkflow();
  } catch (error) { toast(error.message, false); }
}
async function restoreParameterDefault(button, job) {
  if (!job || job !== S.job || S.xmlDirty || S.parameterWrites || S.runtime?.busy) return;
  if (button.dataset.defaultTag === 'EngineeringFilePath' && !guardCsvChanges()) return;
  button.disabled = true;
  const epoch = S.projectEpoch;
  parameterWriteStarted();
  try {
    const res = await post('param_default', {schema:job.schema, tag:button.dataset.defaultTag, revision:S.paramsData?.revision});
    if (job !== S.job || epoch !== S.projectEpoch) return;
    if (!res.ok) return toast(editorFailure(res), false);
    if (S.paramsData && res.revision) S.paramsData.revision = res.revision;
    if (job.mode === 'existing' && res.revision) rememberRuntimeRevision(res.revision);
    workflowContentChanged('XML 默认值已保存');
    if (button.dataset.defaultTag === 'EngineeringFilePath' && job.mode === 'existing') await reloadRuntimeEngineering(job);
    if (!S.xmlDirty) await loadParams();
    toast(`${button.dataset.defaultTag} 已写入 ThirdPart 默认值（原文件备份 .bak）`);
  } catch (error) { toast(error.message, false); }
  finally {
    parameterWriteFinished();
    button.disabled = !!S.runtime?.busy || !!S.xmlDirty || !!S.parameterWrites;
  }
}
function markParamDirty(el) {
  if (S.inputTransition) return;
  parameterEditRevision++;
  parameterDrafts.set(el, el.value);
  S.xmlDirty = true;
  el.classList.add('dirty');
  refreshWorkflow();
}
async function saveParameter(el, job) {
  if (S.inputTransition) return;
  if (!job || job !== S.job) return;
  markParamDirty(el);
  if (S.runtime?.busy) return toast('平台正在执行操作，请稍后保存参数', false);
  const tag = el.dataset.tag, value = el.value;
  const source = S.paramsData?.param_sources?.[tag];
  if (tag === 'EngineeringFilePath' && !guardCsvChanges()) return;
  if (source?.kind === 'engineering_csv' && !guardCsvChanges()) return;
  const revision = (el.editorRevision || 0) + 1;
  el.editorRevision = revision;
  const epoch = S.projectEpoch;
  parameterWriteStarted();
  return queueParameterWrite(async () => {
   try {
    if (job !== S.job || epoch !== S.projectEpoch) return;
    const res = await post('param_write', {schema:job.schema, tag, value, revision:S.paramsData?.revision,
      ...(source?.kind === 'engineering_csv' ? {source_revision:source.revision, format_revision:source.format_revision} : {})});
    if (job !== S.job || epoch !== S.projectEpoch) return;
    if (!res.ok) return toast(editorFailure(res), false);
    if (S.paramsData && res.revision) S.paramsData.revision = res.revision;
    if (job.mode === 'existing' && res.revision) rememberRuntimeRevision(res.revision);
    workflowContentChanged(res.target === 'engineering_csv' ? 'CSV 参数已保存' : 'XML 参数已保存');
    if (el.editorRevision === revision && el.value === value) { parameterDrafts.delete(el); el.classList.remove('dirty'); }
    S.xmlDirty = parameterDrafts.size > 0;
    if (tag === 'EngineeringFilePath' && S.job?.mode === 'existing') {
      await reloadRuntimeEngineering(job);
    }
    if (S.paramsData?.values && res.target !== 'engineering_csv') S.paramsData.values[tag] = value;
    for (const group of S.paramsData?.groups || []) {
      for (const row of group.rows) if (row.name === tag) row.display_value = value;
    }
    if (res.target === 'engineering_csv') {
      csvRequest++;
      if (source) { source.values = [value]; if (res.source_revision) source.revision = res.source_revision; }
      if (!S.csvDirty) { csvData = null; $('csv-wrap').textContent = '计算半径已写入 CSV，请重新加载查看'; }
    }
    refreshWorkflow();
    toast(res.target === 'engineering_csv' ? res.message : `${tag} 已写入 ${job.schema}（原文件备份 .bak）`);
   } catch (error) { toast(error.message, false); }
   finally { parameterWriteFinished(); }
  });
}

/* ---------------- 工参 CSV ---------------- */

let csvData = null;
let csvRequest = 0, csvEditRevision = 0, csvWriting = false;
function refreshCsvDirtyState() {
  const status = $('csv-dirty-status'), discard = $('btn-csv-discard');
  if (status) status.textContent = S.csvDirty ? 'CSV 有未保存编辑；请保存或明确放弃后继续。' : '';
  if (discard) { discard.hidden = !S.csvDirty; discard.classList[S.csvDirty ? 'remove' : 'add']('hidden'); }
  const msg = $('csv-msg');
  if (S.csvDirty && msg) msg.textContent = 'CSV 有未保存编辑；请保存或明确放弃后继续。';
  refreshWorkflow();
}
function markCsvDirty() {
  if (S.inputTransition) return;
  S.csvDirty = true;
  csvEditRevision++;
  refreshCsvDirtyState();
}
function guardCsvChanges() {
  if (!S.csvDirty) return true;
  focusStage('inputs');
  const editor = $('csv-editor') || $('csv-wrap');
  if (editor) editor.open = true;
  if (editor?.focus) editor.focus();
  refreshCsvDirtyState();
  toast('请先保存 CSV，或点击“放弃编辑并重新加载”后继续', false);
  return false;
}
async function discardCsvChanges() { return loadCsv(true); }
async function loadCsv(discard = false, afterWrite = false) {
  if (csvWriting && !afterWrite) return toast('CSV 正在保存，请稍候', false);
  if (discard !== true && !guardCsvChanges()) return;
  const path = $('csv-path').value, epoch = S.projectEpoch, job = S.job;
  if (!path) return toast('没有 CSV 路径，先在左侧选任务', false);
  const request = ++csvRequest, revision = csvEditRevision;
  try {
    const data = await get('csv', `path=${encodeURIComponent(path)}${job ? `&schema=${encodeURIComponent(job.schema)}` : ''}`);
    if (request !== csvRequest || epoch !== S.projectEpoch || job !== S.job || path !== $('csv-path').value || revision !== csvEditRevision) return;
    if (data.error) return toast(data.error, false);
    csvData = data;
    S.csvDirty = false;
    renderCsv();
    refreshCsvDirtyState();
    return true;
  } catch (error) { toast(error.message, false); }
}
function renderCsv() {
  const mk = (row, tag) => row.map(c => `<${tag}>${esc(c)}</${tag}>`).join('');
  const headers = csvData.header_rows || [csvData.header_zh || [], csvData.header_en || []];
  const editable = csvData.editable !== false;
  const head = headers.map(row => `<tr>${mk(row, 'td')}</tr>`).join('');
  const body = csvData.rows.map((row,i) => `<tr data-i="${i}">${row.map(c => `<td${editable ? ' contenteditable' : ''}>${esc(c)}</td>`).join('')}</tr>`).join('');
  $('csv-wrap').innerHTML = `<table>${head}${body}</table>`;
  $('csv-wrap').oninput = editable ? markCsvDirty : null;
  $('csv-msg').textContent = `编码 ${csvData.encoding} · ${headers.length} 行表头 · ${csvData.rows.length} 行数据` +
    (editable ? '' : ` · 只读：${csvData.read_only_reason || '工参格式未确认'}`);
}
async function saveCsv() {
  if (!csvData || csvData.editable === false || csvWriting || S.runtime?.busy || S.parameterWrites) return;
  const data = csvData, path = $('csv-path').value, epoch = S.projectEpoch, revision = csvEditRevision;
  const table = $('csv-wrap').querySelector('table');
  if (!table) return;
  const trs = table.querySelectorAll('tr'), grab = tr => [...tr.children].map(td => td.textContent);
  const headerCount = data.header_rows?.length ?? data.header_lines ?? 2;
  const headers = [...trs].slice(0,headerCount).map(grab);
  const body = {path:data.path, schema:S.job?.schema || '', revision:data.revision, format_revision:data.format_revision,
    header_rows:headers, header_lines:headerCount, header_zh:headers[0] || [], header_en:headers[1] || [],
    rows:[...trs].slice(headerCount).map(grab)};
  csvWriting = true;
  csvRequest++;
  try {
    const r = await post('csv_save', body);
    if (data !== csvData || path !== $('csv-path').value || epoch !== S.projectEpoch) return;
    if (r.ok) {
      if (r.revision) data.revision = r.revision;
      workflowContentChanged('CSV 已保存');
      if (revision === csvEditRevision) { S.csvDirty = false; Object.assign(csvData,{header_rows:headers,header_lines:headerCount,rows:body.rows}); }
      updateRadiusVersion({...data, rows:body.rows}, r.revision);
    }
    $('csv-msg').textContent = r.ok ? r.message || 'CSV 已保存' : editorFailure(r);
    refreshCsvDirtyState();
    toast(r.ok ? 'CSV 已保存（原文件备份 .bak）' : editorFailure(r), r.ok);
  } catch (error) { toast(error.message, false); }
  finally { csvWriting = false; }
}
function updateRadiusVersion(data, revision) {
  parameterRequest++;
  const source = S.paramsData?.param_sources?.DefaultCalcRadius;
  const radiusDraft = [...parameterDrafts.keys()].some(el => el.dataset.tag === 'DefaultCalcRadius');
  if (source?.path === data.path && revision && !radiusDraft) {
    source.revision = revision;
    const index = source.column_index;
    if (Number.isInteger(index)) {
      source.values = [...new Set(data.rows.filter(row=>row.some(Boolean)).map(row=>row[index] || ''))];
      $('params-area').querySelectorAll('input[data-tag="DefaultCalcRadius"]').forEach(el => {
        el.value = source.values.length === 1 ? source.values[0] : '';
        el.placeholder = source.values.length > 1 ? '各小区半径不同；填写后统一修改 CSV' : '请在工参 CSV 中配置';
      });
    }
  }
}
async function setColumn() {
  if (!csvData || csvData.editable === false || csvWriting || !guardCsvChanges() || S.runtime?.busy || S.parameterWrites) return;
  const data = csvData, path = $('csv-path').value, epoch = S.projectEpoch;
  const col = $('csv-col').value.trim(), val = $('csv-val').value;
  if (!col) return toast('填列名', false);
  const revision = csvEditRevision;
  csvWriting = true;
  csvRequest++;
  try {
    const r = await post('csv_column', {path:data.path, schema:S.job?.schema || '', column:col,value:val,
      revision:data.revision,format_revision:data.format_revision});
    if (data !== csvData || path !== $('csv-path').value || epoch !== S.projectEpoch) return;
    $('csv-msg').textContent = r.ok ? r.message || '' : editorFailure(r);
    if (r.ok) {
      data.revision = null;
      workflowContentChanged('CSV 整列已保存');
      // A draft typed while the column request was pending stays based on the
      // earlier grid and must be reloaded explicitly before overwriting it.
      if (revision !== csvEditRevision) {
        data.revision = null;
        toast('整列已写入；期间输入的草稿已保留，请重新加载后核对', false);
        return;
      }
      const loaded = await loadCsv(false, true);
      if (loaded && csvData !== data) {
        updateRadiusVersion(csvData, csvData.revision);
        toast('整列已设置并保存');
      } else toast('整列已写入；表格尚未刷新，草稿已保留，请重新加载后核对', false);
    } else toast(editorFailure(r), false);
  } catch (error) { toast(error.message, false); }
  finally { csvWriting = false; }
}
