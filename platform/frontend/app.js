/* lishuttle 本地平台前端（原生 JS，无依赖） */
"use strict";

const $ = (id) => document.getElementById(id);
const S = {  // 全局状态
  cities: [], tasks: [], functions: [],
  city: null,          // {name, kind}
  task: null,          // 任务对象
  func: "pl",
  job: null,           // {name, schema, func, taskId}
  sid: 0, since: 0, pollTimer: null,
};

async function api(name, body, method) {
  const writing = method !== "GET";
  if (writing) S.pendingRequests = (S.pendingRequests || 0) + 1;
  const opt = method === "GET" ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...(body || {}), _project: S.project }),
  };
  try {
    const res = await fetch(`/api/${name}${method === "GET" ? body : ""}`, opt);
    return await res.json();
  } finally {
    if (writing) S.pendingRequests--;
  }
}

const get = (name, qs) => api(name, qs ? `?${qs}` : "", "GET");
const post = (name, body) => api(name, body, "POST");

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
}

function applyProjectState(st) {
  S.project = st.project;
  S.projectEpoch = (S.projectEpoch || 0) + 1;
  S.job = null;
  S.city = null;
  invalidateSchemaPreview();
  $("params-area").innerHTML = "";
  $("render-output").textContent = "";
  $("render-output").classList.add("hidden");
  $("run-info").textContent = "尚未渲染";
  $("run-console").textContent = "";
  S.sid = 0; S.since = 0;
  $("btn-export-log").disabled = true;
  $("run-status").classList.add("hidden");
  $("result-files").innerHTML = "";
  $("result-log").textContent = "";
  $("result-status").classList.add("hidden");
  $("result-job").value = "";
  lastResultsDir = "";
  S.functions = st.functions;
  S.functionInfo = {};
  (st.function_info || []).forEach(f => { S.functionInfo[f.name] = f; });
  renderFuncRadios(S.functions.includes("pl") ? "pl" : S.functions[0]);
  fillSelect($("project"), st.projects, st.project);
  $("project").value = st.project;
  $("map-root").value = st.map_root;
  $("gongcan-root").value = st.gongcan_root;
  renderCities(st.cities);
  renderTasks(st.tasks);
  $("env-note").textContent = `预设 ${st.preset} · 输出根 ${st.out_root}`;
}

async function changeProject(action, path) {
  if (S.pollTimer || S.pendingRequests) {
    $("project").value = S.project;
    return toast("当前操作结束后再切换项目", false);
  }
  $("project").disabled = true;
  $("btn-project-add").disabled = true;
  try {
    const st = await post(action, {path});
    if (st.error) { $("project").value = S.project; return toast(st.error, false); }
    applyProjectState(st);
    $("project-add-form").classList.add("hidden");
    $("btn-project-add").setAttribute("aria-expanded", "false");
    toast(`项目已切换：${st.project}` + ((st.project_warnings || []).length ? "；" + st.project_warnings.join("；") : ""));
  } catch (error) {
    $("project").value = S.project;
    toast(`项目切换失败：${error.message}`, false);
  } finally {
    $("project").disabled = false;
    $("btn-project-add").disabled = false;
  }
}

function bindActions() {
  $("btn-doctor").onclick = () => toolkit("doctor");
  $("btn-build").onclick = () => toolkit("build");
  $("btn-rescan-map").onclick = rescanMap;
  $("btn-rescan-task").onclick = rescanTasks;
  $("btn-render").onclick = doRender;
  $("btn-run").onclick = doRun;
  $("btn-stop").onclick = () => post("stop", { sid: S.sid });
  $("btn-export-log").onclick = exportRunLog;
  $("btn-csv-load").onclick = loadCsv;
  $("engineering-path").onchange = () => selectEngineering($("engineering-path").value, true);
  $("csv-path").onchange = () => selectEngineering($("csv-path").value, true);
  $("use-existing-schema").onchange = updateSchemaMode;
  ["schema-source", "sync-engineering", "schema-polygon", "job-name", "task-id", "copy-antennas"].forEach(id => {
    $(id).addEventListener("change", invalidateSchemaPreview);
    $(id).addEventListener("input", invalidateSchemaPreview);
  });
  $("btn-csv-save").onclick = saveCsv;
  $("btn-csv-col").onclick = setColumn;
  $("btn-results").onclick = loadResults;
  $("btn-open-dir").onclick = () => post("open_folder", { path: lastResultsDir || "" });
  document.querySelectorAll(".tabs button").forEach(b => b.onclick = () => switchTab(b));
}

function switchTab(btn) {
  document.querySelectorAll(".tabs button").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  btn.classList.add("active");
  $("tab-" + btn.dataset.tab).classList.add("active");
}

function fillSelect(sel, items, current) {
  sel.innerHTML = items.map(p =>
    `<option value="${esc(p).replace(/"/g, "&quot;")}" ${p === current ? "selected" : ""}>${esc(p.split(/[\\/]/).pop())}</option>`).join("");
}

/* ---------------- 左侧：城市与任务 ---------------- */

async function rescanMap() {
  const r = await post("set_map_root", { path: $("map-root").value });
  if (r.error) return toast(r.error, false);
  renderCities(r.cities);
  toast(`识别到 ${r.cities.length} 个城市/场景`);
}

async function rescanTasks() {
  const r = await post("set_gongcan_root", { path: $("gongcan-root").value });
  if (r.error) return toast(r.error, false);
  renderTasks(r.tasks);
  toast(`识别到 ${r.tasks.length} 个任务`);
}

const KIND_CN = { outdoor: "室外", indoor: "室内", unknown: "未识别" };

// -f 功能的中文名与说明（源自 readme.txt、笔记和实测）
const FUNC_INFO = {
  test:        { zh: "基本检测",   desc: "检查程序能否运行，显示授权可用日期（-c 可不给）" },
  debug:       { zh: "内部调试",   desc: "DebugEngine 内部测试功能，开发调试用" },
  pl:          { zh: "路损计算",   desc: "逐小区计算传播路损，输出 .loss/.pene 文件" },
  pred:        { zh: "室外覆盖预测", desc: "室外覆盖预测(RSRP/SINR，输出 pred 目录 BESTSERVER/RSRP/DLRSSINR)。室内预测请用 indoorpred" },
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
    document.querySelectorAll("#city-list .city").forEach(e => e.classList.remove("sel"));
    el.classList.add("sel");
    S.city = cities.find(c => c.name === el.dataset.name);
    updateNote();
    if (S.city.kind === "indoor" && !("plindoor", "predindoor", "indoorrays").includes(S.func))
      renderFuncRadios("indoorpred");
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
    if (!$("job-name").value) $("job-name").value = `${S.task.name}-${S.func}`;
  });
}

let schemaPreviewRevision = 0;
function updateAntennaOption() {
  const available = !!(S.task && S.task.has_antennas);
  $("antenna-option").classList.toggle("hidden", !available);
  $("copy-antennas").disabled = !available;
  $("copy-antennas").checked = available;
}

function invalidateSchemaPreview() {
  schemaPreviewRevision++;
  $("schema-preview").classList.add("hidden");
  $("btn-apply-schema").disabled = true;
}

function updateSchemaMode() {
  const reuse = $("use-existing-schema").checked;
  $("schema-source").disabled = !reuse;
  $("sync-engineering").disabled = !reuse;
  $("copy-files").disabled = reuse;
  $("existing-schema-options").classList.toggle("hidden", !reuse);
  $("btn-render").textContent = reuse ? "预览路径修改" : "装配并渲染";
  invalidateSchemaPreview();
}

function clearCsvEditor() {
  csvData = null;
  $("csv-wrap").textContent = "工参选择已更新，请点击加载";
  $("csv-msg").textContent = "";
}

function selectEngineering(path, manual) {
  if (!S.task) return;
  S.task.engineering_file = path;
  $("engineering-path").value = path;
  $("csv-path").value = path;
  S.task.kind = (S.task.engineering_kinds || {})[path] || "unknown";
  S.task.detect = manual && path ? "手动选择，工参表头已识别" : S.task.engineering_reason;
  $("engineering-reason").textContent = path
    ? `${S.task.detect} · ${path}` : S.task.engineering_reason;
  clearCsvEditor();
  updateNote();
}

function updateNote() {
  invalidateSchemaPreview();
  const c = S.city ? `${S.city.kind === "indoor" ? "室内场景" : "城市"} ${S.city.name}` : "未选地图";
  const t = S.task ? `任务 ${S.task.name}（${KIND_CN[S.task.kind]}，${S.task.detect}）` : "未选任务";
  $("selection-note").textContent = `已选：${c} · ${t}`;
  if (S.job) $("run-info").textContent =
    `${S.job.name}.xml · -f ${S.job.func} -t ${S.job.taskId}${S.job.outDir ? ` · 实际输出：${S.job.outDir}` : ""}`;
}

/* ---------------- 功能选择 ---------------- */

function renderFuncRadios(current) {
  S.func = current;
  $("func-radios").innerHTML = S.functions.map(f => {
    const srv = (S.functionInfo || {})[f];
    const loc = FUNC_INFO[f];
    const zh = srv ? srv.label : (loc ? loc.zh : "");
    const desc = srv ? srv.desc : (loc ? loc.desc : "");
    return `<label title="${desc}"><input type="radio" name="func" value="${f}" ${f === current ? "checked" : ""}>${f}${zh ? ` <span class="fzh">${zh}</span>` : ""}</label>`;
  }).join("");
  showFuncHint(current);
  document.querySelectorAll('#func-radios input').forEach(r => r.onchange = () => {
    S.func = r.value;
    showFuncHint(r.value);
    updateNote();
    if (S.job && S.job.schema) loadParams();
  });
}

function showFuncHint(f) {
  const srv = (S.functionInfo || {})[f];
  const info = srv ? { zh: srv.label, desc: srv.desc } : FUNC_INFO[f];
  if (info) $("hint").textContent = `-f ${f} ${info.zh}：${info.desc}`;
}

/* ---------------- 渲染与参数 ---------------- */

async function doRender() {
  if (!S.city) return toast("先在左侧选择城市/场景", false);
  if (!S.task) return toast("先在左侧选择工参任务", false);
  const reuse = $("use-existing-schema").checked;
  if ((!reuse || $("sync-engineering").checked) && !S.task.engineering_file)
    return toast(S.task.engineering_reason || "请选择装配工参", false);
  if (reuse && !$("schema-source").value) return toast("请选择已有运行配置 XML", false);
  const jobName = $("job-name").value.trim();
  if (!jobName) return toast("先填任务名", false);
  const body = {
    job_name: jobName, func: S.func, task_id: $("task-id").value || "1",
    task: S.task, city: S.city.name, city_kind: S.city.kind,
    engineering_file: S.task.engineering_file,
    copy_files: !reuse && $("copy-files").checked,
    copy_antennas: !!S.task.has_antennas && $("copy-antennas").checked,
    use_existing_schema: reuse, schema_source: $("schema-source").value,
    sync_engineering: $("sync-engineering").checked, polygon_file: $("schema-polygon").value,
  };
  if (reuse) {
    invalidateSchemaPreview();
    const revision = schemaPreviewRevision;
    const p = await post("preview_render", body);
    if (revision !== schemaPreviewRevision) return;
    if (p.error) return toast(p.error, false);
    $("schema-preview-text").textContent =
      `源文件：${p.source}\n目标文件：${p.destination}\n保留 name：${p.runtime_name}\n实际输出目录：${p.out_dir}\n` +
      `覆盖已有目标前备份为 .bak。源文件保持不变。\n\n` +
      `确认后自动补齐当前项目 ThirdPart 基础运行资源，保留已存在文件。\n\n` +
      (body.copy_antennas ? `另装配任务天线：${S.task.antenna_dir || S.task.antenna || "无任务天线，将按现有规则恢复项目默认天线 XML"}\n\n` : "不装配天线，保留项目现有天线文件。\n\n") +
      p.changes.map(c => `${c.tag}\n  原：${c.old || "（空）"}\n  新：${c.new || "（空）"}`).join("\n") +
      (p.warnings.length ? "\n\n提示：\n" + p.warnings.join("\n") : "");
    $("schema-preview").classList.remove("hidden");
    $("btn-apply-schema").disabled = false;
    $("btn-apply-schema").onclick = async () => {
      $("btn-apply-schema").disabled = true;
      await submitRender({ ...body, preview_token: p.token });
    };
    return;
  }
  await submitRender(body);
}

async function submitRender(body) {
  const epoch = S.projectEpoch;
  const jobName = body.job_name;
  const r = await post("render", body);
  if (epoch !== S.projectEpoch) return;
  if (r.error) return toast(r.error, false);
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
    return;
  }
  if (r.render_exit !== 0) {
    toast("运行单已生成，但有输入文件缺失（下方标 [缺失]）——参数面板仍可改路径", false);
  }

  S.job = { name: jobName, schema: r.schema_name, func: r.func, taskId: r.task_id, outDir: r.out_dir };
  const copied = (r.copied || []).map(c => `${c.file} → ${c.to} ${c.backup}`).join("\n");
  toast(`渲染完成：${r.schema_name}${copied ? "\n已替换：" + copied : ""}`);
  if (r.vs_launch_warning) toast(r.vs_launch_warning, false);
  updateNote();
  switchTab(document.querySelector('[data-tab="params"]'));
  loadParams();
}

async function loadParams() {
  const job = S.job;
  const r = await get("params", `schema=${encodeURIComponent(S.job.schema)}&func=${S.job.func}&all=0`);
  if (job !== S.job) return;
  if (r.error) return toast(r.error, false);
  renderParams(r);
}

function renderParams(r) {
  const area = $("params-area");
  area.innerHTML = "";
  for (const g of r.groups) {
    const div = document.createElement("div");
    div.className = "pgroup";
    div.innerHTML = `<h4>${g.group}</h4><table class="ptable"></table>`;
    const tb = div.querySelector("table");
    for (const p of g.rows) {
      const d = (r.thirdpart_defaults || {})[p.name];
      const available = d && d.available && r.values[p.name] !== undefined;
      const reason = r.values[p.name] === undefined ? "当前 XML 没有此字段" : d ? (d.reason || `恢复为：${d.value || "（空）"}；来源：${d.source}`) : "当前项目 ThirdPart 样例没有此参数默认值";
      const defaultButton = `<button type="button" class="mini param-default" data-default-tag="${p.name}" ${available ? "" : "disabled"} title="${esc(reason).replace(/"/g, "&quot;")}">ThirdPart 默认</button>`;
      const v = r.values[p.name] !== undefined ? r.values[p.name] : (p.default || "");
      const tr = document.createElement("tr");
      const input = p.type === "bool"
        ? `<select data-tag="${p.name}"><option ${v === "true" ? "selected" : ""}>true</option><option ${v !== "true" ? "selected" : ""}>false</option></select>`
        : `<input data-tag="${p.name}" value="${esc(v).replace(/"/g, "&quot;")}">`;
      tr.innerHTML = `<td title="${(p.desc || "").replace(/"/g, "&quot;")}">${p.label}<br><span class="muted" style="font-size:11px">${p.name}</span></td>
                      <td><div class="param-control">${input}${defaultButton}</div></td>
                      <td>${p.desc || ""}</td>`;
      tb.appendChild(tr);
    }
    area.appendChild(div);
  }
  // 失焦即写文件（用户确认的模型：改了就落盘）
  area.querySelectorAll("input[data-tag],select[data-tag]").forEach(el => {
    el.addEventListener("change", async () => {
      const tag = el.dataset.tag, value = el.value;
      const res = await post("param_write", { schema: S.job.schema, tag, value });
      if (!res.ok) { toast(res.message, false); return; }
      el.classList.remove("dirty");
      toast(`${tag} 已写入 ${S.job.schema}（原文件备份 .bak）`);
    });
    el.addEventListener("focus", () => { /* hint 由 title 承担 */ });
  });
  area.querySelectorAll("button[data-default-tag]").forEach(button => {
    button.onclick = async () => {
      const job = S.job;
      const tag = button.dataset.defaultTag;
      button.disabled = true;
      try {
        const res = await post("param_default", {schema: job.schema, tag});
        if (S.job !== job) return;
        if (!res.ok) return toast(res.message || res.error, false);
        await loadParams();
        toast(`${tag} 已写入 ThirdPart 默认值（原文件备份 .bak）`);
      } catch (error) { toast(error.message, false); }
      finally { button.disabled = false; }
    };
  });
}

/* ---------------- 工参 CSV ---------------- */

let csvData = null;

async function loadCsv() {
  const p = $("csv-path").value;
  if (!p) return toast("没有 CSV 路径，先在左侧选任务", false);
  const data = await get("csv", `path=${encodeURIComponent(p)}`);
  if (p !== $("csv-path").value) return;
  csvData = data;
  if (csvData.error) return toast(csvData.error, false);
  renderCsv();
}

function renderCsv() {
  const mk = (row, tag) => row.map(c => `<${tag}>${esc(c)}</${tag}>`).join("");
  const head = `<tr>${mk(csvData.header_zh, "td")}</tr><tr>${mk(csvData.header_en, "td")}</tr>`;
  const body = csvData.rows.map((row, i) =>
    `<tr data-i="${i}">${row.map(c => `<td contenteditable>${esc(c)}</td>`).join("")}</tr>`).join("");
  $("csv-wrap").innerHTML = `<table>${head}${body}</table>`;
  $("csv-msg").textContent = `编码 ${csvData.encoding} · ${csvData.rows.length} 行数据`;
}

async function saveCsv() {
  if (!csvData) return;
  const table = $("csv-wrap").querySelector("table");
  const trs = table.querySelectorAll("tr");
  const grab = tr => [...tr.children].map(td => td.textContent);
  const body = {
    path: csvData.path,
    header_zh: grab(trs[0]), header_en: grab(trs[1]),
    rows: [...trs].slice(2).map(grab),
  };
  const r = await post("csv_save", body);
  $("csv-msg").textContent = r.message || r.error || "";
  toast(r.ok ? "CSV 已保存（原文件备份 .bak）" : r.error, r.ok);
}

async function setColumn() {
  if (!csvData) return;
  const col = $("csv-col").value.trim(), val = $("csv-val").value;
  if (!col) return toast("填列名", false);
  const r = await post("csv_column", { path: csvData.path, column: col, value: val });
  $("csv-msg").textContent = r.message || r.error || "";
  if (r.ok) { await loadCsv(); toast("整列已设置并保存"); }
}

function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;"); }

/* ---------------- 运行与工具链 ---------------- */

async function toolkit(step) {
  const r = await post("toolkit", { step });
  if (r.error) return toast(r.error, false);
  attachConsole(r.sid, `${step} 输出：`);
  switchTab(document.querySelector('[data-tab="run"]'));
}

async function doRun() {
  if (!S.job) return toast("先在「功能与参数」页装配并渲染", false);
  const r = await post("run", { schema: S.job.schema, func: S.job.func, task_id: S.job.taskId });
  if (r.error) return toast(r.error, false);
  attachConsole(r.sid, `运行 ${S.job.schema}：`);
  switchTab(document.querySelector('[data-tab="run"]'));
}

function attachConsole(sid, title) {
  S.sid = sid; S.since = 0;
  $("btn-export-log").disabled = false;
  const con = $("run-console");
  con.textContent = title + "\n";
  $("run-status").className = "badge running hidden";
  if (S.pollTimer) clearInterval(S.pollTimer);
  S.pollTimer = setInterval(async () => {
    const r = await get("output", `sid=${S.sid}&since=${S.since}`);
    if (r.error) return;
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
      b.className = "badge " + (r.exit === 0 ? "ok" : "fail");
      b.textContent = `退出码 ${r.exit}`;
      toast(`${r.label} 结束，退出码 ${r.exit}`, r.exit === 0);
    }
  }, 700);
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
  if (!job) return toast("填任务名", false);
  const r = await get("results", `job=${encodeURIComponent(job)}`);
  if (epoch !== S.projectEpoch) return;
  lastResultsDir = r.dir || "";
  const b = $("result-status");
  if (!r.exists) {
    b.className = "badge fail"; b.textContent = "输出目录不存在";
    $("result-files").innerHTML = ""; $("result-log").textContent = "";
    return;
  }
  b.classList.remove("hidden");
  const empty = r.empty_run;
  b.className = "badge " + (empty ? "fail" : r.status === "end" ? "ok" : r.status ? "fail" : "unknown");
  b.textContent = empty ? "假完成(无产物)"
    : r.status ? ({ end: "完成", failed: "失败", processing: "进行中" }[r.status] || r.status) : "无状态文件";
  $("result-files").innerHTML = r.files.map(f =>
    `<div><span>${f.rel}</span><span class="muted">${f.size}</span></div>`).join("");
  const src = r.log_file
    ? `\n（日志来源：${r.log_file}${r.log_file.includes("Bin") ? "，exe目录实时日志" : "，输出目录归档日志"}）` : "";
  $("result-log").innerHTML =
    r.log_tail.map(l => {
      const cls = /FATAL|ERROR/.test(l) ? "err" : /WARN/.test(l) ? "warn" : "";
      return cls ? `<span class="${cls}">${esc(l)}</span>` : esc(l);
    }).join("\n") + src || "（无日志）";
}

init();
