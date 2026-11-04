<script setup lang="ts">
import ProjectArchive from '../ProjectArchive.vue'
import {useStudio} from '../studioContext'
import AppIcon from '../AppIcon.vue'
const s=useStudio()
</script>
<template><section class="overview-page"><div class="overview-intro"><span class="eyebrow">制作流程</span><h2>从资料到入画对话</h2><p>按顺序准备内容，每一步可成组生成。修改自动保存，AI内容可以直接用于下一步；人工核对是可选操作。</p><button v-if="s.checklist.value.nextAction" class="primary" @click="s.navigate(s.checklist.value.nextAction.page)">继续：{{s.checklist.value.nextAction.label}}<AppIcon name="arrow" :size="15"/></button></div><div class="workflow-map"><button v-for="(step,i) in s.checklist.value.pages||[]" class="workflow-step" @click="s.navigate(step.id)"><span class="step-number">{{Number(i)+1}}</span><h3>{{step.name}}</h3><b>{{step.complete?(step.done<step.total?'可继续 · 部分待补充':'已完成 · 可以继续'):step.blocker?'等待必要输入':'未完成'}}</b><p>{{step.blocker||`${step.done}/${step.total} 组内容可用`}}</p><span class="workflow-link">{{step.complete?'查看或调整':'进入此步骤'}}<AppIcon name="arrow" :size="15"/></span></button></div><p>基础人物来自资料整理，完整知识和人设在线索之后集中准备，无需来回确认。分镜视频保留单独审核和提交。</p><ProjectArchive/></section></template>
