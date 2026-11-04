<script setup lang="ts">
import {computed,onUnmounted,onActivated,onDeactivated,ref,watch} from 'vue'
import ReviewUnit from './ReviewUnit.vue'
import {useStudio} from './studioContext'
import {savedVideoReady} from './experienceRuntime'
const props=defineProps<{storyboardId:string}>(),s=useStudio()
const jobs=ref<any[]>([]),busy=ref(false),error=ref(''),forms=ref<Record<string,any>>({})
const storageKey='animatedscroll-video-drafts:'+s.p.value.id
try{forms.value=JSON.parse(sessionStorage.getItem(storageKey)||'{}')}catch{}
const form=computed(()=>forms.value[props.storyboardId]||(forms.value[props.storyboardId]={text:'',saved:'',preview:null,accepted:false}))
const currentJobs=computed(()=>jobs.value.filter(j=>j.storyboardId===props.storyboardId))
const ready=computed(()=>form.value.preview?.customized&&!form.value.preview?.stale&&form.value.text===form.value.saved)
watch(forms,()=>{try{sessionStorage.setItem(storageKey,JSON.stringify(forms.value))}catch{}},{deep:true})
const base=()=>`/projects/${s.p.value.id}`
async function run(fn:()=>Promise<void>){busy.value=true;error.value='';try{await fn()}catch(e:any){error.value=e.message||String(e)}finally{busy.value=false}}
async function poll(){if(document.hidden||s.page.value!=='storyboards')return;const pid=s.p.value.id,result=await s.api(base()+'/videos');if(s.p.value?.id===pid){const changed=JSON.stringify(jobs.value)!==JSON.stringify(result.jobs);jobs.value=result.jobs;if(changed)await s.updateChecklist()}}
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
 <h3>独立分镜视频</h3><p class="muted">使用可用分镜；旧结果仍可播放。原画与出场人物裁切作参考，首尾画面描述进入提示词。</p>
 <p v-if="error" class="extension-error" role="alert">{{error}}</p>
 <fieldset :disabled="busy"><div class="actions"><button @click="prepare">查看可用分镜的最终提示词</button><span v-if="busy" role="status">正在处理…</span></div>
 <template v-if="form.preview"><p class="muted">{{form.preview.model}} · 480P · 5 秒 · 有音频 · 无本地次数上限</p><p>{{form.preview.references.map((r:any)=>r.label+'：'+r.name).join('；')}}</p>
 <p v-if="form.preview.stale" class="extension-error">已确认输入已变化，请重新整理并保存提示词。</p>
 <label>实际发送给视频模型的完整文本<textarea rows="10" v-model="form.text" @input="form.accepted=false"/></label>
 <div class="actions"><button @click="form.text=form.preview.compiledPrompt;form.accepted=false">采用当前编译稿</button><button @click="savePrompt" :disabled="!form.text.trim()">保存最终提示词</button></div>
 <label class="extension-check"><input type="checkbox" v-model="form.accepted" :disabled="!ready">我已审核上方已保存的最终提示词与参考人物</label>
 <button class="primary" @click="generate" :disabled="!ready||!form.accepted">确认并生成本分镜视频（调用视频服务）</button></template></fieldset>
 <div v-if="!currentJobs.length" class="muted">本分镜尚无视频任务。</div>
 <article v-for="job in currentJobs" :key="job.id" class="video-job"><div class="rail-heading"><b>{{job.title}}</b><ReviewUnit :unit-id="'video:'+job.id" label="确认此视频"/><span>{{job.status}}</span></div><p>{{job.message}}</p><p v-if="!job.matchesCurrentScript" class="muted">相关制作内容有更新，视频仍可播放</p>
 <video v-if="job.status==='succeeded'&&job.videoUrl" controls preload="metadata" :src="job.videoUrl"/>
 <div class="actions"><a v-if="job.videoUrl" :href="job.videoUrl" :download="job.id+'.mp4'">下载视频</a><button v-if="job.status==='succeeded'&&job.availableForExperience" :disabled="busy" @click="select(job)">{{job.selectedForExperience?'已用于欣赏作品':'选为体验视频'}}</button><button v-if="['paused','download_failed','pending','running'].includes(job.status)" :disabled="busy" @click="refresh(job)">继续查询／下载原任务</button><button v-if="job.status==='failed'&&(job.remoteId||job.submissionKnownRejected)&&job.matchesCurrentScript" :disabled="busy||!ready||!form.accepted" @click="retry(job)">审核提示词后重试（调用视频服务）</button></div></article>
</section>
</template>
