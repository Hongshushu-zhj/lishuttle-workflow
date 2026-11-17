<script setup lang="ts">
import {computed,onMounted} from 'vue';
import type {Workbench} from '../app/useWorkbench';
import JsonReport from '../shared/JsonReport.vue';
import PathField from '../shared/PathField.vue';
const {w}=defineProps<{w:Workbench}>();const s=w.s;
const build=computed(()=>s.state.build_workflow||{});
const presets=computed(()=>Object.entries(s.detection?.presets||build.value.presets||{}));
const dll=computed(()=>s.dllPreview||build.value.dll||{});
onMounted(()=>{if(!s.runtime.busy)void w.previewDll();});
</script>
<template>
 <div class="page-heading"><div><div class="eyebrow">BUILD PREPARATION</div><h1>选择本次使用的程序</h1><p>已有可用程序可直接复用；需要更新源码时再编译。</p></div><el-tag :type="build.built?'success':'warning'">{{build.built?'已识别匹配程序':'程序待确认'}}</el-tag></div>
 <div class="grid-two">
  <section class="card">
   <div class="card-heading"><span class="card-icon">B</span><div><h2>构建目标</h2><p>采用当前项目实际提供的构建预设</p></div></div>
   <label class="field"><span>构建预设</span><el-select :model-value="s.draft.PRESET" filterable placeholder="选择预设" @change="w.selectPreset" :disabled="s.runtime.busy||!!s.pending"><el-option v-for="[name,preset] in presets" :key="name" :value="name" :label="name+' · '+((preset as any).mode||(preset as any).build_type||'项目预设')"/></el-select></label>
   <PathField :model-value="s.draft.DLL_ROOT||''" @update:model-value="w.setDllRoot" :label="w.labels.DLL_ROOT" hint="选择 Dll 根目录，构建预设会使用其中的 Debug 或 Release 子目录。" :disabled="s.runtime.busy||!!s.pending"/>
   <div class="info-box" aria-live="polite"><template v-if="s.dllPreviewBusy">正在核对动态库子目录…</template><template v-else><strong>实际动态库目录</strong><p class="mono">{{dll.source||s.draft.DLL_SRC||'选择预设与动态库根目录后显示'}}</p><p>{{dll.message}}</p><el-tag v-if="dll.compatibility" type="warning">兼容旧版直接来源</el-tag></template></div>
   <div class="form-grid"><label class="field" v-for="key in ['BUILD_SUBDIR','INSTALL_SUBDIR','EXE_NAME']" :key="key"><span>{{w.labels[key]}}</span><el-input :model-value="s.draft[key]" readonly/></label></div>
   <div class="info-box">构建目录与程序文件名由预设确定。应用此目标后，运行 XML 列表随构建目录切换。</div>
   <div class="button-row"><el-button type="primary" plain @click="w.useExecutable" :disabled="!s.state.project||s.runtime.busy||!!s.pending">使用已有程序</el-button><el-button @click="w.run('重新检测构建',w.refreshBuild)" :disabled="!s.state.project||s.runtime.busy||!!s.pending">重新检测</el-button></div>
  </section>
  <section class="card">
   <div class="card-heading"><span class="card-icon teal">✓</span><div><h2>程序可用状态</h2><p>检测结果与正在进行的编译分别显示</p></div></div>
   <div class="build-state" :class="{success:build.built}"><span>{{build.built?'✓':'○'}}</span><div><h3>{{build.built?'找到可复用程序':'尚未确认匹配程序'}}</h3><p>{{build.reason||build.message||(build.built?'核对程序路径后可进入任务与输入阶段。':'检查预设、构建目录与程序名，或开始编译。')}}</p></div></div>
   <dl class="definition-list"><dt>当前预设</dt><dd>{{s.state.project_config?.PRESET||'未配置'}}</dd><dt>实际程序</dt><dd class="mono">{{build.exe||build.executable||build.exe_path||'查看下方检测详情'}}</dd><dt>任务状态</dt><dd>{{s.runtime.busy?(s.runtime.label||'后台执行中'):'当前空闲'}}</dd></dl>
   <JsonReport :data="build" title="查看构建、程序与工具完整检测结果"/>
  </section>
 </div>
 <section class="card">
  <div class="card-heading"><span class="card-icon teal">D</span><div><h2>准备当前程序的动态库</h2><p>先比较来源与 Bin，再备份并更新缺少或内容不同的 DLL。</p></div></div>
  <p v-if="!w.dllTargetApplied()" class="muted">构建或根目录草稿尚未应用，请先使用已有程序或编译当前配置。</p>
  <p v-if="s.dllStatus" aria-live="polite">相同 {{s.dllStatus.counts?.same||0}} 个 · 缺少 {{s.dllStatus.counts?.missing||0}} 个 · 内容不同 {{s.dllStatus.counts?.different||0}} 个</p>
  <div class="button-row"><el-button @click="w.compareDlls" :disabled="!build.built||!w.dllTargetApplied()||s.runtime.busy||!!s.pending">比较当前 DLL</el-button><el-button type="primary" plain @click="w.syncDlls" :disabled="!s.dllStatus?.pending||!w.dllTargetApplied()||s.runtime.busy||!!s.pending">准备 DLL（备份并替换）</el-button></div>
  <JsonReport v-if="s.dllStatus" :data="s.dllStatus" title="查看 DLL 文件比较与准备结果"/>
 </section>
 <section class="card">
  <div class="card-heading"><span class="card-icon lilac">↗</span><div><h2>体检与编译</h2><p>操作期间锁定关联资源，日志持续写入底部抽屉</p></div></div>
  <div class="action-tiles"><div><h3>项目体检</h3><p>核验配置与环境，定位缺少的构建条件。</p><el-button @click="w.toolkit('doctor')" :disabled="!s.state.project||s.runtime.busy||!!s.pending">运行体检</el-button></div><div><h3>增量编译</h3><p>使用所选预设和本机工具链编译。不会自动开始计算。</p><el-button type="primary" @click="w.toolkit('build')" :disabled="!s.state.project||s.runtime.busy||!!s.pending">编译所选配置</el-button></div><div><h3>当前操作</h3><p>{{s.runtime.busy?(s.runtime.label||s.runtime.phase):'没有正在执行的后台任务'}}</p><el-button v-if="s.runtime.busy" type="danger" plain @click="w.cancel" :disabled="s.runtime.external||!s.runtime.sid">取消当前操作</el-button><el-button v-else @click="s.logOpen=true">查看日志</el-button></div></div>
 </section>
</template>
