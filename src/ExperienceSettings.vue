<script setup lang="ts">
import {computed} from 'vue'
import {useStudio} from './studioContext'
import EntityActions from './EntityActions.vue'
const s=useStudio(),r=computed(()=>s.rec('experience_config','main'))
</script>
<template><section v-if="r" class="experience-settings" data-entity-key="experience_config:main"><h3>体验设置</h3><label>全项目时间视角<select v-model="r.draft.viewpoint"><option value="depicted">画中事件当时（默认）</option><option value="lifetime">人物生平回忆视角</option></select></label><p>连续多轮未触及尚未记录的线索时，推荐可交谈的人物及问题。整场体验共用计数，切换人物不清零；新会话使用确认配置。</p><label><input type="checkbox" v-model="r.draft.enabled">开启线索引导</label><label>连续偏离轮数<input type="number" min="1" max="20" v-model.number="r.draft.offTopicThreshold"></label></section></template>
<style scoped>.experience-settings{border-top:1px solid #dfe5e1;margin-top:26px;padding-top:18px}.experience-settings p{font-size:12px;color:#7b8581;line-height:1.8}</style>
