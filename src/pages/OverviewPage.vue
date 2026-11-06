<script setup lang="ts">
import {computed,ref} from 'vue'
import ProjectArchive from '../ProjectArchive.vue'
import WorkflowDiagram from '../WorkflowDiagram.vue'
import {useStudio} from '../studioContext'
import {creationPages} from '../navigation'
import AppIcon from '../AppIcon.vue'
const s=useStudio(),subflow=ref<HTMLElement>()
const steps=computed(()=>[...creationPages.filter(p=>p.id!=='overview'),{id:'experience',name:'欣赏作品'}].map(p=>{
 const state=s.checklist.value.pages?.find((r:any)=>r.id===p.id)
 return {id:p.id,label:p.id==='characters'?'人物档案与对话设定':p.name,status:!state?'':state.complete?'可继续':state.blocker?'等待必要输入':'待准备',description:state?state.blocker||`${state.done}/${state.total} 组内容可用`:'',action:p.id==='library'?'查看资料整理流程':''}
}))
const edges=computed(()=>steps.value.slice(1).map((n,i)=>({from:steps.value[i]!.id,to:n.id})))
const subnodes=[
 {id:'sources',label:'添加多个来源',description:'PDF、文本及图片',column:0,row:0},
 {id:'parse',label:'解析与原文定位',description:'保留来源、页码和版本',column:1,row:0},
 {id:'extract',label:'提取人物与信息',description:'按来源保留逐字依据',column:2,row:0},
 {id:'reconcile',label:'归并与矛盾识别',description:'仅突出不可调和的矛盾',column:3,row:0},
 {id:'library',label:'统一结构化资料库',description:'人物、事件、关系与判断',column:4,row:0},
 {id:'summary',label:'摘要面板',description:'先看核心，按需展开',column:5,row:0},
 {id:'feedback',label:'智能修改',description:'自然语言确定修改方向',column:5,row:1},
 {id:'revise',label:'局部结构化与校验',description:'直接更新，可以撤销',column:4,row:1},
 {id:'evidence',label:'展开详情与原文',description:'回到对应来源核对',column:2,row:1},
]
const subedges=[{from:'sources',to:'parse'},{from:'parse',to:'extract'},{from:'extract',to:'reconcile'},{from:'reconcile',to:'library'},{from:'library',to:'summary'},{from:'summary',to:'feedback'},{from:'feedback',to:'revise'},{from:'revise',to:'library'},{from:'summary',to:'evidence',secondary:true}]
function reveal(){subflow.value?.scrollIntoView({behavior:'smooth',block:'start'});subflow.value?.focus({preventScroll:true})}
</script>
<template><section class="overview-page">
 <div class="overview-intro"><span class="eyebrow">制作流程</span><h2>从资料到入画对话</h2><p>先整理依据，再逐步创作。修改自动保存，每一步都可以回看和调整。</p><button v-if="s.p.value&&s.checklist.value.nextAction" class="primary" @click="s.navigate(s.checklist.value.nextAction.page)">继续：{{s.checklist.value.nextAction.label}}<AppIcon name="arrow" :size="15"/></button></div>
 <section class="overview-flow"><div class="workflow-heading"><h3>完整制作流程</h3><span>点击步骤进入工作区</span></div><WorkflowDiagram label="完整制作流程" :nodes="steps" :edges="edges" interactive @navigate="s.navigate($event)" @action="reveal"/><p class="flow-caption">基础人物来自资料整理，完整知识与对话设定在线索之后准备。分镜视频仍单独审核和提交。</p></section>
 <section ref="subflow" tabindex="-1" class="overview-subflow" aria-label="画作资料整理子流程"><div class="workflow-heading"><div><span class="subflow-tag">SUB-WORKFLOW · 资料与基础人物</span><h3>画作资料整理</h3></div><button @click="s.navigate('library')">进入资料库 →</button></div><p class="flow-caption">多个来源归为一份资料。先读摘要，只处理真正的矛盾；选中任意结果，用智能修改继续改进。</p><WorkflowDiagram label="画作资料整理子流程" :nodes="subnodes" :edges="subedges"/></section>
 <ProjectArchive/>
</section></template>
<style scoped>.overview-flow{margin-bottom:28px}.overview-subflow{border:1px solid #dce6de;background:#f7faf5;border-radius:14px;padding:24px;margin:28px 0 36px;scroll-margin-top:110px}.overview-subflow:focus{outline:2px solid #7ba48c;outline-offset:4px}.overview-subflow .workflow-heading h3{margin-top:9px;font-size:16px}.subflow-tag{font-size:9px;color:#7d9684;letter-spacing:.08em}.flow-caption{font-size:12px;color:#809087;line-height:1.9}.workflow-heading button{font-size:11px;white-space:nowrap}</style>
