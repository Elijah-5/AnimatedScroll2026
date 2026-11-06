<script setup lang="ts">
import {onMounted,onUnmounted,onActivated,onDeactivated,ref} from 'vue'
import {useStudio} from './studioContext'
import AppIcon from './AppIcon.vue'
const s=useStudio(),budget=ref<any>(null),error=ref(''),busy=ref(false),dialog=ref<HTMLDialogElement>(),password=ref(''),count=ref(20),request=ref<any>(null)
const base=()=>`/projects/${s.p.value.id}/video-budget`
async function load(){try{budget.value=await s.api(base())}catch(e:any){error.value=e.message}}
function open(){password.value='';error.value='';dialog.value?.showModal()}
async function grant(){busy.value=true;error.value='';try{
 if(!request.value||request.value.count!==count.value)request.value={count:count.value,id:crypto.randomUUID()}
 const result=await s.api(base()+'/grants','POST',{password:password.value,additionalCount:count.value,requestId:request.value.id})
 budget.value={...budget.value,...result};password.value='';request.value=null;dialog.value?.close()
}catch(e:any){error.value=e.message}finally{busy.value=false}}
let timer:ReturnType<typeof setInterval>|undefined
function start(){if(timer)return;void load();timer=setInterval(()=>{if(!document.hidden)void load()},6000)}
function pause(){clearInterval(timer);timer=undefined}
onMounted(start);onActivated(start);onDeactivated(pause)
onUnmounted(()=>{pause();password.value=''})
</script>
<template><section class="video-budget" aria-label="项目视频额度"><div class="budget-heading"><div><span class="eyebrow">项目视频制作</span><h2>分镜视频</h2></div><button class="researcher-entry" aria-label="实验员额度管理" title="实验员工具" @click="open">···</button></div>
 <template v-if="budget"><div class="budget-stats"><div><small>额度已用</small><strong>¥{{budget.usedCny.toFixed(2)}} <span>/ ¥{{budget.limitCny}}</span></strong></div><div><small>生成次数</small><strong>{{budget.usedCount}} <span>/ {{budget.limitCount}}</span></strong></div><div><small>进行中预留</small><strong>¥{{budget.reservedCny.toFixed(2)}} <span>· {{budget.reservedCount}} 次</span></strong></div><div><small>剩余额度</small><strong>¥{{budget.remainingCny.toFixed(2)}} <span>· {{budget.remainingCount}} 次</span></strong></div></div>
 <progress :value="budget.allocatedCny" :max="budget.limitCny" aria-label="视频额度已用及预留"/>
 <p>每次生成预留 ¥{{budget.slotCny}}，成功后计入已用额度；明确未提交或生成失败会释放，状态不明时继续预留。额度与供应商实际账单分开记录。</p>
 <p v-if="budget.blocked" class="budget-warning">有视频提交状态待核实，暂停本项目新增生成；可继续查询原任务。</p>
 <div class="model-state"><AppIcon name="ai" :size="17"/><div><b>{{budget.model.ready?budget.model.model:'视频模型待接入'}}</b><small>{{budget.model.ready?`${budget.model.resolution} · ${budget.model.duration} 秒`:'已保留 AIHubMix 接口，Wan 模型和价格暂未配置。可先准备、修改与审核分镜。'}}</small></div></div></template>
 <p v-if="error&&!dialog?.open" class="extension-error" role="alert">{{error}}</p>
 <dialog ref="dialog" class="budget-dialog" aria-labelledby="budget-dialog-title" @close="password=''"><form @submit.prevent="grant"><h3 id="budget-dialog-title">实验员增加额度</h3><p>仅调整当前项目的本地生成上限，不会为供应商账户充值。</p><label>实验员密码<input v-model="password" type="password" autocomplete="off" required maxlength="256"></label><label>增加生成次数<input v-model.number="count" type="number" min="1" max="200" step="1" required></label><p>增加 {{count}} 次 · ¥{{count*5}}</p><p v-if="error" class="extension-error" role="alert">{{error}}</p><div class="actions"><button class="primary" type="submit" :disabled="busy||!password||!Number.isInteger(count)||count<1||count>200">{{busy?'正在增加…':'确认增加额度'}}</button><button type="button" :disabled="busy" @click="dialog?.close()">取消</button></div></form></dialog>
</section></template>
<style scoped>.video-budget{padding:22px;border:1px solid #dce5d6;border-radius:12px;background:#fbfcf7;margin-bottom:22px}.budget-heading{display:flex;align-items:center;justify-content:space-between}.budget-heading h2{margin:5px 0 20px}.researcher-entry{border:0;background:transparent;color:#9aa38d;font-size:20px;padding:3px 8px}.researcher-entry:focus-visible{outline:2px solid #668970}.budget-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:20px}.budget-stats small{display:block;color:#8b977e;font-size:11px;margin-bottom:7px}.budget-stats strong{font-size:23px;font-weight:550;color:#48654b}.budget-stats strong span{font-size:12px;font-weight:400;color:#8a967c}.video-budget progress{display:block;width:100%;height:7px;margin:18px 0;accent-color:#7e9e77}.video-budget progress{appearance:none;border:0;border-radius:4px;overflow:hidden;background:#e5ecdf}.video-budget progress::-webkit-progress-bar{background:#e5ecdf}.video-budget progress::-webkit-progress-value{background:#7e9e77}.video-budget progress::-moz-progress-bar{background:#7e9e77}.video-budget p{font-size:11px;line-height:1.8;color:#88967c}.model-state{display:flex;align-items:center;gap:11px;border-top:1px solid #e6ecdf;padding-top:15px;margin-top:14px;color:#778d69}.model-state b{font-size:12px}.model-state small{display:block;font-size:11px;color:#8b967f;margin-top:5px}.budget-warning{color:#9e773d!important}.budget-dialog{width:420px;max-width:none;border:1px solid #d2deca;border-radius:12px;padding:28px;background:#fffef9;color:#506547}.budget-dialog::backdrop{background:#172c2844}.budget-dialog label{display:block;font-size:12px;margin:14px 0}.budget-dialog input{display:block;width:100%;margin-top:6px}.budget-dialog h3{margin-top:0}</style>
