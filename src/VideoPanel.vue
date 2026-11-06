<script setup lang="ts">
import {computed,onUnmounted,onActivated,onDeactivated,ref,watch} from 'vue'
import ReviewUnit from './ReviewUnit.vue'
import {useStudio} from './studioContext'
import {savedVideoReady} from './experienceRuntime'
const props=defineProps<{storyboardId:string}>(),s=useStudio()
const jobs=ref<any[]>([]),generation=ref<any>(null),budget=ref<any>(null),busy=ref(false),error=ref(''),forms=ref<Record<string,any>>({})
const storageKey='animatedscroll-video-drafts:'+s.p.value.id
try{forms.value=JSON.parse(sessionStorage.getItem(storageKey)||'{}')}catch{}
const form=computed(()=>forms.value[props.storyboardId]||(forms.value[props.storyboardId]={text:'',saved:'',preview:null,accepted:false}))
const currentJobs=computed(()=>jobs.value.filter(j=>j.storyboardId===props.storyboardId))
const ready=computed(()=>form.value.preview?.customized&&!form.value.preview?.stale&&form.value.text===form.value.saved)
watch(forms,()=>{try{sessionStorage.setItem(storageKey,JSON.stringify(forms.value))}catch{}},{deep:true})
const base=()=>`/projects/${s.p.value.id}`
async function run(fn:()=>Promise<void>){busy.value=true;error.value='';try{await fn()}catch(e:any){error.value=e.message||String(e)}finally{busy.value=false}}
async function poll(){if(document.hidden||s.page.value!=='storyboards')return;const pid=s.p.value.id,result=await s.api(base()+'/videos');if(s.p.value?.id===pid){const changed=JSON.stringify(jobs.value)!==JSON.stringify(result.jobs);jobs.value=result.jobs;generation.value=result.generation;budget.value=result.budget;if(changed)await s.updateChecklist()}}
async function prepare(){await run(async()=>{await s.saveAll();const sid=props.storyboardId;const preview=await s.api(base()+`/storyboards/${sid}/video-prompt`);forms.value[sid]={preview,text:preview.prompt,saved:preview.customized?preview.prompt:'',accepted:false}})}
async function savePrompt(){await run(async()=>{await s.saveAll();const sid=props.storyboardId,f=forms.value[sid];const p=await s.api(base()+`/storyboards/${sid}/video-prompt`,'PUT',{version:s.p.value.version,text:f.text,baseFingerprint:f.preview.baseFingerprint});await s.legacy(p);f.saved=f.text;f.accepted=false;f.preview=await s.api(base()+`/storyboards/${sid}/video-prompt`)})}
async function generate(){await run(async()=>{await s.saveAll();const sid=props.storyboardId;if(!form.value.accepted||!ready.value)return;await s.legacy(await s.api(base()+`/storyboards/${sid}/confirm-video`,'POST',{version:s.p.value.version}));await s.api(base()+'/videos','POST',{version:s.p.value.version,storyboardId:sid});form.value.accepted=false;await poll()})}
async function select(job:any){await run(async()=>{await s.saveAll();await s.legacy(await s.api(base()+`/storyboards/${props.storyboardId}/experience-video`,'POST',{version:s.p.value.version,jobId:job.id}));await poll()})}
async function refresh(job:any){await run(async()=>{await s.api(base()+`/videos/${job.id}/refresh`,'POST',{});await poll()})}
async function retry(job:any){await run(async()=>{await s.saveAll();const sid=props.storyboardId;if(!form.value.accepted||!ready.value)return;const keys=form.value.retryIds||={};keys[job.id]||=crypto.randomUUID();await s.legacy(await s.api(base()+`/storyboards/${sid}/confirm-video`,'POST',{version:s.p.value.version}));await s.api(base()+'/videos','POST',{version:s.p.value.version,storyboardId:sid,retryOf:job.id,requestId:keys[job.id]});form.value.accepted=false;await poll()})}
let timer:ReturnType<typeof setInterval>|undefined
function pause(){clearInterval(timer);timer=undefined}
onActivated(()=>{void run(poll);if(!timer)timer=setInterval(()=>{poll().catch(()=>{error.value='暂时无法查询视频进度，稍后重试'})},8000)})
onDeactivated(pause);onUnmounted(pause)
</script>
<template>
<section class="extension-panel video-panel" aria-label="独立分镜视频制作">
 <h3>分镜视频制作</h3><p class="muted">审核本镜的情节、人物参考与最终导演稿。原画画风和人物形象一起作为参考；已有视频仍可播放。</p>
 <p v-if="error" class="extension-error" role="alert">{{error}}</p>
 <fieldset :disabled="busy"><div class="actions"><button @click="prepare">查看可用分镜的最终提示词</button><span v-if="busy" role="status">正在处理…</span></div>
 <template v-if="form.preview"><p class="muted">{{form.preview.generation.ready?form.preview.model+' · '+form.preview.parameters.resolution+' · '+form.preview.parameters.duration+' 秒':'视频模型待接入，可先保存和审核导演稿'}}</p><p>{{form.preview.references.map((r:any)=>r.label+'：'+r.name).join('；')}}</p>
 <div class="prompt-audit" v-if="form.preview.audit"><h4>提示词检查 <a :href="form.preview.audit.guideUrl" target="_blank" rel="noopener noreferrer">官方写作指南 ↗</a></h4><div class="audit-checks"><span v-for="check in form.preview.audit.checks">{{check.passed?'✓':'○'}} {{check.label}}</span></div><p v-for="warning in form.preview.audit.warnings" class="audit-warning">{{warning}}</p><p v-for="issue in form.preview.audit.errors" class="extension-error">{{issue}}</p><small>{{form.text!==form.saved?'修改后保存导演稿即可更新检查。 ':''}}{{form.preview.audit.note}}</small></div>
 <p v-if="form.preview.directorChanged" class="audit-warning">分镜或相关资料有更新，已保存的导演稿仍保留；可对照当前编译稿选择更新。</p>
 <p v-if="form.preview.stale" class="extension-error">已确认输入已变化，请重新整理并保存提示词。</p>
 <label>实际发送给视频模型的完整文本<textarea rows="10" v-model="form.text" @input="form.accepted=false"/></label>
 <div class="actions"><button @click="form.text=form.preview.compiledPrompt;form.accepted=false">采用当前编译稿</button><button @click="savePrompt" :disabled="!form.text.trim()">保存最终提示词</button></div>
 <label class="extension-check"><input type="checkbox" v-model="form.accepted" :disabled="!ready">我已审核已保存的导演稿与人物参考，同意本次占用 ¥5 额度</label>
 <button class="primary" @click="generate" :disabled="!ready||!form.accepted||!generation?.ready||budget?.blocked||!budget?.remainingCount||budget?.remainingCny<5">{{generation?.ready?'生成此分镜视频 · ¥5 额度':'视频模型待接入'}}</button></template></fieldset>
 <div v-if="!currentJobs.length" class="muted">本分镜尚无视频任务。</div>
 <article v-for="job in currentJobs" :key="job.id" class="video-job"><div class="rail-heading"><b>{{job.title}}</b><ReviewUnit :unit-id="'video:'+job.id" label="确认此视频"/><span>{{job.status}}</span></div><p>{{job.message}}</p><p v-if="!job.matchesCurrentScript" class="muted">相关制作内容有更新，视频仍可播放</p>
 <video v-if="job.status==='succeeded'&&job.videoUrl" controls preload="metadata" :src="job.videoUrl"/>
 <div class="actions"><a v-if="job.videoUrl" :href="job.videoUrl" :download="job.id+'.mp4'">下载视频</a><button v-if="job.status==='succeeded'&&job.availableForExperience" :disabled="busy" @click="select(job)">{{job.selectedForExperience?'已用于欣赏作品':'选为体验视频'}}</button><button v-if="['paused','download_failed','pending','running'].includes(job.status)" :disabled="busy" @click="refresh(job)">继续查询／下载原任务</button><button v-if="job.status==='failed'&&(job.remoteId||job.submissionKnownRejected)&&job.matchesCurrentScript" :disabled="busy||!ready||!form.accepted||!generation?.ready||budget?.blocked||!budget?.remainingCount||budget?.remainingCny<5" @click="retry(job)">审核提示词后重试（调用视频服务）</button></div></article>
</section>
</template>

<style scoped>.prompt-audit{border:1px solid #dce5d5;border-radius:8px;padding:14px;margin:16px 0;background:#f9fbf5}.prompt-audit h4{font-size:12px;margin:0 0 10px}.prompt-audit h4 a{float:right;font-size:10px;font-weight:400;color:#809374}.audit-checks{display:flex;gap:12px;flex-wrap:wrap;font-size:11px;color:#728968}.prompt-audit small{font-size:10px;color:#94a087;line-height:1.8}.prompt-audit .audit-warning{font-size:11px;color:#a5814a;margin:9px 0}</style>
