<script setup lang="ts">
import {computed,nextTick,onActivated,onDeactivated,onMounted,onUnmounted,ref,watch} from 'vue'
import {useStudio} from './studioContext'
import AppIcon from './AppIcon.vue'
import {normalizedTarget,sameTarget,type SmartTarget} from './smartEditRuntime'
const props=defineProps<{target:SmartTarget|null;label:string;prepare?:()=>Promise<void>}>()
const emit=defineEmits<{updated:[];running:[value:boolean]}>(),s=useStudio()
const input=ref<HTMLTextAreaElement>(),instruction=ref(''),error=ref(''),job=ref<any>(null),sending=ref(false),undoing=ref(false),priorInstruction=ref(''),pendingPayload=ref<any>(null)
const running=computed(()=>sending.value||['queued','running'].includes(job.value?.status))
const draftPage=s.page.value,draftProject=s.p.value.id
const storageKey=()=>`smart-edit:${draftProject}:${draftPage}`
const jobKey=()=>`smart-edit-job:${draftProject}`
let timer:ReturnType<typeof setTimeout>|undefined,active=true,polling=false
watch(running,v=>emit('running',v))
function remember(){try{sessionStorage.setItem(storageKey(),JSON.stringify({instruction:instruction.value,pendingPayload:pendingPayload.value}));if(job.value)sessionStorage.setItem(jobKey(),JSON.stringify({job:job.value,priorInstruction:priorInstruction.value}))}catch{}}
watch([instruction,job,pendingPayload],remember,{deep:true})
async function poll(){
 if(!active||!job.value||polling)return
 polling=true;const pid=s.p.value.id,jid=job.value.id
 try{
  const result=await s.api(`/projects/${pid}/studio/feedback/${jid}`)
  if(!active||s.p.value.id!==pid||job.value?.id!==jid)return
  job.value=result
  if(['queued','running'].includes(result.status))timer=setTimeout(poll,1000)
  else if(result.status==='completed'){await s.syncLatest();emit('updated')}
 }catch(e:any){error.value=e.message;if(active)timer=setTimeout(poll,3000)}finally{polling=false}
}
async function send(resolution?:string,targetOverride?:SmartTarget,action?:{peopleAction?:string;groups?:any[];resolution?:string}){
 const rawTarget=targetOverride||props.target;if(!rawTarget){error.value='请先选择要修改的模块或条目';return}
 const target=normalizedTarget(rawTarget!)
 const text=resolution||action?'':instruction.value.trim();if(!text&&!resolution&&!action)return
 sending.value=true;error.value=''
 const pid=s.p.value.id
 try{
  await props.prepare?.();await s.saveAll()
  const full=job.value?.status==='needs_input'&&sameTarget(job.value.request?.target,target)?`${priorInstruction.value}\n补充说明：${text}`:text
  const signature=JSON.stringify([pid,target,full,resolution,action])
  if(pendingPayload.value?.signature!==signature)pendingPayload.value={signature,body:{version:s.p.value.version,requestId:crypto.randomUUID(),target,instruction:full,...(resolution?{resolution}:{}),...(action||{})}}
  remember()
  const result=await s.api(`/projects/${pid}/studio/feedback`,'POST',pendingPayload.value.body)
  pendingPayload.value=null
  if(s.p.value.id!==pid)return
  priorInstruction.value=full;if(!resolution&&!action)instruction.value='';job.value=result;remember();void poll()
 }catch(e:any){error.value=e.message;if([400,409,422].includes(e.status))pendingPayload.value=null;remember()}finally{sending.value=false}
}
async function undo(){
 undoing.value=true;error.value=''
 try{await s.saveAll();job.value=await s.api(`/projects/${s.p.value.id}/studio/feedback/${job.value.operationId}/undo`,'POST',{});await s.syncLatest();emit('updated')}
 catch(e:any){error.value=e.message}finally{undoing.value=false}
}
async function focus(){await nextTick();input.value?.focus()}
function restore(){try{const saved=JSON.parse(sessionStorage.getItem(storageKey())||'null'),last=JSON.parse(sessionStorage.getItem(jobKey())||'null');if(saved){instruction.value=saved.instruction||'';pendingPayload.value=saved.pendingPayload||null}if(last){job.value=last.job;priorInstruction.value=last.priorInstruction||'';if(['queued','running'].includes(job.value?.status))void poll()}}catch{}}
watch(()=>s.p.value.id,()=>{clearTimeout(timer);job.value=null;instruction.value='';pendingPayload.value=null;restore()})
onMounted(restore);onActivated(()=>{active=true;emit('running',running.value);if(['queued','running'].includes(job.value?.status))void poll()});onDeactivated(()=>{active=false;clearTimeout(timer);emit('running',false)});onUnmounted(()=>{active=false;clearTimeout(timer);emit('running',false)})
defineExpose({focus,send})
</script>
<template><section class="feedback-composer" aria-label="智能修改" :aria-busy="running">
 <div class="feedback-heading"><span><AppIcon name="ai" :size="15"/>智能修改</span><small>{{target?'正在修改：'+label:'先选择一个模块或条目'}}</small></div>
 <form @submit.prevent="send()"><textarea ref="input" v-model="instruction" aria-label="自然语言修改要求" rows="2" :disabled="running" :placeholder="target?'例如：合并唐太宗与太宗，他们是同一个人；或把这段简介写得更简洁':'点击模块旁的「智能修改」，或勾选多个条目'" @keydown.ctrl.enter.prevent="send()" @keydown.meta.enter.prevent="send()"/><button class="primary" :disabled="!target||!instruction.trim()||running||s.generating.value&&!running">{{running?'处理中…':'发送修改'}}</button></form>
 <p v-if="error" class="feedback-error" role="alert">{{error}}</p>
 <div v-if="job" class="feedback-result" role="status"><span>{{job.undone?'已撤销此次修改':job.question||job.progress}}<small v-if="job.affected?.length&&!job.undone"> · {{job.affected.length}} 项关联内容保留，按需更新</small></span><button v-if="job.status==='completed'&&!job.undone&&job.operationId" :disabled="undoing||running" @click="undo">{{undoing?'撤销中…':'撤销此次修改'}}</button></div>
 <small v-else class="feedback-hint">只修改所选内容，关联内容按需更新；可撤销此次修改。</small>
</section></template>
<style scoped>.feedback-composer{position:sticky;bottom:14px;z-index:12;background:#fcfefb;border:1px solid #b9cfbd;box-shadow:0 8px 32px #29473412;border-radius:13px;padding:16px 18px;margin-top:22px}.feedback-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:9px}.feedback-heading>span{display:flex;align-items:center;gap:7px;font-size:12px;font-weight:600;color:#3e6852}.feedback-heading small{font-size:11px;color:#68806f}.feedback-composer form{display:flex;align-items:flex-end;gap:12px}.feedback-composer textarea{flex:1;min-width:0;min-height:65px;font-size:12px;line-height:1.7;margin:0;resize:vertical;background:white}.feedback-composer form button{white-space:nowrap;font-size:12px}.feedback-hint{display:block;margin-top:8px;color:#8b998e;font-size:10px}.feedback-result{display:flex;justify-content:space-between;align-items:center;gap:14px;font-size:12px;color:#4d6e58;margin-top:10px}.feedback-result button{font-size:11px;white-space:nowrap}.feedback-error{color:#a94736;font-size:12px}</style>
