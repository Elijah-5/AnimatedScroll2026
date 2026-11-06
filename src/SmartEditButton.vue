<script setup lang="ts">
import {useStudio} from './studioContext'
import AppIcon from './AppIcon.vue'
const props=withDefaults(defineProps<{kind:string;itemIds:string[];label:string;fields?:string[];unitIds?:string[]}>(),{fields:()=>[],unitIds:()=>[]})
const s=useStudio()
</script>
<template><button class="smart-edit-button" type="button" :disabled="!itemIds.length||s.busy.value" :aria-label="'智能修改：'+label" @click="s.openSmartEdit({kind:props.kind,section:'content',itemIds,fields,unitIds},label)"><AppIcon name="ai" :size="14"/>智能修改</button></template>
<style scoped>.smart-edit-button{display:inline-flex;align-items:center;gap:6px;font-size:11px;white-space:nowrap;color:#496b55;background:#f2f6ec;border-color:#d9e3d1;padding:7px 11px}.smart-edit-button:hover{border-color:#8da784}.smart-edit-button:focus-visible{outline:2px solid #789b7d;outline-offset:3px}</style>
