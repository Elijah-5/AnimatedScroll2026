<script setup lang="ts">
import {computed} from 'vue'
import ImportPanel from '../ImportPanel.vue'
import DocumentLibrary from '../DocumentLibrary.vue'
import LibrarySummary from '../LibrarySummary.vue'
import StructuredLibrary from '../StructuredLibrary.vue'
import {useStudio} from '../studioContext'
const s=useStudio(),emit=defineEmits(['replace','running'])
const hasData=computed(()=>!!s.rec('material','main')?.draft.structured||!!s.p.value.characters.length&&!!s.p.value.sources.length)
</script>
<template><div data-entity-key="material:main" class="library-page">
 <details class="source-tools" :open="!hasData"><summary>资料来源 · {{s.p.value.documents.length}} 份文献 <span>添加文件或文本</span></summary><DocumentLibrary compact/></details>
 <details class="source-tools painting-tools" open><summary>画作与画中人物 <span>上传画作、检测与身份对应</span></summary><ImportPanel :project="s.p.value" studio hide-documents @replace="emit('replace',$event)" @running="emit('running',$event)" @confirm-materials="s.confirm(s.rec('material','main'),false)"/></details>
 <LibrarySummary @running="emit('running',$event)"/>
 <details class="source-tools"><summary>高级资料编辑与兼容记录</summary><StructuredLibrary/></details>
</div></template>
<style scoped>.source-tools{margin-bottom:24px;border:1px solid #e1e6da;background:#fbfcf7;border-radius:11px;padding:16px 20px}.source-tools>summary{cursor:pointer;font-size:13px;color:#5b7450;font-weight:600}.source-tools>summary span{font-size:11px;font-weight:400;color:#95a08b;margin-left:12px}.source-tools[open]>summary{margin-bottom:20px}.painting-tools :deep(.visual-grid){max-height:560px;overflow:auto}.painting-tools :deep(.canvas-panel){max-height:530px}.painting-tools :deep(.canvas-panel canvas){max-height:470px}</style>
