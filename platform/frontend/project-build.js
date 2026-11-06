/* project-build — plain script; shared application state is composed in app.js. */
"use strict";

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
  if (!S.buildWorkflow?.built && (MACHINE_KEYS.some(key => !S.projectConfig[key]) || (S.machineDetection.filled || []).length)) {
    $("machine-config-form").classList.remove('hidden');
    $("btn-machine-config").setAttribute('aria-expanded', 'true');
  }
  $("local-path-fields").innerHTML = '';
  $("local-path-status").textContent = '选择地图与任务运行配置后识别本地路径。';
  $("task-binding-note").textContent = '选择工参及地图后可保存；对应关系仅在当前项目生效。';
  S.projectEpoch = (S.projectEpoch || 0) + 1;
  S.job = null;
  S.workflow = null; S.runVerdict = null; S.assemblyUnconfirmed=false;
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
  S.resultSid = 0; S.resultContext = null;
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
  renderFuncRadios(S.functions.includes("pred") ? "pred" : S.functions[0]);
  fillSelect($("project"), st.projects, st.project);
  $("project").value = st.project;
  const projectName = String(st.project || '').replace(/[\\/]+$/, '').split(/[\\/]/).pop();
  $('current-project-name').textContent = projectName ? `当前项目：${projectName}` : '请选择项目';
  $('current-project-path').textContent = st.project || '尚未选择项目';
  $('current-project-path').title = st.project || '';
  $("map-root").value = st.map_root;
  $("gongcan-root").value = st.gongcan_root;
  renderCities(st.cities);
  renderTasks(st.tasks);
  $("env-note").textContent = `预设 ${st.preset} · 输出根 ${st.out_root}`;
  if (typeof fetch === 'function' && S.profileId) refreshProjectDetection();
  if (st.runtime) applyRuntimeState(st.runtime, true);
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
    ` · 程序：${status?.built ? (status.executable || draft.EXE_NAME || '已识别') + '（仅确认文件存在；最新源码是否编译成功请查看本次日志）' : '编译后自动识别'}`;
}
function chooseBuildMode(mode) {
  const presets = buildPresets();
  const names = Object.keys(presets).filter(name => buildMode(presets[name],name) === mode);
  if (!names.length) return focusSetupIssue({target:'build-mode',section:'build',message:`项目没有兼容的 ${mode === 'debug' ? 'Debug' : 'Release'} 预设，请检查 CMakePresets.json`});
  clearSetupIssue();
  changeProjectConfigChoice('PRESET',names.includes(S.projectDraft.PRESET) ? S.projectDraft.PRESET : names[0]);
}
function renderWorkflowGuide() {
  refreshWorkflow();
  // Legacy hook retained for integrations using the previous guide.
  $('workflow-steps').innerHTML = '<li>项目 → 程序编译或复用 → 输入 → 装配 → 检查 → 运行</li>';
}
function clearSetupIssue() {
  document.querySelectorAll('.field-invalid').forEach(el=>{el.classList.remove('field-invalid');el.removeAttribute('aria-invalid');});
  $('setup-validation').textContent = '';
}
function focusSetupIssue(issue) {
  clearSetupIssue();
  focusStage(({project:'project',machine:'build','project-add':'project',build:'build',input:'inputs'})[issue.section] || 'check');
  const form = {project:'project-config',machine:'machine-config','project-add':'project-add'}[issue.section];
  if (form) {
    $(form+'-form').classList.remove('hidden');
    $('btn-'+form).setAttribute('aria-expanded','true');
  }
  if (issue.section === 'input') {
    const tab = document.querySelector('[data-tab="params"]');
    focusStage('inputs');
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
  if (!guardCsvChanges() || S.xmlDirty) return toast('请先保存未完成的编辑',false);
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
  if (S.inputTransition || S.parameterWrites || !guardCsvChanges() || S.xmlDirty) {
    $('project').value=S.project;
    if (S.xmlDirty) toast('请先保存或放弃未保存的参数编辑',false);
    return;
  }
  return withInputTransition(() => changeProjectTransition(action, path));
}

async function changeProjectTransition(action, path) {
  if (!guardCsvChanges()) { $("project").value=S.project; return; }
  if (S.xmlDirty) { $("project").value=S.project; return toast("请先保存未完成的参数编辑",false); }
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
    for (const id of ['project', 'btn-project-add']) {
      const node = $(id);
      // The response can capture this request's temporary disable as the
      // runtime lock's baseline. Restore its idle value without bypassing
      // an actual runtime owner that may have rejected the switch.
      if (runtimeDisabled.has(node)) runtimeDisabled.set(node, false);
      node.disabled = !!S.runtime?.busy;
    }
  }
}


async function toolkit(step) {
  if (S.inputTransition || S.parameterWrites || !guardCsvChanges() || S.xmlDirty) return;
  return withInputTransition(() => toolkitTransition(step));
}

async function toolkitTransition(step) {
  if (!guardCsvChanges() || S.xmlDirty) return toast('请先保存未完成的编辑',false);
  if (S.pollTimer || S.pendingRequests) return toast('请等待当前操作结束',false);
  let epoch = S.projectEpoch;
  let sentDraft = {...S.projectDraft};
  const r = await post("toolkit", { step, ...(step === 'build' ? {preset:S.projectDraft?.PRESET || ''} : {}) });
  if (epoch !== S.projectEpoch) return;
  if (r.error) return setupError(r);
  if (r.runtime) applyRuntimeState(r.runtime);
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
  showOperation(step === 'build' ? '编译输出' : '项目体检输出');
  focusStage('build');
}

async function useExecutable() {
  if (S.inputTransition || S.parameterWrites || !guardCsvChanges() || S.xmlDirty) return;
  return withInputTransition(() => useExecutableTransition());
}

async function useExecutableTransition() {
  if (!guardCsvChanges() || S.xmlDirty || S.runtime?.busy || S.pendingRequests || S.pollTimer) return;
  if (!selectedBuildStatus()?.built) return toast('所选配置未识别到可用程序，请先编译',false);
  const epoch=S.projectEpoch;
  const sentDraft={...S.projectDraft};
  const changed=BUILD_KEYS.some(key=>(S.projectDraft?.[key] || '') !== (S.projectConfig?.[key] || ''));
  try {
    if(changed) {
      const values=Object.fromEntries(Object.keys(PROFILE_LABELS).filter(key=>!MACHINE_KEYS.includes(key))
        .map(key=>[key,BUILD_KEYS.includes(key) ? S.projectDraft[key] || '' : S.projectConfig[key] || '']));
      const result=await post('save_project_config',{values});
      if(epoch !== S.projectEpoch) return;
      if(result.error) return setupError(result);
      // Applying only the build selection preserves independent resource/input drafts.
      applyBuildStatus({...result, build_values:Object.fromEntries(BUILD_KEYS.map(key=>[key,result.project_config?.[key] || '']))}, sentDraft);
    } else {
      const result=await post('build_status',{});
      if(epoch !== S.projectEpoch) return;
      if(result.error) return setupError(result);
      // Refresh discovery without resetting an existing matching assembly.
      if(Object.entries(result.build_values || {}).some(([key,value])=>S.projectConfig[key] !== value)) applyBuildStatus(result);
      else { S.buildWorkflow=result.build_workflow || S.buildWorkflow; refreshWorkflow(); }
    }
    if(!S.buildWorkflow?.built) return toast('程序尚不可用，请查看程序准备阶段',false);
    focusStage('inputs'); toast('已使用匹配程序，请继续选择任务与输入');
  } catch(error) { toast('应用程序配置失败：'+error.message,false); }
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
