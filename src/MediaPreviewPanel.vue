<script setup lang="ts">
import {ref,computed,watch,onMounted,onActivated,onDeactivated,onUnmounted} from 'vue'
import {useStudio} from './studioContext'
const props=defineProps<{ids:string[];scope:string;visibleIds:string[]}>(),s=useStudio()
const jobs=ref<any[]>([]),budget=ref<any>(null),quote=ref<any>(null),busy=ref(false),error=ref(''),kind=ref('video'),requestId=ref('')
const allVisibleJobs=computed(()=>jobs.value.filter(j=>props.visibleIds.includes(j.storyboardId)))
const visibleJobs=computed(()=>allVisibleJobs.value.filter((j,i,all)=>all.findIndex(v=>v.storyboardId===j.storyboardId)===i))
const historicalJobs=computed(()=>allVisibleJobs.value.filter(j=>!visibleJobs.value.some(v=>v.id===j.id)))
const base=()=>`/projects/${s.p.value.id}/media-previews`
async function run(fn:()=>Promise<void>){busy.value=true;error.value='';try{await fn()}catch(e:any){error.value=e.message||String(e)}finally{busy.value=false}}
async function load(){const result=await s.api(base());jobs.value=result.jobs;budget.value=result.budget}
async function estimate(){await run(async()=>{await s.saveAll();quote.value=await s.api(base()+'/quote','POST',{version:s.p.value.version,scope:props.scope,storyboardIds:props.ids,kind:kind.value});requestId.value=crypto.randomUUID()})}
async function submit(){await run(async()=>{const result=await s.api(base(),'POST',{quoteId:quote.value.quoteId,requestId:requestId.value});jobs.value=result.jobs;budget.value=result.budget;quote.value=null;await load()})}
async function review(job:any,accepted:boolean){await run(async()=>{await s.api(base()+`/${job.id}/review`,'POST',{accepted});await load()})}
async function resume(job:any){await run(async()=>{await s.api(base()+`/${job.id}/resume`,'POST',{});await load()})}
watch(()=>JSON.stringify([props.ids,props.scope,kind.value]),()=>{quote.value=null;requestId.value=''})
let timer:ReturnType<typeof setInterval>|undefined
function start(){if(!timer){void run(load);timer=setInterval(()=>{if(!document.hidden)void load().catch(()=>{error.value='暂时无法读取预览进度，任务记录已保留'})},5000)}}
function stop(){clearInterval(timer);timer=undefined}
onMounted(start);onActivated(start);onDeactivated(stop);onUnmounted(stop)
const labels:Record<string,string>={queued:'等待提交',waiting_review:'等待前一条检查',submitting:'正在提交',pending:'正在生成',downloading:'正在下载',succeeded:'已完成',failed:'未成功',submission_unknown:'提交状态待核实',cost_unknown:'费用待核实',paused:'等待继续查询',download_failed:'下载未完成',skipped:'未提交'}
</script>
<template>
 <section class="preview-panel" aria-label="低成本叙事预览">
  <h2>低成本预览</h2><p>勾选 1–3 条分镜后查看费用。先生成第一条，检查通过后逐条继续。</p>
  <p v-if="budget">本轮总上限 ¥{{budget.limitCny}} · 已用及预留 ¥{{budget.reservedCny.toFixed(2)}} · 剩余 ¥{{budget.remainingCny.toFixed(2)}} <span v-if="budget.blocked"> · 有状态待核实，付费生成已暂停</span></p>
  <div class="actions"><label>预览形式<select v-model="kind"><option value="video">低清短片 · 480P / 5 秒</option><option value="image">分镜图片 · 视频不可用时</option><option value="crop">原画局部预览 · 免费</option></select></label><button :disabled="busy||!ids.length||ids.length>3" @click="estimate">生成低成本预览 · 先查看费用</button><small>已选 {{ids.length}} 条</small></div>
  <p v-if="error" role="alert" class="extension-error">{{error}}</p>
  <section v-if="quote" class="preview-quote" aria-label="提交前核对">
   <h3>提交前核对</h3><p>{{quote.model}} · {{quote.items.length}} 条<span v-if="quote.duration"> · 每条 {{quote.duration}} 秒 · {{quote.resolution}} · 无生成音轨</span></p>
   <p>预计 ¥{{quote.estimatedCny.toFixed(2)}}，含余量预留 ¥{{quote.reservedCny.toFixed(2)}}。提交后仅生成第一条。</p>
   <details v-for="item in quote.items" :key="item.storyboardId"><summary>{{item.title}} · {{item.referenceCount}} 张参考图</summary><p>{{item.narrationText}}</p><pre>{{item.prompt}}</pre></details>
   <div class="actions"><button class="primary" :disabled="busy||quote.reservedCny>(budget?.remainingCny??0)||(budget?.blocked&&kind!=='crop')" @click="submit">{{kind==='crop'?'确认制作免费预览':'确认费用并生成第一条'}}</button><button @click="quote=null">取消</button></div>
  </section>
  <div class="preview-jobs"><article v-for="job in visibleJobs" :key="job.id"><h3>{{job.title}} <small>{{labels[job.status]||job.status}}</small></h3><p>{{job.kind==='video'?'视频':job.kind==='image'?'图片':'原画局部'}} · {{job.mediaLabel}} · {{job.message}}</p>
   <video v-if="job.videoUrl" :src="job.videoUrl" controls muted playsinline preload="metadata"/>
   <img v-else-if="job.imageUrl" :src="job.imageUrl" :alt="job.title+'分镜预览'"/>
   <div class="actions"><template v-if="job.status==='succeeded'&&job.review==='pending'"><button :disabled="busy" @click="review(job,true)">画面通过，继续下一条</button><button :disabled="busy" @click="review(job,false)">效果不可用，停止本组</button></template><span v-if="job.review==='accepted'">已检查通过</span><span v-if="job.review==='rejected'">未采用，可改用分镜图片</span><button v-if="['paused','download_failed'].includes(job.status)&&job.remoteId" :disabled="busy" @click="resume(job)">继续查询／下载原任务</button><a v-if="job.videoUrl||job.imageUrl" :href="job.videoUrl||job.imageUrl" :download="job.id+job.extension">下载</a></div>
  </article></div><details v-if="historicalJobs.length"><summary>此前任务记录 · {{historicalJobs.length}} 条</summary><p v-for="job in historicalJobs" :key="job.id">{{job.title}} · {{job.kind==='video'?'视频':job.kind==='image'?'图片':'原画局部'}} · {{labels[job.status]||job.status}} · {{job.message}}</p></details>
 </section>
</template>
<style scoped>
.preview-panel{border:1px solid var(--border,#d9e0dc);border-radius:12px;background:#f7faf8;padding:20px;margin-bottom:22px}.preview-panel p{font-size:12px;color:#63736b}.preview-panel label{margin:0;min-width:200px}.preview-panel pre{white-space:pre-wrap;font:inherit;font-size:12px}.preview-quote{background:white;border:1px solid #bfcfc4;padding:18px;margin-top:16px;border-radius:8px}.preview-quote details{margin:10px 0}.preview-jobs{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}.preview-jobs article{background:white;border:1px solid #dde5de;border-radius:8px;padding:14px;margin-top:16px}.preview-jobs video,.preview-jobs img{width:100%;max-height:240px;object-fit:contain;background:#e9e5d7}.preview-jobs h3{font-size:14px}.preview-jobs h3 small{font-weight:400;color:#6b7c70}.preview-jobs button{font-size:11px}
</style>
