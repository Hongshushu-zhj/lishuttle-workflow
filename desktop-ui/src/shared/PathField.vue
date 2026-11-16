<script setup lang="ts">
import {FolderOpened,Document,CopyDocument,Select} from '@element-plus/icons-vue';
import {pickPath,openPath} from './desktop';
const props=withDefaults(defineProps<{modelValue?:string;label?:string;kind?:'directory'|'file';placeholder?:string;disabled?:boolean;extensions?:string[];hint?:string}>(),{modelValue:'',kind:'directory'});
const emit=defineEmits<{(e:'update:modelValue',value:string):void}>();
async function copy(){await navigator.clipboard.writeText(props.modelValue||'');}
async function browse(){const path=await pickPath(props.kind,props.modelValue,props.extensions);if(path)emit('update:modelValue',path);}
</script>
<template><label class="path-field"><span v-if="label" class="field-label">{{label}}</span><span class="path-control"><el-input :model-value="modelValue" :disabled="disabled" :placeholder="placeholder||'输入或选择本机路径'" @update:model-value="emit('update:modelValue',$event)" :title="modelValue"/><el-button :icon="kind==='file'?Document:FolderOpened" :disabled="disabled" @click="browse" title="选择本机路径" aria-label="选择本机路径"/><el-button :icon="Select" @click="openPath(modelValue||'')" :disabled="!modelValue" title="打开路径" aria-label="打开路径"/><el-button :icon="CopyDocument" @click="copy" :disabled="!modelValue" title="复制完整路径" aria-label="复制完整路径"/></span><small v-if="hint">{{hint}}</small></label></template>
