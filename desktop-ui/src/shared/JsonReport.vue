<script setup lang="ts">defineProps<{title?:string;data:any}>();</script>
<template><details class="json-report"><summary>{{title||'查看完整报告与路径'}}</summary><pre>{{JSON.stringify(data,null,2)}}</pre></details></template>
