<script setup lang="ts">
import AppIcon from './AppIcon.vue'
defineProps<{unit?:any}>()
const labels:any={incomplete:'待补全',AI:'AI',human:'人工'}
const icons:any={incomplete:'incomplete',AI:'ai',human:'human'}
</script>
<template><span v-if="unit" class="review-badges"><span class="review-badge" :class="unit.status" :title="unit.status==='human'?'人工填写或已统一核对':unit.status==='AI'?'包含未人工核对的自动生成内容':unit.issues?.join('；')"><AppIcon :name="icons[unit.status]" :size="15"/>{{labels[unit.status]}}</span><span v-if="unit.outdated" class="review-badge outdated" title="实际使用的相关依据已变化，内容仍可使用"><AppIcon name="outdated" :size="15"/>待更新</span></span></template>
<style scoped>.review-badges{display:inline-flex;align-items:center;gap:7px}.review-badge{display:inline-flex;align-items:center;gap:4px;font-size:11px;white-space:nowrap;color:#8b9296}.review-badge.AI{color:#b18b31}.review-badge.human{color:#528877}.review-badge.incomplete,.review-badge.outdated{color:#899297}</style>
