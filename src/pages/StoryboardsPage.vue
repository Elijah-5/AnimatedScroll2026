<script setup lang="ts">
import {ref,computed,watch} from 'vue'
import {useStudio,state,states} from '../studioContext'
import EntityActions from '../EntityActions.vue'
import ReviewUnit from '../ReviewUnit.vue'
import ReviewBadge from '../ReviewBadge.vue'
import AppIcon from '../AppIcon.vue'
import RegionPicker from '../RegionPicker.vue'
import Portrait from '../Portrait.vue'
import VideoPanel from '../VideoPanel.vue'
import MediaPreviewPanel from '../MediaPreviewPanel.vue'
const s=useStudio(),selected=ref(''),scope=ref('narrative'),checked=ref<string[]>([])
const clues=computed(()=>s.entries('clue').filter((c:any)=>scope.value==='all'||c.draft.type==='narrative'))
const visibleIds=computed<string[]>(()=>clues.value.map((c:any)=>c.id))
const shots=computed(()=>s.entries('storyboard').filter((shot:any)=>visibleIds.value.includes(shot.draft.clueId)))
const r=computed(()=>shots.value.find((r:any)=>r.id===selected.value)||shots.value[0])
const mediaIds=computed(()=>checked.value.filter(id=>shots.value.some((shot:any)=>shot.id===id)))
watch(scope,()=>{checked.value=[]})
function generate(regenerate=false,one=''){void s.generateStep('storyboards',one?[one]:checked.value.length?checked.value:visibleIds.value,regenerate,'storyboard',scope.value)}
watch(()=>s.focus.value,(v:string)=>{if(v.startsWith('storyboard:'))selected.value=v.split(':')[1]},{immediate:true})
</script>
<template><section class="shot-scope"><label>生成范围<select v-model="scope"><option value="narrative">仅叙事线索（默认）</option><option value="all">全部线索</option></select></label><div class="actions"><button :disabled="s.generating.value||!visibleIds.length" @click="generate()">生成当前范围的缺失提示词</button><button :disabled="s.generating.value||!checked.length" @click="generate(true)">重新生成所选提示词</button></div><p>当前 {{clues.length}} 条线索。勾选分镜后可只为选中内容制作预览，已有其他分镜保留。</p><label v-for="c in clues" :key="c.id" class="shot-check"><input type="checkbox" :value="c.id" v-model="checked">{{c.draft.name}}</label></section><MediaPreviewPanel :ids="mediaIds" :scope="scope" :visible-ids="visibleIds"/><div class="workspace-two"><aside class="entity-rail"><h2>分镜管理</h2><small>每条线索一个分镜，独立制作。</small><button v-for="shot in shots" :class="{selected:shot.id===r?.id}" @click="s.selectEntity('storyboard',shot.id)"><b>{{s.rec('clue',shot.draft.clueId)?.draft.name||shot.draft.name}}</b><ReviewBadge :unit="s.unit('storyboard:'+shot.id)"/></button></aside><article v-if="r" :data-entity-key="'storyboard:'+r.id"><fieldset :disabled="s.locked('storyboard',r.id)"><h2>{{s.rec('clue',r.draft.clueId)?.draft.name}}</h2><button @click="s.navigate('clues','clue:'+r.draft.clueId)">查看对应线索</button><details><summary>参与人物与画面区域（自动选择，可调整）</summary><fieldset><legend>参与人物</legend><label v-for="c in s.entries('character').filter((c:any)=>c.draft.depictionScope!=='background')"><input type="checkbox" :value="c.id" v-model="r.draft.characterIds" @change="r.draft.participantsConfirmed=false">{{c.draft.name}}</label><small>{{r.draft.characterIds.length?'已选择参与人物':'无人出镜'}}</small></fieldset><RegionPicker :image="s.p.value.image" v-model="r.draft.region"/><Portrait v-if="r.draft.region" :url="s.p.value.image" :box="r.draft.region"/></details><button :disabled="s.busy.value||s.generating.value" title="生成期间不能重复提交任务" class="primary" @click="generate(true,r.id)"><AppIcon name="ai" :size="14"/>{{r.draft.prompt?'重新生成':'首次生成'}}此分镜提示词</button><small>生成文生视频提示词和首尾画面描述，不调用视频生成服务。</small><fieldset :disabled="s.locked('storyboard',r.id,'prompt')"><details><summary>动作、运镜、风格与首尾画面（自动补齐）</summary><label>主体与动作<textarea v-model="r.draft.action"/></label><label>镜头运动<textarea v-model="r.draft.camera"/></label><label>风格与限制<textarea v-model="r.draft.style"/></label><div class="compact-grid"><label>起始画面<textarea rows="5" v-model="r.draft.startFrame"/></label><label>结束画面<textarea rows="5" v-model="r.draft.endFrame"/></label></div></details><label>完整文生视频提示词<textarea rows="8" v-model="r.draft.prompt"/></label></fieldset><ReviewUnit :unit-id="'storyboard:'+r.id" label="确认此分镜"/></fieldset><VideoPanel :storyboard-id="r.id"/></article><article v-else><div class="empty">生成线索后即可制作分镜。</div></article></div></template>

<style scoped>.shot-scope{padding:18px;border:1px solid var(--border);border-radius:10px;margin-bottom:18px}.shot-scope>label:first-child{max-width:280px}.shot-scope p{font-size:12px;color:#718177}.shot-check{display:inline-flex;align-items:center;gap:6px;margin:8px 18px 8px 0;font-size:12px}.shot-check input{width:auto}</style>
