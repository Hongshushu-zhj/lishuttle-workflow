/* task-assembly — plain script; shared application state is composed in app.js. */
"use strict";

function fillSelect(sel, items, current) {
  sel.innerHTML = items.map(p =>
    `<option value="${esc(p).replace(/"/g, "&quot;")}" ${p === current ? "selected" : ""}>${esc(p.split(/[\\/]/).pop())}</option>`).join("");
}

/* ---------------- 左侧：城市与任务 ---------------- */

async function rescanMap() {
  if (!guardCsvChanges() || S.xmlDirty) return toast('请先保存未完成的编辑',false);
  const r = await post("set_map_root", { path: $("map-root").value });
  if (r.error) return toast(r.error, false);
  S.profileRevision = r.profile_revision || S.profileRevision;
  S.projectConfig.MAP_ROOT = $("map-root").value;
  if (S.projectDraft) S.projectDraft.MAP_ROOT = S.projectConfig.MAP_ROOT;
  renderProjectConfig();
  renderCities(r.cities);
  S.city = null;
  refreshLocalPaths({});
  S.job = null;
  updateNote();
  toast(`识别到 ${r.cities.length} 个城市/场景`);
}

async function rescanTasks() {
  if (!guardCsvChanges() || S.xmlDirty) return toast('请先保存未完成的编辑',false);
  const r = await post("set_gongcan_root", { path: $("gongcan-root").value });
  if (r.error) return toast(r.error, false);
  S.profileRevision = r.profile_revision || S.profileRevision;
  S.projectConfig.GONGCAN_ROOT = $("gongcan-root").value;
  if (S.projectDraft) S.projectDraft.GONGCAN_ROOT = S.projectConfig.GONGCAN_ROOT;
  renderProjectConfig();
  renderTasks(r.tasks);
  S.job = null;
  toast(`识别到 ${r.tasks.length} 个任务`);
}

const KIND_CN = { outdoor: "室外", indoor: "室内", unknown: "未识别" };

// -f 功能的中文名与说明（源自 readme.txt、笔记和实测）
const FUNC_INFO = {
  test:        { zh: "基本检测",   desc: "检查程序能否运行，显示授权可用日期（-c 可不给）" },
  debug:       { zh: "内部调试",   desc: "DebugEngine 内部测试功能，开发调试用" },
  pl:          { zh: "路损计算",   desc: "逐小区计算传播路损，输出 .loss/.pene 文件" },
  pred:        { zh: "室外覆盖预测", desc: "室外覆盖预测(RSRP/SINR，输出 pred 目录 BESTSERVER/RSRP/DLRSSINR)。室内预测请用 predindoor" },
  plindoor:    { zh: "室内路损",   desc: "室内路损计算，输出 .ils 射线路损数据" },
  predindoor:  { zh: "室内覆盖预测", desc: "室内覆盖预测(-f predindoor)，室内预测只用这个" },
  rays:        { zh: "室外射线",   desc: "记录室外射线数据。运行前需在参数里把 RaySpectrumSaved 改 true" },
  indoorrays:  { zh: "室内射线",   desc: "记录室内射线数据，配室内运行单" },
  dt:          { zh: "路测分析",   desc: "路测数据分析，需要路测数据目录(DriverTestFileDictionaryPath)" },
  cali:        { zh: "模型校正",   desc: "传播模型校正(K0/Knear/Kfar/衍射/反射系数)，需要路测数据" },
  acp:         { zh: "参数优化",   desc: "粒子群自动优化下倾角/方位角/功率等（ACP）" },
  ai:          { zh: "AI训练",     desc: "智能传播模型训练，需要 Python 运行时（pyAndsh 脚本）" },
  scene:       { zh: "场景分类",   desc: "场景分类，唯一不加载全部子系统的功能" },
  debugbuild:  { zh: "穿损详算",   desc: "计算并输出建筑物穿透损耗详细数据" },
  commsensing: { zh: "通感一体化", desc: "通感一体化预测。工参必须是44列(含感知列)，常规固定 -t 0" },
};

function renderCities(cities) {
  S.cities = cities;
  const out = cities.filter(c => c.kind === "outdoor");
  const ind = cities.filter(c => c.kind === "indoor");
  const item = (c) => {
    const bad = c.checks.filter(k => !k[2]).length;
    const mark = bad ? `<span class="mark">缺${bad}项</span>` : `<span class="mark">✔</span>`;
    return `<div class="city" data-name="${c.name}"><span>${c.name}</span>${mark}</div>`;
  };
  $("city-list").innerHTML =
    (out.length ? `<div class="panel-title" style="margin-top:4px">室外城市</div>` : "") +
    out.map(item).join("") +
    (ind.length ? `<div class="panel-title" style="margin-top:8px">室内场景</div>` : "") +
    ind.map(item).join("");
  document.querySelectorAll("#city-list .city").forEach(el => el.onclick = () => {
    if (S.inputTransition || !guardCsvChanges() || S.xmlDirty || S.runtime?.busy) return;
    document.querySelectorAll("#city-list .city").forEach(e => e.classList.remove("sel"));
    el.classList.add("sel");
    S.city = cities.find(c => c.name === el.dataset.name);
    updateNote();
    refreshLocalPaths({});
    if (S.city.kind === "indoor" && !(["plindoor", "predindoor", "indoorrays"]).includes(S.func))
      renderFuncRadios("predindoor");
    else if (S.city.kind === "outdoor" && ["plindoor", "predindoor", "indoorrays"].includes(S.func))
      renderFuncRadios("pred");
  });
}

function renderTasks(tasks) {
  S.tasks = tasks;
  S.task = null;
  updateAntennaOption();
  $("use-existing-schema").checked = false;
  $("use-existing-schema").disabled = true;
  $("schema-source").replaceChildren();
  $("sync-engineering").checked = false;
  updateSchemaMode();
  $("engineering-path").replaceChildren();
  $("engineering-path").disabled = true;
  $("engineering-reason").textContent = "先选择工参任务";
  $("csv-path").replaceChildren();
  clearCsvEditor();
  updateNote();
  $("task-list").innerHTML = tasks.map(t =>
    `<div class="task" data-name="${t.name}">
       <span>${t.name}</span><span class="badge ${t.kind}">${KIND_CN[t.kind]}</span>
     </div>`).join("") || `<span class="muted">（未识别到任务）</span>`;
  document.querySelectorAll("#task-list .task").forEach(el => el.onclick = async () => {
    if (S.inputTransition || !guardCsvChanges() || S.xmlDirty || S.runtime?.busy) return;
    document.querySelectorAll("#task-list .task").forEach(e => e.classList.remove("sel"));
    el.classList.add("sel");
    S.task = tasks.find(t => t.name === el.dataset.name);
    updateAntennaOption();
    const candidates = S.task.engineering_candidates || [];
    for (const id of ["engineering-path", "csv-path"]) {
      const sel = $(id);
      sel.replaceChildren(new Option(candidates.length ? "请选择工参 CSV" : "未识别到有效工参", ""));
      candidates.forEach(p => sel.add(new Option(p.slice(S.task.dir.length + 1), p)));
      sel.disabled = !candidates.length;
    }
    selectEngineering(S.task.engineering_file || "", false);
    const schemas = S.task.schema_candidates || [];
    $("use-existing-schema").checked = false;
    $("use-existing-schema").disabled = !schemas.length;
    $("sync-engineering").checked = false;
    $("schema-source").replaceChildren(new Option(schemas.length ? "请选择运行配置 XML" : "未识别到运行配置 XML", ""));
    schemas.forEach(c => $("schema-source").add(new Option(
      `${c.path.slice(S.task.dir.length + 1)} · name=${c.name} · ${KIND_CN[c.kind]}`, c.path)));
    if (schemas.length === 1) $("schema-source").value = schemas[0].path;
    $("schema-polygon").replaceChildren(new Option("不使用区域（将 PolygonFilePath 设为空）", ""));
    (S.task.txts || []).forEach(p => $("schema-polygon").add(new Option(p.slice(S.task.dir.length + 1), p)));
    updateSchemaMode();
    refreshLocalPaths({});
    restoreTaskBinding();
    if (!$("job-name").value) $("job-name").value = `${S.task.name}-${S.func}`;
    refreshWorkflow();
  });
}

let schemaPreviewRevision = 0;
let schemaPreview = null;
let schemaSubmissionPending = false;
function schemaPreviewContext() {
  return JSON.stringify({project:S.project, epoch:S.projectEpoch, revision:S.profileRevision,
    machineRevision:S.machineRevision, config:S.projectConfig, draft:S.projectDraft,
    func:S.func, city:S.city, task:S.task,
    fields:['job-name','task-id','schema-source','schema-polygon'].map(id=>$(id).value),
    flags:['use-existing-schema','sync-engineering','copy-files','copy-antennas'].map(id=>$(id).checked),
    paths:collectLocalPaths()});
}
function schemaPreviewCurrent(record = schemaPreview) {
  return !!record && record === schemaPreview && record.revision === schemaPreviewRevision &&
    record.context === schemaPreviewContext();
}
function refreshSchemaApplyState() {
  const valid = schemaPreviewCurrent();
  const reason = !valid ? '请重新预览当前配置' : schemaSubmissionPending ? '正在装配，请稍候' :
    S.inputTransition || S.runtime?.busy || S.assemblyPending ? '平台正在执行操作，请等待空闲' : S.csvDirty || S.xmlDirty ? '请先保存未完成的编辑' : '';
  $('btn-apply-schema').disabled = !!reason;
  $('btn-apply-schema').title = reason;
  $('schema-apply-status').textContent=reason || '预览有效，可以确认装配';
  return !reason;
}
function updateAntennaOption() {
  const available = !!(S.task && S.task.has_antennas);
  $("antenna-option").classList.toggle("hidden", !available);
  $("copy-antennas").disabled = !available;
  $("copy-antennas").checked = available;
}

function invalidateSchemaPreview() {
  schemaPreviewRevision++;
  schemaPreview = null;
  bindingRevision++;
  $("schema-preview").classList.add("hidden");
  refreshSchemaApplyState();
  refreshWorkflow();
}

function updateSchemaMode() {
  const reuse = $("use-existing-schema").checked;
  $("schema-source").disabled = !reuse;
  $("sync-engineering").disabled = !reuse;
  $("copy-files").disabled = reuse;
  $("existing-schema-options").classList.toggle("hidden", !reuse);
  $("btn-render").textContent = reuse ? "预览路径修改" : "装配并渲染";
  invalidateSchemaPreview();
  refreshLocalPaths();
}

function clearCsvEditor() {
  csvData = null;
  S.csvDirty=false; parameterDrafts.clear(); S.xmlDirty=false;
  refreshCsvDirtyState();
  $("csv-wrap").textContent = "工参选择已更新，请点击加载";
  $("csv-msg").textContent = "";
}

function selectEngineering(path, manual) {
  if (!S.task) return;
  if (S.inputTransition || !guardCsvChanges() || S.xmlDirty) {
    if(S.xmlDirty) toast('请先保存或放弃未保存的参数编辑',false);
    $('engineering-path').value=S.task.engineering_file || '';
    $('csv-path').value=S.task.engineering_file || ''; return;
  }
  S.task.engineering_file = path;
  $("engineering-path").value = path;
  $("csv-path").value = path;
  S.task.kind = (S.task.engineering_kinds || {})[path] || "unknown";
  S.task.detect = manual && path ? "手动选择，工参表头已识别" : S.task.engineering_reason;
  $("engineering-reason").textContent = path
    ? `${S.task.detect} · ${path}` : S.task.engineering_reason;
  clearCsvEditor();
  updateNote();
  if (manual) { refreshLocalPaths({}); restoreTaskBinding(); }
}

const LOCAL_PATH_LABELS = {
  SceneSettingsPath:'场景配置', DriverTestFileDictionaryPath:'路测目录',
  ClutterMatchPath:'杂波匹配配置', BulidVectorIndexPath:'建筑矢量索引（支持特殊索引）',
  ProjectionFilePath:'投影文件', HeightIndexPath:'高程索引', ClutterIndexPath:'杂波索引',
  ClutterMenuPath:'杂波菜单', BuildingIndexPath:'建筑索引', MapPath:'室内地图目录',
  PathlossDirectory:'输出根目录',
};
let localPathRevision = 0;
function renderLocalPaths(saved = {}, defaults = S.localPathDefaults || {}) {
  const schema = (S.task?.schema_candidates || []).find(item => item.path === $("schema-source").value);
  const originals = schema?.path_values || {};
  $("local-path-fields").innerHTML = Object.entries(LOCAL_PATH_LABELS)
    .filter(([tag]) => tag in originals || tag in saved || tag in defaults).map(([tag, label]) =>
      `<label>${label}<span class="field-help">原：${esc(originals[tag] || '（空）')}</span>` +
      `<input class="path" data-local-path-tag="${tag}" data-auto-path="${attr(defaults[tag])}" value="${attr(saved[tag] ?? defaults[tag])}" placeholder="${attr(S.localPathIssues?.[tag] || '自动识别后填入；也可手动指定本机路径')}">` +
      (S.localPathIssues?.[tag] ? `<span class="field-help local-path-issue">${esc(S.localPathIssues[tag])}</span>` : '') + '</label>').join('');
  $("local-path-fields").querySelectorAll?.('input').forEach(input => input.oninput = () => {
    localPathRevision++;
    invalidateSchemaPreview();
  });
}
async function refreshLocalPaths(saved) {
  const overrides = saved === undefined ? collectLocalPaths() : saved;
  const revision = ++localPathRevision, epoch = S.projectEpoch, task = S.task;
  const city = S.city?.name, schema = $("schema-source").value, engineering = S.task?.engineering_file;
  S.localPathDefaults = {};
  S.localPathIssues = {};
  renderLocalPaths(overrides);
  const status = $("local-path-status");
  if (!S.profileId || !task || !city || !schema) {
    status.textContent = !city ? '请先在左侧选择地图；已保存的对应关系恢复后会自动识别。' :
      !task ? '请先选择工参任务。' : !schema ? '请选择任务运行配置 XML。' : '请先选择项目。';
    return;
  }
  status.textContent = '正在识别当前项目的本地资源路径…';
  const current = () => revision === localPathRevision && epoch === S.projectEpoch && task === S.task &&
    city === S.city?.name && schema === $("schema-source").value && engineering === S.task?.engineering_file;
  try {
    const result = await post('local_paths', {task, city, schema_source:schema, engineering_file:engineering});
    if (!current()) return;
    if (result.error) {
      status.textContent = `本地路径识别失败：${result.error}`;
      return toast(result.error, false);
    }
    S.localPathDefaults = result.values || {};
    S.localPathIssues = result.unresolved || {};
    renderLocalPaths(overrides);
    const count = Object.values(S.localPathDefaults).filter(Boolean).length;
    status.textContent = `已自动识别 ${count} 项本地路径。` +
      Object.values(S.localPathIssues).concat(result.warnings || []).join('；');
    if (result.warnings?.length) toast(result.warnings.join('；'), false);
  } catch (error) {
    if (current()) {
      status.textContent = `本地路径识别失败：${error.message}`;
      toast(status.textContent, false);
    }
  }
}
function collectLocalPaths() {
  const values = {};
  $("local-path-fields").querySelectorAll?.('[data-local-path-tag]').forEach(input => {
    const tag = input.dataset.localPathTag, value = input.value.trim();
    if (tag in LOCAL_PATH_LABELS && value && value !== (input.dataset.autoPath || '')) values[tag] = value;
  });
  return values;
}
function bindingBody() {
  return {task:S.task, engineering_file:S.task?.engineering_file || '',
    schema_source:$("schema-source").value, city:S.city?.name || '',
    path_overrides:collectLocalPaths(), sync_engineering:$("sync-engineering").checked,
    polygon_file:$("schema-polygon").value};
}
let bindingRevision = 0;
async function restoreTaskBinding() {
  if (!S.profileId || !S.task) return;
  const epoch = S.projectEpoch, task = S.task, revision = ++bindingRevision;
  const body = bindingBody();
  const r = await post('task_binding', body);
  if (epoch !== S.projectEpoch || task !== S.task || revision !== bindingRevision) return;
  if (body.engineering_file !== S.task.engineering_file || body.schema_source !== $("schema-source").value) return;
  if (r.error) { $("task-binding-note").textContent = r.error; return; }
  const binding = r.binding;
  if (!binding) { $("task-binding-note").textContent = '当前工参尚未保存地图对应关系，请选择地图后保存。'; return; }
  const city = S.cities.find(c => c.name === binding.city);
  if (!city) { S.city = null; updateNote(); $("task-binding-note").textContent = '已保存的地图不存在，请重新选择并保存对应关系。'; return; }
  S.city = city;
  document.querySelectorAll('#city-list .city').forEach(node => node.classList.toggle('sel', node.dataset.name === city.name));
  $("sync-engineering").checked = !!binding.sync_engineering;
  $("schema-polygon").value = binding.polygon_file || binding.path_overrides?.PolygonFilePath || '';
  renderLocalPaths(binding.path_overrides || {});
  await refreshLocalPaths(binding.path_overrides || {});
  if (epoch !== S.projectEpoch || task !== S.task || revision !== bindingRevision || S.city !== city) return;
  updateNote();
  $("task-binding-note").textContent = `已恢复当前项目对应关系：${city.name}；路径将在渲染前重新检查。`;
}
async function saveTaskBinding() {
  if (!S.task?.engineering_file || !S.city) return toast('请先选择有效工参及对应地图', false);
  const epoch = S.projectEpoch;
  const r = await post('save_task_binding', bindingBody());
  if (epoch !== S.projectEpoch) return;
  if (r.error) return toast(r.error, false);
  $("task-binding-note").textContent = '当前项目的工参、地图和本地路径对应关系已保存。';
  toast('工参与地图对应关系已保存');
}

function updateNote() {
  renderWorkflowGuide();
  invalidateSchemaPreview();
  const c = S.city ? `${S.city.kind === "indoor" ? "室内场景" : "城市"} ${S.city.name}` : "未选地图";
  const t = S.task ? `任务 ${S.task.name}（${KIND_CN[S.task.kind]}，${S.task.detect}）` : "未选任务";
  $("selection-note").textContent = `已选：${c} · ${t}`;
  if (S.job) $("run-info").textContent = taskIdentityDirty()
    ? '任务设置已修改，请重新装配后运行'
    : `${S.job.name}.xml · -f ${S.job.func} -t ${S.job.taskId}${S.job.outDir ? ` · 实际输出：${S.job.outDir}` : ""}`;
}

/* ---------------- 功能选择 ---------------- */

function renderFuncRadios(current) {
  S.func = current;
  $("func-radios").innerHTML = [...S.functions].sort((a,b)=>{const main=["pred","commsensing","predindoor","cali"];return (main.includes(a)?main.indexOf(a):99)-(main.includes(b)?main.indexOf(b):99);}).map(f => {
    const srv = (S.functionInfo || {})[f];
    const loc = FUNC_INFO[f];
    const zh = srv ? srv.label : (loc ? loc.zh : "");
    const desc = srv ? srv.desc : (loc ? loc.desc : "");
    return `<label title="${desc}"><input type="radio" name="func" value="${f}" ${f === current ? "checked" : ""}>${f}${zh ? ` <span class="fzh">${zh}</span>` : ""}</label>`;
  }).join("");
  showFuncHint(current);
  document.querySelectorAll('#func-radios input').forEach(r => r.onchange = () => {
    if (S.inputTransition || !guardCsvChanges() || S.xmlDirty || S.runtime?.busy) { renderFuncRadios(S.func); return; }
    S.func = r.value;
    showFuncHint(r.value);
    updateNote();

  });
}

function showFuncHint(f) {
  const srv = (S.functionInfo || {})[f];
  const info = srv ? { zh: srv.label, desc: srv.desc } : FUNC_INFO[f];
  if (info) $("hint").textContent = `-f ${f} ${info.zh}：${info.desc}`;
}

/* ---------------- 渲染与参数 ---------------- */

async function doRender() {
  if (S.inputTransition) return;
  if(S.assemblyPending) return;
  S.assemblyPending=true; refreshWorkflow();
  try { return await prepareAssembly(); }
  finally { S.assemblyPending=false; refreshWorkflow(); }
}
async function prepareAssembly() {
  if (!guardCsvChanges() || S.xmlDirty) return toast("请先保存或放弃未保存的编辑",false);
  if (S.inputTransition || S.runtime?.busy || schemaSubmissionPending) return toast("平台正忙，请稍候",false);
  if (S.profileId) {
    const epoch = S.projectEpoch;
    const validation = await post('validate_setup',{operation:'render'});
    if (epoch !== S.projectEpoch) return;
    if (validation.error || validation.issues?.length) return setupError(validation);
    if (BUILD_KEYS.some(key=>(S.projectDraft?.[key] || '') !== (S.projectConfig?.[key] || '')))
      return focusSetupIssue({target:'btn-build',section:'build',message:'当前构建选择尚未应用，请编译所选配置，或使用已识别程序后重新装配'});
    const unsaved = ['CONFIG_SRC','DLL_SRC','MAP_ROOT','GONGCAN_ROOT','OUT_ROOT'].find(key=>(S.projectDraft?.[key] || '') !== (S.projectConfig?.[key] || ''));
    if (unsaved) return focusSetupIssue({key:unsaved,target:'config-'+unsaved,section:'project',message:`${PROFILE_LABELS[unsaved]}已修改，请先保存当前项目配置`});
  }
  const missing = (target,message) => focusSetupIssue({target,section:'input',message});
  if (!S.city) return missing('city-list','先在左侧选择城市/场景');
  if (!S.task) return missing('task-list','先在左侧选择工参任务');
  const reuse = $("use-existing-schema").checked;
  if ((!reuse || $("sync-engineering").checked) && !S.task.engineering_file)
    return missing('engineering-path',S.task.engineering_reason || '请选择装配工参');
  if (reuse && !$("schema-source").value) return missing('schema-source','请选择已有运行配置 XML');
  const jobName = $("job-name").value.trim();
  if (!jobName) return missing('job-name','先填任务名');
  const body = {
    job_name: jobName, func: S.func, task_id: $("task-id").value || "1",
    task: JSON.parse(JSON.stringify(S.task)), city: S.city.name, city_kind: S.city.kind,
    engineering_file: S.task.engineering_file,
    copy_files: !reuse && $("copy-files").checked,
    copy_antennas: !!S.task.has_antennas && $("copy-antennas").checked,
    use_existing_schema: reuse, schema_source: $("schema-source").value,
    sync_engineering: $("sync-engineering").checked, polygon_file: $("schema-polygon").value,
    path_overrides: collectLocalPaths(),
    previous_schema: S.job?.schema || '',
  };
  if (reuse) {
    invalidateSchemaPreview();
    const revision = schemaPreviewRevision;
    const context = schemaPreviewContext();
    let p;
    try { p = await post("preview_render", body); }
    catch (error) { if (revision === schemaPreviewRevision) toast(`预览失败：${error.message}，请重新预览`, false); return; }
    if (revision !== schemaPreviewRevision || context !== schemaPreviewContext()) return;
    if (p.error) return setupError(p);
    $("schema-preview-text").textContent =
      `源文件：${p.source}\n目标文件：${p.destination}\n任务 name：${p.runtime_name}\n实际输出目录：${p.out_dir}\n` +
      `覆盖已有目标前备份为 .bak。源文件保持不变。\n\n` +
      `确认后自动补齐当前项目 ThirdPart 基础运行资源，保留已存在文件。\n\n` +
      (body.copy_antennas ? `另装配任务天线：${S.task.antenna_dir || S.task.antenna || "无任务天线，将按现有规则恢复项目默认天线 XML"}\n\n` : "不装配天线，保留项目现有天线文件。\n\n") +
      p.changes.map(c => `${c.tag}\n  原：${c.old || "（空）"}\n  新：${c.new || "（空）"}`).join("\n") +
      (p.warnings.length ? "\n\n提示：\n" + p.warnings.join("\n") : "");
    $("schema-preview").classList.remove("hidden");
    const record = {revision, context, body:JSON.parse(JSON.stringify(body)), token:p.token};
    schemaPreview = record;
    refreshSchemaApplyState();
    $('btn-apply-schema').onclick = async () => {
      if (!schemaPreviewCurrent(record)) {
        if (schemaPreview === record) invalidateSchemaPreview();
        return;
      }
      if (!refreshSchemaApplyState()) return;
      schemaSubmissionPending = true;
      refreshWorkflow();
      try {
        const outcome = await submitRender({...record.body, preview_token:record.token}, record);
        if (['applied','preview_stale','outcome_unknown'].includes(outcome.status) && schemaPreview === record)
          invalidateSchemaPreview();
      } finally {
        schemaSubmissionPending = false;
        refreshWorkflow();
      }
    };
    return;
  }
  await submitRender(body);
}

async function submitRender(body, previewRecord = null) {
  const epoch = S.projectEpoch;
  const sentContext=schemaPreviewContext();
  const jobName = body.job_name;
  S.assemblyUnconfirmed=true;
  if(S.workflow) S.workflow={...S.workflow,assembled:null,preflight:null,staleReason:'装配结果尚未确认，请完成装配后再运行'};
  refreshWorkflow();
  let r;
  try { r = await post("render", body); }
  catch (error) {
    toast(`装配请求中断，结果待核对：${error.message}。请核对状态并重新预览后再确认`, false);
    return {status:'outcome_unknown'};
  }
  if (epoch !== S.projectEpoch || sentContext !== schemaPreviewContext() || (previewRecord && !schemaPreviewCurrent(previewRecord))) return {status:'preview_stale'};
  if (r.error) {
    if (r.code === 'RUNTIME_BUSY' && !r.runtime) applyRuntimeState({...S.runtime, busy:true});
    setupError(r);
    return {status:r.code === 'PREVIEW_STALE' ? 'preview_stale' : r.code === 'RUNTIME_BUSY' ? 'runtime_busy' : 'retryable_error'};
  }
  const ro = $("render-output");
  ro.classList.remove("hidden");
  const base = r.base_resources;
  const baseLog = base ? `基础运行资源：补齐 ${base.copied.length} 个文件，保留 ${base.kept_count} 个已有文件\n` +
    `配置来源：${base.config_source}\n动态库来源：${base.dll_source}\n目标：${base.exe_dir}\n` +
    base.copied.map(c => `${c.from} → ${c.to}`).join("\n") + "\n\n" : "";
  const launch = r.vs_launch;
  const launchLog = launch ? `\n\nVisual Studio 启动项：${launch.path}\n` +
    launch.entries.join("\n") + (launch.backup ? `\n原文件备份：${launch.backup}` : "") : "";
  ro.textContent = baseLog + (r.render_output || "(无输出)") + launchLog +
    (r.vs_launch_warning ? `\n\n${r.vs_launch_warning}` : "");
  if (!r.schema_ok) {
    toast("渲染失败：没生成运行单，看下方输出", false);
    return {status:"retryable_error"};
  }
  if (r.render_exit !== 0) {
    toast("运行单已生成，但有输入文件缺失（下方标 [缺失]）——参数面板仍可改路径", false);
  }

  S.job = { name: jobName, schema: r.schema_name, func: r.func, taskId: r.task_id, outDir: r.out_dir };
  resetCleanupPreview();
  markWorkflowAssembled(S.job);
  taskIdentityChanged();
  $('result-job').value = r.runtime_name || jobName;
  const copied = (r.copied || []).map(c => `${c.file} → ${c.to} ${c.backup}`).join("\n");
  toast(`渲染完成：${r.schema_name}${copied ? "\n已替换：" + copied : ""}`);
  if (r.vs_launch_warning) toast(r.vs_launch_warning, false);
  updateNote();
  switchTab(document.querySelector('[data-tab="params"]'));
  loadParams();
  return {status:"applied"};
}


function taskIdentityDirty() {
  if(S.job && S.assemblyUnconfirmed) return true;
  if (S.workflow?.assembled && !workflowStatus().assemblyCurrent) return true;
  return !!S.job && ($('job-name').value.trim() !== S.job.name ||
    ($('task-id').value || '1') !== String(S.job.taskId));
}

function taskIdentityChanged() {
  const dirty = taskIdentityDirty();
  $('task-name-note').textContent = dirty
    ? '任务名或任务 ID 已修改，请重新装配；运行 XML、输出子目录和 VS 启动项将在装配成功后同步。'
    : '装配后同步运行 XML 名称、输出子目录和 Visual Studio 启动项；修改后需重新装配。';
  if (dirty) $('run-info').textContent = '任务设置已修改，请重新装配后运行';
  else if (S.job) $('run-info').textContent = `${S.job.schema} · -f ${S.job.func} -t ${S.job.taskId}` +
    (S.job.outDir ? ` · 实际输出：${S.job.outDir}` : '');
  resetCleanupPreview();
}

let cleanupRevision = 0;
let cleanupRecord = null, cleanupPending = false;
function refreshCleanupState() {
  const valid=cleanupRecord && cleanupRecord.epoch === S.projectEpoch && cleanupRecord.revision === cleanupRevision;
  $('btn-cleanup-apply').disabled=!valid || !cleanupRecord.count || cleanupPending || !!S.inputTransition || !!S.runtime?.busy || !!S.pollTimer;
}
function resetCleanupPreview() {
  cleanupRevision++;
  cleanupRecord=null;
  $('cleanup-preview').classList.add('hidden');
  refreshCleanupState();
  $('cleanup-note').textContent = '';
}

async function previewCleanup() {
  if (S.inputTransition) return;
  if (S.runtime?.busy || S.pollTimer || S.pendingRequests) return toast('请等待当前操作结束再清理', false);
  resetCleanupPreview();
  const revision = cleanupRevision, epoch = S.projectEpoch;
  const keep = S.job?.schema || '';
  const r = await post('cleanup_configs', {keep_schema: keep});
  if (epoch !== S.projectEpoch || revision !== cleanupRevision) return;
  if (r.error) return toast(r.error, false);
  $('cleanup-preview-text').textContent = `保留当前配置：${r.keep_schema || '无'}\n` +
    `将归档 ${r.files.length} 个文件：\n` + r.files.map(f => f.path).join('\n') +
    (r.launch_changed ? '\n同时移除以上历史配置对应的平台 VS 启动项。' : '') +
    (r.skipped.length ? `\n另有 ${r.skipped.length} 项记录无法确认归属，已跳过。` : '') +
    (r.kept_jobs?.length ? `\n保留 ${r.kept_jobs.length} 个无法确认构建独占的旧版或共享任务 env。` : '') +
    '\n文件将移至 docs/runtime-config-archives，源 XML、当前配置和结果不清理。';
  $('cleanup-preview').classList.remove('hidden');
  cleanupRecord={epoch,revision,count:r.files.length};
  refreshCleanupState();
  $('btn-cleanup-apply').onclick = async () => {
    if (epoch !== S.projectEpoch || revision !== cleanupRevision) return;
    if (S.inputTransition || cleanupPending || S.runtime?.busy || S.pollTimer || S.pendingRequests) return toast('请等待当前操作结束再清理', false);
    cleanupPending=true; refreshCleanupState();
    try {
      const result = await post('cleanup_configs', {keep_schema:keep, token:r.token, apply:true});
      if (epoch !== S.projectEpoch || revision !== cleanupRevision) return;
      resetCleanupPreview();
      if (result.error) return toast(result.error, false);
      $('cleanup-note').textContent = result.message + (result.archive ? `；归档位置：${result.archive}` : '');
      toast(result.message);
    } catch (error) {
      if (epoch === S.projectEpoch) { resetCleanupPreview(); toast(error.message, false); }
    } finally { cleanupPending=false; refreshCleanupState(); }
  };
}
