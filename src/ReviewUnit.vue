<script setup lang="ts">
import {computed} from 'vue'
import {useStudio} from './studioContext'
import ReviewBadge from './ReviewBadge.vue'
const props=defineProps<{unitId:string,label?:string}>(),s=useStudio(),unit=computed(()=>s.unit(props.unitId))
</script>
<template><div class="review-unit"><ReviewBadge :unit="unit"/><button v-if="unit?.canConfirm&&(unit.status!=='human'||unit.outdated)" :disabled="s.reviewing.value===unitId" @click="s.confirmUnit(unitId)">{{label||'确认内容'}}</button><small v-if="unit?.status==='incomplete'">{{unit.issues[0]}}</small></div></template>
<style scoped>.review-unit{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:12px 0}.review-unit button{font-size:12px;padding:6px 12px}.review-unit small{font-size:11px;color:#8b9296}</style>
