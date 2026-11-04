<script setup lang="ts">
import {computed} from 'vue'
import {useStudio} from './studioContext'
const props=defineProps<{record:any}>()
const s=useStudio()
const notices=computed(()=>props.record.basisWarnings||[])
const labels:Record<string,string>={name:'名称',summary:'简介／摘要',identity:'身份',biography:'经历',relationships:'人物关系',body:'剧情内容',goal:'目标',theme:'主题',characterIds:'参与人物',clueIds:'关联线索',materialInputs:'三段资料',sources:'依据资料',annotations:'画面人物对应',image:'原画',imageVersion:'原画版本',style:'风格',region:'画面区域',prompt:'完整提示词',startFrame:'起始画面',endFrame:'结束画面',historySnapshot:'历史资料版本',camera:'运镜',action:'动作',units:'内容及引用'}
function display(value:any){return typeof value==='string'?(value||'（未填写）'):JSON.stringify(value,null,2)||'（无）'}
</script>
<template><div v-if="record.basisError" class="extension-error">历史依据需要处理：{{record.basisError}}</div><details v-if="notices.length" class="version-notice"><summary>基于旧版本{{notices.every((v:any)=>v.reviewed)?' · 已核对，继续使用':' · 内容仍可使用'}}</summary><section v-for="notice in notices" :key="notice.key"><p>{{notice.name}}：依据 r{{notice.fromRevision}}，当前 r{{notice.toRevision}}{{notice.reviewed?'（已核对）':''}}</p><details v-for="change in notice.changes" :key="change.field"><summary>{{labels[change.field]||change.field}}</summary><div class="columns"><pre>{{display(change.before)}}</pre><pre>{{display(change.after)}}</pre></div></details></section><button v-if="notices.some((v:any)=>!v.reviewed)" :disabled="s.busy.value" @click="s.acknowledge(record)">已核对，继续使用</button></details></template>
<style scoped>.version-notice{background:#f6f2e7;color:#685938;border:1px solid #e6dbc3;padding:10px 14px;border-radius:8px;width:100%;margin:8px 0}.version-notice pre{font-size:12px;max-height:220px;overflow:auto;white-space:pre-wrap}.version-notice summary{cursor:pointer}</style>
