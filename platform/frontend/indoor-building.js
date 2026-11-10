/* Source-only indoor export switch. The executable still needs rebuilding. */
"use strict";

function refreshIndoorBuildingButtons() {
  const state = S.indoorBuildingExport, info = state?.info;
  const button = $('btn-enable-indoor-building');
  if (!button) return;
  const current = state && state.project === S.project && state.epoch === S.projectEpoch && S.func === 'predindoor';
  button.disabled = !current || !info?.supported || info.enabled !== false || !info.revision ||
    !!S.indoorExportSaving || !!S.runtime?.busy || !!S.pollTimer || !!S.inputTransition || !!S.xmlDirty || !!S.parameterWrites;
  const reload = $('btn-reload-indoor-building');
  if (reload) reload.disabled = !!S.indoorExportSaving;
}

function renderIndoorBuildingExport(catalog) {
  const panel = $('indoor-building-panel');
  if (!panel) return;
  const visible = catalog?.function === 'predindoor' && S.func === 'predindoor' && !!S.job;
  panel.classList[visible ? 'remove' : 'add']('hidden');
  if (!visible) { S.indoorBuildingExport = null; return; }
  const info = catalog.indoor_building_export || {supported:false, reason:'尚未读取源码状态，请点击重新检查。'};
  const previous = S.indoorBuildingExport;
  if (previous && previous.project === S.project && previous.epoch === S.projectEpoch && previous.job === S.job) {
    previous.info = info;
  } else {
    S.indoorBuildingExport = {project:S.project,epoch:S.projectEpoch,job:S.job,info};
  }
  if (S.paramsData?.function === 'predindoor') S.paramsData.indoor_building_export = info;
  $('indoor-building-status').textContent = !info.supported
    ? `暂不能自动开启：${info.reason || '无法确认当前源码的导出开关'}；保留原文件。`
    : info.enabled
      ? '源码开关已开启（true）。修改后须重新编译所选配置，再运行室内预测；已有程序不会自动更新。'
      : '源码开关未开启（false）。点击启用后会备份并修改当前项目源码，随后必须重新编译所选配置。';
  $('btn-enable-indoor-building').onclick = enableIndoorBuildingExport;
  $('btn-reload-indoor-building').onclick = reloadIndoorBuildingExport;
  $('btn-indoor-building-build').onclick = () => focusStage('build');
  refreshIndoorBuildingButtons();
}

async function reloadIndoorBuildingExport() {
  const project = S.project, epoch = S.projectEpoch;
  if (!project || S.func !== 'predindoor' || S.indoorExportSaving) return;
  const request = S.indoorExportRequest = (S.indoorExportRequest || 0) + 1;
  try {
    const info = await get('indoor_building_export');
    if (project !== S.project || epoch !== S.projectEpoch || request !== S.indoorExportRequest || S.func !== 'predindoor') return;
    if (info.error) throw Error(info.error);
    if (typeof invalidateParameterReads === 'function') invalidateParameterReads();
    renderIndoorBuildingExport({function:'predindoor',indoor_building_export:info});
  } catch (error) {
    if (project === S.project && epoch === S.projectEpoch && request === S.indoorExportRequest && S.func === 'predindoor') {
      $('indoor-building-status').textContent = `源码状态读取失败：${error.message}；请重新检查。`;
    }
  }
}

async function enableIndoorBuildingExport() {
  const state = S.indoorBuildingExport;
  if (!state || state.project !== S.project || state.epoch !== S.projectEpoch || S.func !== 'predindoor') return;
  if (S.runtime?.busy || S.pollTimer || S.inputTransition || S.indoorExportSaving || S.xmlDirty || S.parameterWrites || S.pendingRequests || !guardCsvChanges()) {
    return toast('请先完成当前操作并保存编辑，再开启室内建筑导出。', false);
  }
  if (!state.info.supported || state.info.enabled !== false || !state.info.revision) return;
  S.indoorExportSaving = true;
  if (typeof invalidateParameterReads === 'function') invalidateParameterReads();
  S.indoorExportRequest = (S.indoorExportRequest || 0) + 1;
  refreshIndoorBuildingButtons();
  try {
    const info = await post('enable_indoor_building_export', {revision:state.info.revision});
    if (state !== S.indoorBuildingExport || state.project !== S.project || state.epoch !== S.projectEpoch || S.func !== 'predindoor') return;
    if (info.error || info.ok === false) throw Error(info.message || info.error || '开启失败');
    if (typeof invalidateParameterReads === 'function') invalidateParameterReads();
    renderIndoorBuildingExport({function:'predindoor',indoor_building_export:info});
    if (typeof workflowContentChanged === 'function') workflowContentChanged('室内建筑导出源码已修改，请重新编译后检查');
    toast('已开启 building.txt 源码导出；请前往“程序准备”重新编译所选配置。');
  } catch (error) {
    if (state === S.indoorBuildingExport && state.project === S.project && state.epoch === S.projectEpoch && S.func === 'predindoor') {
      $('indoor-building-status').textContent = `未完成开启：${error.message}；请重新检查源码后重试。`;
      toast($('indoor-building-status').textContent, false);
    }
  } finally {
    S.indoorExportSaving = false;
    refreshIndoorBuildingButtons();
  }
}
