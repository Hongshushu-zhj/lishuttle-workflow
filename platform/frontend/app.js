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
    body: JSON.stringify({ ...(body || {}), _project: S.project, _revision: S.profileRevision,
      _machine_revision: S.machineRevision }),
  };
  try {
    const suffix = method === 'GET' && S.project && name !== 'output' && name !== 'state'
      ? `${body ? '&' : '?'}_project=${encodeURIComponent(S.project)}&_revision=${encodeURIComponent(S.profileRevision || '')}` : '';
    const res = await fetch(`/api/${name}${method === "GET" ? body + suffix : ""}`, opt);
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
  $("btn-project-config").onclick = () => {
    const open = $("project-config-form").classList.contains("hidden");
    $("project-config-form").classList.toggle("hidden", !open);
    $("btn-project-config").setAttribute("aria-expanded", String(open));
  };
  $("project-config-form").onsubmit = async event => {
    event.preventDefault();
    if (S.pollTimer || S.pendingRequests) return toast('当前操作结束后再修改项目配置', false);
    const values = {};
    $("project-config-fields").querySelectorAll('[data-config-key]').forEach(input => {
      values[input.dataset.configKey] = input.value.trim();
    });
    BUILD_KEYS.forEach(key => { values[key] = S.projectDraft[key] || ''; });
    const st = await post('save_project_config', {values});
    if (st.error) return toast(st.error, false);
    applyProjectState(st, {preserveMachineDraft:true});
    $("project-config-note").textContent = '当前项目配置已保存，任务选择与旧预览已清理。';
    toast('当前项目配置已保存');
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

function applyProjectState(st, {preserveMachineDraft = false} = {}) {
  const machineDraft = preserveMachineDraft ? MACHINE_KEYS.filter(key=>S.configTouched?.has(key) ||
      S.projectDraft?.[key] !== S.projectConfig?.[key])
    .map(key=>({key,value:S.projectDraft[key],manual:S.projectManualFields?.has(key),touched:S.configTouched?.has(key)})) : [];
  S.project = st.project;
  S.profileId = st.profile_id;
  S.profileRevision = st.profile_revision;
  S.machineRevision = st.machine_revision;
  S.machineDetection = mergeMachineDetection(st.machine_detection);
  S.projectConfig = {...(st.project_config || {}), ...(st.machine_config || {})};
  S.buildWorkflow = st.build_workflow || {};
  S.projectDraft = {...S.projectConfig};
  S.projectDetection = null;
  S.configTouched = new Set();
  S.projectManualFields = new Set();
  machineDraft.forEach(({key,value,manual,touched}) => {
    S.projectDraft[key] = value;
    if (touched) S.configTouched.add(key);
    if (manual) S.projectManualFields.add(key);
  });
  S.localPathDefaults = {};
  S.localPathIssues = {};
  localPathRevision++;
  renderProjectConfig();
  $("machine-config-note").textContent = '本机工具链已保存的值由所有项目共用；自动检测只补空缺，手动修改后请保存。';
  if (machineDraft.length) configDraftNote(machineDraft[0].key);
  if (MACHINE_KEYS.some(key => !S.projectConfig[key]) || (S.machineDetection.filled || []).length) {
    $("machine-config-form").classList.remove('hidden');
    $("btn-machine-config").setAttribute('aria-expanded', 'true');
  }
  $("local-path-fields").innerHTML = '';
  $("local-path-status").textContent = '选择地图与任务运行配置后识别本地路径。';
  $("task-binding-note").textContent = '选择工参及地图后可保存；对应关系仅在当前项目生效。';
  S.projectEpoch = (S.projectEpoch || 0) + 1;
  S.job = null;
  S.city = null;
  taskIdentityChanged();
  invalidateSchemaPreview();
  $("params-area").innerHTML = "";
  S.paramsData = null; S.paramsScope = null; S.paramsSearch = ''; S.paramsForJob = null;
  $('params-toolbar').classList.add('hidden');
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
  if (typeof fetch === 'function' && S.profileId) refreshProjectDetection();
}

const PROFILE_LABELS = {
  PRESET:'构建预设', BUILD_SUBDIR:'构建目录（相对项目）', INSTALL_SUBDIR:'安装目录（相对项目）',
  EXE_NAME:'程序文件名', VS_ROOT:'Visual Studio 目录', CMAKE:'CMake 程序', NINJA:'Ninja 程序',
  VCVARS:'MSVC 环境脚本', CONFIG_SRC:'基础配置源目录', DLL_SRC:'动态库源目录',
  MAP_ROOT:'地图根目录', OUT_ROOT:'结果根目录', DT_ROOT:'路测根目录（可选，仅路测相关功能）',
  GONGCAN_ROOT:'工参任务根目录',
};
const MACHINE_KEYS = ['VS_ROOT','CMAKE','NINJA','VCVARS'];
const BUILD_KEYS = ['PRESET','BUILD_SUBDIR','INSTALL_SUBDIR','EXE_NAME'];
const attr = value => esc(value || '').replace(/"/g, '&quot;');
function renderProjectConfig() {
  renderConfigFields('project-config-fields', false);
  renderConfigFields('machine-config-fields', true);
  renderBuildControls();
  renderWorkflowGuide();
}
function renderConfigFields(id, machine) {
  const draft = S.projectDraft || S.projectConfig;
  const container = $(id);
  container.innerHTML = Object.entries(PROFILE_LABELS).filter(([key]) => !BUILD_KEYS.includes(key) && MACHINE_KEYS.includes(key) === machine).map(([key, label]) => {
    const field = S.projectDetection?.fields[key];
    const value = draft[key] || '';
    const detected = machine ? S.machineDetection?.candidates?.[key] : null;
    const candidates = detected?.length ? detected.map(value=>({value,label:value})) : [...(field?.candidates || [])];
    if (value && !candidates.some(c => c.value === value)) candidates.unshift({value,label:value});
    const manual = S.projectManualFields?.has(key) || !candidates.length;
    const choice = candidates.length ? `<select id="config-choice-${key}" class="txt" data-config-choice="${key}" aria-label="${attr(label)}候选">` +
      `<option value="" ${!value && !manual ? 'selected' : ''}>请选择检测到的候选</option>` +
      candidates.map(c => `<option value="${attr(c.value)}" ${!manual && value === c.value ? 'selected' : ''}>${esc(c.label || c.value)}</option>`).join('') +
      `<option value="__manual__" ${manual ? 'selected' : ''}>手动填写其他路径或值</option></select>` : '';
    const source = S.configTouched?.has(key) || (machine && value !== (S.projectConfig[key] || '')) ? '当前未保存的选择或输入' :
      S.projectConfig[key] ? (machine ? '本机全局已保存 · 所有项目共用' : '当前项目已保存配置') :
        field?.source || (machine ? '未检测到，请安装对应工具后重新检测或手动填写' : '正在检测；也可手动填写');
    return `<label>${label} · ${key}${choice}<input id="config-${key}" class="txt" type="${manual ? 'text' : 'hidden'}" data-config-key="${key}" value="${attr(value)}" aria-label="${attr(label)}">` +
      `<small class="field-help">${esc(source)}</small></label>`;
  }).join('');
  container.oninput = event => {
    if (event.target.dataset.configKey) editProjectConfig(event.target.dataset.configKey, event.target.value);
  };
  container.onchange = event => {
    if (event.target.dataset.configChoice) changeProjectConfigChoice(event.target.dataset.configChoice, event.target.value);
  };
}

function editProjectConfig(key, value) {
  clearSetupIssue();
  S.projectDraft[key] = value;
  S.configTouched.add(key);
  S.projectManualFields.add(key);
  configDraftNote(key);
}

function buildPresets() { return S.projectDetection?.presets || S.buildWorkflow?.presets || {}; }
function buildMode(entry, name) {
  return entry?.mode || (/debug/i.test(entry?.build_type || name) ? 'debug' :
    /release|relwithdebinfo|minsizerel/i.test(entry?.build_type || name) ? 'release' : '');
}
function selectedBuildStatus() {
  const draft = S.projectDraft || {};
  const saved = draft.PRESET === S.projectConfig?.PRESET && draft.BUILD_SUBDIR === S.projectConfig?.BUILD_SUBDIR;
  return saved ? S.buildWorkflow : S.buildWorkflow?.presets?.[draft.PRESET];
}
function renderBuildControls() {
  const presets = buildPresets(), draft = S.projectDraft || {};
  const mode = buildMode(presets[draft.PRESET], draft.PRESET) || 'release';
  $('build-mode').innerHTML = '<option value="debug">Debug · 调试</option><option value="release">Release · 发布</option>';
  $('build-mode').value = mode;
  $('build-mode').onchange = () => chooseBuildMode($('build-mode').value);
  const names = Object.keys(presets).filter(name => buildMode(presets[name],name) === mode);
  $('build-preset').innerHTML = names.length ? names.map(name => `<option value="${attr(name)}">${esc(name)} · ${esc(presets[name].build_type || mode)}</option>`).join('') : '<option value="">未检测到兼容预设，请检查 CMakePresets.json</option>';
  $('build-preset').value = names.includes(draft.PRESET) ? draft.PRESET : '';
  $('build-preset').onchange = () => changeProjectConfigChoice('PRESET',$('build-preset').value);
  const status = selectedBuildStatus();
  const directory = status?.directory_exists ? '已生成' : '尚未生成（点击编译后创建）';
  $('build-summary').textContent = `预设：${draft.PRESET || '待选择'} · 构建目录：${draft.BUILD_SUBDIR || '由预设自动确定'} · ${directory}` +
    ` · 程序：${status?.built ? status.executable || draft.EXE_NAME || '已识别' : '编译后自动识别'}`;
}
function chooseBuildMode(mode) {
  const presets = buildPresets();
  const names = Object.keys(presets).filter(name => buildMode(presets[name],name) === mode);
  if (!names.length) return focusSetupIssue({target:'build-mode',section:'build',message:`项目没有兼容的 ${mode === 'debug' ? 'Debug' : 'Release'} 预设，请检查 CMakePresets.json`});
  clearSetupIssue();
  changeProjectConfigChoice('PRESET',names.includes(S.projectDraft.PRESET) ? S.projectDraft.PRESET : names[0]);
}
function renderWorkflowGuide() {
  const saved = S.projectConfig || {};
  const steps = [
    [!!S.profileId,'添加并选择本地项目','project-path','project-add'],
    [['CMAKE','NINJA','VCVARS'].every(k=>saved[k]),'检测并保存本机工具链（全局复用）','config-CMAKE','machine'],
    [!!selectedBuildStatus()?.built,'选择 Debug / Release 并编译，生成构建目录','build-mode','build'],
    [['CONFIG_SRC','DLL_SRC','MAP_ROOT','GONGCAN_ROOT','OUT_ROOT'].every(k=>saved[k]),'确认并保存资源、地图、工参任务和结果目录','config-CONFIG_SRC','project'],
    [!!S.city && !!S.task,'选择地图、工参 CSV 和运行配置 XML','city-list','input'],
    [!!S.job,'装配并渲染，确认预览后运行','btn-render','input'],
  ];
  $('workflow-steps').innerHTML = steps.map(([done,label,target,section]) => `<li class="${done ? 'step-done' : ''}"><button type="button" data-guide-target="${target}" data-guide-section="${section}">${done ? '✓ 完成' : '待操作'} · ${esc(label)}</button></li>`).join('');
  $('workflow-steps').querySelectorAll('[data-guide-target]').forEach(button => button.onclick = () => focusSetupIssue({target:button.dataset.guideTarget,section:button.dataset.guideSection,message:''}));
}
function clearSetupIssue() {
  document.querySelectorAll('.field-invalid').forEach(el=>{el.classList.remove('field-invalid');el.removeAttribute('aria-invalid');});
  $('setup-validation').textContent = '';
}
function focusSetupIssue(issue) {
  clearSetupIssue();
  const form = {project:'project-config',machine:'machine-config','project-add':'project-add'}[issue.section];
  if (form) {
    $(form+'-form').classList.remove('hidden');
    $('btn-'+form).setAttribute('aria-expanded','true');
  }
  if (issue.section === 'input') {
    const tab = document.querySelector('[data-tab="params"]');
    if (tab) switchTab(tab);
  }
  let el = $(issue.target);
  if (el?.type === 'hidden') el = $('config-choice-'+issue.key);
  if (el) {
    el.setAttribute('aria-invalid', String(!!issue.message));
    el.classList.add('field-invalid');
    el.scrollIntoView?.({behavior:'smooth',block:'center'});
    el.focus?.();
  }
  $('setup-validation').textContent = issue.message || '';
  if (issue.message) toast(issue.message,false);
}
function setupError(result) {
  if (result.issues?.length) focusSetupIssue(result.issues[0]);
  else toast(result.error || '配置校验失败',false);
}

function configDraftNote(key) {
  $(MACHINE_KEYS.includes(key) ? 'machine-config-note' : 'project-config-note').textContent =
    MACHINE_KEYS.includes(key) ? '本机工具链已修改；保存后应用于所有项目。' : '配置已修改；保存当前项目配置后生效。';
}

function matchingToolchain(toolchains, root) {
  const canonical = value => String(value || '').replace(/\\/g,'/').replace(/\/+$/,'').toLowerCase();
  return Object.entries(toolchains || {}).find(([path])=>canonical(path) === canonical(root))?.[1];
}

function mergeMachineDetection(next = {}) {
  return {...next, candidates:Object.keys(next.candidates || {}).length ? next.candidates : S.machineDetection?.candidates || {}};
}

async function updateMachineConfig(action, body) {
  if (S.pollTimer || S.pendingRequests) return toast('当前操作结束后再修改本机工具链', false);
  const epoch = S.projectEpoch, sent = Object.fromEntries(MACHINE_KEYS.map(key=>[key,S.projectDraft[key]]));
  $("machine-config-note").textContent = '正在检测或保存本机工具链…';
  try {
    const st = await post(action, body);
    if (epoch !== S.projectEpoch) return;
    if (st.error) throw Error(st.error);
    S.machineRevision = st.machine_revision;
    S.profileRevision = st.profile_revision;
    S.machineDetection = mergeMachineDetection(st.machine_detection);
    MACHINE_KEYS.forEach(key => {
      const saved = st.machine_config[key] || '';
      S.projectConfig[key] = saved;
      if (S.projectDraft[key] === sent[key]) {
        S.projectDraft[key] = saved;
        S.configTouched.delete(key);
      }
    });
    invalidateSchemaPreview();
    renderProjectConfig();
    const missing = MACHINE_KEYS.filter(key=>!st.machine_config[key]);
    $("machine-config-note").textContent = '本机工具链已保存，所有项目共用。' +
      (missing.length ? `未检测到：${missing.join('、')}；请安装后重新检测或手动填写。` : '') +
      (MACHINE_KEYS.some(key=>S.configTouched.has(key)) ? '仍有尚未保存的手动修改。' : '');
  } catch (error) {
    if (epoch === S.projectEpoch) $("machine-config-note").textContent = `本机工具链配置失败：${error.message}`;
  }
}

function changeProjectConfigChoice(key, value) {
  clearSetupIssue();
  if (value === '__manual__') {
    S.projectManualFields.add(key);
    S.configTouched.add(key);
  } else {
    const previous = S.projectDraft[key];
    const groups = key === 'PRESET' ? buildPresets() : key === 'VS_ROOT' ?
      S.machineDetection?.candidates?.toolchains || S.projectDetection?.toolchains : null;
    const linked = entry => key === 'PRESET' ? entry?.values || {} : entry || {};
    const old = linked(key === 'VS_ROOT' ? matchingToolchain(groups, previous) : groups?.[previous]);
    const next = linked(key === 'VS_ROOT' ? matchingToolchain(groups, value) : groups?.[value]);
    S.projectDraft[key] = value;
    S.configTouched.add(key);
    S.projectManualFields.delete(key);
    Object.entries(old).forEach(([field, previousValue]) => {
      if (field !== key && !(field in next) && !S.configTouched.has(field) &&
          S.projectDraft[field] === previousValue) S.projectDraft[field] = '';
    });
    Object.entries(next).forEach(([field, proposed]) => {
      if (field !== key && !S.configTouched.has(field) &&
          (!S.projectDraft[field] || S.projectDraft[field] === old[field])) S.projectDraft[field] = proposed;
    });
  }
  renderProjectConfig();
  configDraftNote(key);
}

let projectDetectionRequest = 0;
async function refreshProjectDetection() {
  const request = ++projectDetectionRequest;
  const project = S.project, epoch = S.projectEpoch, revision = S.profileRevision;
  const current = () => request === projectDetectionRequest && project === S.project &&
    epoch === S.projectEpoch && revision === S.profileRevision;
  $("project-config-note").textContent = '正在检测当前项目预设和资源目录…';
  try {
    const result = await post('detect_project_config', {});
    if (!current()) return;
    if (result.error) throw Error(result.error);
    S.projectDetection = result;
    const suggested = {...result.values};
    // A selection typed while detection was in flight takes precedence over its recommendation.
    const preset = S.projectDraft.PRESET || suggested.PRESET;
    if (preset !== suggested.PRESET) {
      ['BUILD_SUBDIR','INSTALL_SUBDIR','EXE_NAME','DLL_SRC'].forEach(key => delete suggested[key]);
      Object.assign(suggested, result.presets?.[preset]?.values || {});
    }
    const vs = S.projectDraft.VS_ROOT || suggested.VS_ROOT;
    if (vs !== suggested.VS_ROOT) {
      ['CMAKE','NINJA','VCVARS'].forEach(key => delete suggested[key]);
      Object.assign(suggested, matchingToolchain(result.toolchains, vs) || {});
    }
    let filled = 0;
    Object.entries(suggested).forEach(([key,value]) => {
      if (MACHINE_KEYS.includes(key)) return; // Machine discovery is persisted by the dedicated global endpoint.
      if (value && !S.projectDraft[key] && !S.configTouched.has(key)) {
        S.projectDraft[key] = value;
        filled++;
      }
    });
    renderProjectConfig();
    const unresolved = ['CONFIG_SRC','DLL_SRC','MAP_ROOT','GONGCAN_ROOT','OUT_ROOT'].filter(key => !S.projectDraft[key]);
    $("project-config-note").textContent = `检测完成，自动填充 ${filled} 项；保存当前项目配置后生效。` +
      (unresolved.length ? `待选择或填写：${unresolved.map(key=>PROFILE_LABELS[key]).join('、')}。` : '') +
      ((result.warnings || []).length ? `检测提示：${result.warnings.join('；')}` : '');
    if (filled || unresolved.length) {
      $("project-config-form").classList.remove('hidden');
      $("btn-project-config").setAttribute('aria-expanded','true');
    }
  } catch (error) {
    if (current()) $("project-config-note").textContent = `自动检测失败：${error.message}。可重新检测或手动填写。`;
  }
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
  $("btn-cleanup-preview").onclick = previewCleanup;
  $("btn-run").onclick = doRun;
  $("btn-stop").onclick = () => post("stop", { sid: S.sid });
  $("btn-export-log").onclick = exportRunLog;
  $("btn-csv-load").onclick = loadCsv;
  $("engineering-path").onchange = () => selectEngineering($("engineering-path").value, true);
  $("csv-path").onchange = () => selectEngineering($("csv-path").value, true);
  $("use-existing-schema").onchange = updateSchemaMode;
  $("schema-source").onchange = () => { refreshLocalPaths({}); invalidateSchemaPreview(); restoreTaskBinding(); };
  $("btn-save-task-binding").onclick = saveTaskBinding;
  ["sync-engineering", "schema-polygon", "job-name", "task-id", "copy-antennas"].forEach(id => {
    $(id).addEventListener("change", invalidateSchemaPreview);
    $(id).addEventListener("input", invalidateSchemaPreview);
  });
  ['job-name', 'task-id'].forEach(id => {
    $(id).addEventListener('input', taskIdentityChanged);
    $(id).addEventListener('change', taskIdentityChanged);
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
    refreshLocalPaths({});
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
    refreshLocalPaths({});
    restoreTaskBinding();
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
  bindingRevision++;
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
  refreshLocalPaths();
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
  if (S.profileId) {
    const epoch = S.projectEpoch;
    const validation = await post('validate_setup',{operation:'render'});
    if (epoch !== S.projectEpoch) return;
    if (validation.error || validation.issues?.length) return setupError(validation);
    if (BUILD_KEYS.some(key=>(S.projectDraft?.[key] || '') !== (S.projectConfig?.[key] || '')))
      return focusSetupIssue({target:'btn-build',section:'build',message:'当前构建选择尚未应用，请编译所选配置，或保存项目配置后重新装配'});
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
    task: S.task, city: S.city.name, city_kind: S.city.kind,
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
    const p = await post("preview_render", body);
    if (revision !== schemaPreviewRevision) return;
    if (p.error) return setupError(p);
    $("schema-preview-text").textContent =
      `源文件：${p.source}\n目标文件：${p.destination}\n任务 name：${p.runtime_name}\n实际输出目录：${p.out_dir}\n` +
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
  if (r.error) return setupError(r);
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
  resetCleanupPreview();
  taskIdentityChanged();
  $('result-job').value = r.runtime_name || jobName;
  const copied = (r.copied || []).map(c => `${c.file} → ${c.to} ${c.backup}`).join("\n");
  toast(`渲染完成：${r.schema_name}${copied ? "\n已替换：" + copied : ""}`);
  if (r.vs_launch_warning) toast(r.vs_launch_warning, false);
  updateNote();
  switchTab(document.querySelector('[data-tab="params"]'));
  loadParams();
}

let parameterRequest = 0;
async function loadParams() {
  const job = S.job;
  if (!job) return;
  const func = S.func || job.func, request = ++parameterRequest;
  if (S.paramsForJob !== job) {
    $('params-area').innerHTML = '';
    $('params-toolbar').classList.add('hidden');
  }
  const r = await get("params", `schema=${encodeURIComponent(job.schema)}&func=${encodeURIComponent(func)}&all=1`);
  if (job !== S.job || func !== (S.func || S.job.func) || request !== parameterRequest) return;
  if (r.error) return toast(r.error, false);
  S.paramsForJob = job;
  renderParams(r);
}

function renderParams(r) {
  S.paramsData = r;
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
  $('params-toolbar').classList.remove('hidden');
  $('params-scope').value = scope;
  $('params-search').value = S.paramsSearch || '';
  $('params-scope').onchange = () => { S.paramsScope = $('params-scope').value; renderParams(S.paramsData); };
  $('params-search').oninput = () => { S.paramsSearch = $('params-search').value; renderParams(S.paramsData); };
  $('params-summary').textContent = `XML 已识别 ${counts.total} 项 · 当前显示 ${shown} 项 · 推荐功能：${label}` +
    (r.counts ? ` · 本功能可配置 ${counts.recommended} 项 · 其他功能/场景 ${counts.other} 项 · 未分类 ${counts.unclassified} 项` : '');
  $('params-source').textContent = `实际读取与编辑文件：${r.file || '当前运行 XML'}${r.schema_name ? ` · name=${r.schema_name}` : ''}。字典中但当前 XML 未定义的字段不作为已配置参数显示。`;
  const review = profile.source_review || {};
  const reviewText = review.status === 'matched' ? '当前项目源码与调研版本一致' : review.status === 'changed'
    ? `当前项目源码存在差异，功能范围待复核：${(review.changed || []).join('、')}` : '当前项目源码不完整，使用已调研版本的参考范围';
  const required = profile.missing_required || [], optional = profile.missing_optional || [];
  $('params-profile').innerHTML = profile.reviewed
    ? `<p><strong>${esc(profile.label || label)}</strong>：${esc(profile.description || '')}</p>` +
      `<p class="${review.status === 'matched' ? '' : 'param-warning'}">${esc(reviewText)}</p>` +
      (profile.scene_warning ? `<p class="param-warning">${esc(profile.scene_warning)}</p>` : '') +
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
  // 失焦即写文件（用户确认的模型：改了就落盘）
  area.querySelectorAll("input[data-tag],select[data-tag]").forEach(el => {
    el.addEventListener("change", async () => {
      const tag = el.dataset.tag, value = el.value;
      if (!job || job !== S.job) return;
      const res = await post("param_write", { schema: job.schema, tag, value });
      if (job !== S.job) return;
      if (!res.ok) { toast(res.message, false); return; }
      el.classList.remove("dirty");
      if (res.target === 'engineering_csv') {
        csvData = null;
        $("csv-wrap").textContent = '计算半径已写入 CSV，请重新加载查看';
      }
      await loadParams();
      if (job !== S.job) return;
      toast(res.target === 'engineering_csv' ? res.message : `${tag} 已写入 ${S.job.schema}（原文件备份 .bak）`);
    });
    el.addEventListener("focus", () => { /* hint 由 title 承担 */ });
  });
  area.querySelectorAll("button[data-default-tag]").forEach(button => {
    button.onclick = async () => {
      if (!job || job !== S.job) return;
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
  if (S.pollTimer || S.pendingRequests) return toast('请等待当前操作结束',false);
  let epoch = S.projectEpoch;
  let sentDraft = {...S.projectDraft};
  const r = await post("toolkit", { step, ...(step === 'build' ? {preset:S.projectDraft?.PRESET || ''} : {}) });
  if (epoch !== S.projectEpoch) return;
  if (r.error) return setupError(r);
  if (step === 'build') {
    applyBuildStatus(r, sentDraft);
    epoch = S.projectEpoch;
    sentDraft = {...sentDraft, ...r.build_values};
  }
  attachConsole(r.sid, `${step} 输出：`, step === 'build' ? async () => {
    const status = await post('build_status',{});
    if (epoch !== S.projectEpoch) return;
    if (status.error) return setupError(status);
    applyBuildStatus(status,sentDraft);
  } : null);
  switchTab(document.querySelector('[data-tab="run"]'));
}

function applyBuildStatus(result, sentDraft = {...S.projectDraft}) {
  S.profileRevision = result.profile_revision || S.profileRevision;
  const sameSelection = S.projectDraft.PRESET === sentDraft.PRESET;
  Object.entries(result.build_values || {}).forEach(([key,value]) => {
    const previous = S.projectConfig[key];
    S.projectConfig[key] = value;
    if ((BUILD_KEYS.includes(key) && sameSelection && S.projectDraft[key] === sentDraft[key]) ||
        (!BUILD_KEYS.includes(key) && !S.configTouched.has(key) && S.projectDraft[key] === sentDraft[key] &&
          (S.projectDraft[key] === previous || S.projectDraft[key] === value))) {
      S.projectDraft[key] = value;
      S.configTouched.delete(key);
    }
  });
  S.buildWorkflow = result.build_workflow || S.buildWorkflow;
  S.projectEpoch = (S.projectEpoch || 0) + 1;
  S.job = null;
  invalidateSchemaPreview();
  taskIdentityChanged();
  $('params-area').innerHTML = '';
  S.paramsData = null; S.paramsForJob = null;
  $('params-toolbar').classList.add('hidden');
  $('run-info').textContent = '构建配置已更新，请重新装配并渲染';
  renderProjectConfig();
}

async function doRun() {
  if (!S.job) return toast("先在「功能与参数」页装配并渲染", false);
  if (taskIdentityDirty()) return toast('任务名或任务 ID 已修改，请先重新装配并渲染', false);
  const r = await post("run", { schema: S.job.schema, func: S.job.func, task_id: S.job.taskId });
  if (r.error) return toast(r.error, false);
  attachConsole(r.sid, `运行 ${S.job.schema}：`);
  switchTab(document.querySelector('[data-tab="run"]'));
}

function taskIdentityDirty() {
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
function resetCleanupPreview() {
  cleanupRevision++;
  $('cleanup-preview').classList.add('hidden');
  $('btn-cleanup-apply').disabled = true;
  $('cleanup-note').textContent = '';
}

async function previewCleanup() {
  if (S.pollTimer || S.pendingRequests) return toast('请等待当前操作结束再清理', false);
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
  $('btn-cleanup-apply').disabled = !r.files.length;
  $('btn-cleanup-apply').onclick = async () => {
    if (epoch !== S.projectEpoch || revision !== cleanupRevision) return;
    if (S.pollTimer || S.pendingRequests) return toast('请等待当前操作结束再清理', false);
    $('btn-cleanup-apply').disabled = true;
    try {
      const result = await post('cleanup_configs', {keep_schema:keep, token:r.token, apply:true});
      if (epoch !== S.projectEpoch || revision !== cleanupRevision) return;
      resetCleanupPreview();
      if (result.error) return toast(result.error, false);
      $('cleanup-note').textContent = result.message + (result.archive ? `；归档位置：${result.archive}` : '');
      toast(result.message);
    } catch (error) {
      if (epoch === S.projectEpoch) { resetCleanupPreview(); toast(error.message, false); }
    }
  };
}

function attachConsole(sid, title, onDone = null) {
  S.sid = sid; S.since = 0;
  $("btn-export-log").disabled = false;
  const con = $("run-console");
  con.textContent = title + "\n";
  $("run-status").className = "badge running hidden";
  if (S.pollTimer) clearInterval(S.pollTimer);
  S.pollTimer = setInterval(async () => {
    const r = await get("output", `sid=${sid}&since=${S.since}`);
    if (sid !== S.sid) return;
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
      if (onDone) await onDone(r);
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
