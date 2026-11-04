<script setup lang="ts">
import {computed,ref} from 'vue'
import {useStudio} from './studioContext'
import AppIcon from './AppIcon.vue'
const s=useStudio(),open=ref(false),working=ref(false),error=ref(''),message=ref(''),input=ref<HTMLInputElement|null>(null),tick=ref(0)
const previous=computed(()=>{tick.value;try{return JSON.parse(localStorage.getItem('animatedscroll-copy:'+s.p.value?.id)||'null')}catch{return null}})
const reminder=computed(()=>s.page.value==='overview'&&s.p.value&&(!previous.value||(s.p.value.version!==previous.value.version&&Date.now()-previous.value.time>86400000)))
const lastLabel=computed(()=>previous.value?new Date(previous.value.time).toLocaleString():'尚未手动下载副本')
async function download(){
 working.value=true;error.value='';message.value=''
 try{
  await s.saveAll();const pid=s.p.value.id,version=s.p.value.version
  const response=await fetch(`/api/projects/${pid}/creation-copy?version=${version}`)
  if(!response.ok){const v=await response.json();throw Error(v.detail?.message||v.detail||'副本下载失败')}
  const blob=await response.blob(),link=document.createElement('a'),url=URL.createObjectURL(blob)
  link.href=url;link.download=`创作副本-${pid}-${new Date().toISOString().slice(0,19).replaceAll(':','-')}.zip`;link.click();setTimeout(()=>URL.revokeObjectURL(url),10000)
  try{localStorage.setItem('animatedscroll-copy:'+pid,JSON.stringify({time:Date.now(),version}));tick.value++}catch{}
  message.value='副本已交给浏览器下载，请确认下载文件已保存。服务器不保留这份下载副本。'
 }catch(e:any){error.value=e.message}finally{working.value=false}
}
async function restore(event:Event){
 const field=event.target as HTMLInputElement,file=field.files?.[0];if(!file)return
 working.value=true;error.value='';message.value=''
 try{
  await s.saveAll();const body=new FormData();body.append('file',file)
  const response=await fetch('/api/creation-copies/restore',{method:'POST',body}),value=await response.json()
  if(!response.ok)throw Error(value.detail?.message||value.detail||'恢复未完成')
  await s.reloadProjects();await s.openProject(value.projectId);await s.navigate('overview')
  message.value=value.missingAssets.length?`已恢复到独立项目，${value.missingAssets.length} 项原有素材缺失，请在资料中补充。`:'已恢复到独立项目，现有项目和体验记录均保留。'
 }catch(e:any){error.value=e.message}finally{working.value=false;field.value=''}
}
</script>
<template>
 <button class="copy-trigger" :disabled="working" @click="open=true"><AppIcon name="save" :size="17"/><span>保存副本</span><i v-if="reminder" title="重要修改后可手动下载副本" aria-label="建议保存副本"/></button>
 <Teleport to="body"><div v-if="open" class="modal creation-copy-modal" role="dialog" aria-modal="true" aria-labelledby="copy-title" @keydown.esc="!working&&(open=false)"><article>
  <h2 id="copy-title">创作副本</h2>
  <p>修改会自动保存到本机。重要修改后，可手动下载 ZIP 副本另存。</p>
  <p class="muted">包含当前草稿、审核与依据、画作、文献及已完成的本地视频。不包含观众聊天或密钥；不会自动新增整库备份。</p>
  <small>{{lastLabel}}</small>
  <p v-if="error" class="extension-error" role="alert">{{error}}</p><p v-if="message" role="status">{{message}}</p>
  <div class="actions"><button class="primary" :disabled="working||!s.p.value" @click="download">{{working?'正在处理…':'下载当前创作副本'}}</button><button :disabled="working" @click="open=false">关闭</button></div>
  <details><summary>从副本恢复</summary><p class="muted">恢复为独立项目，不覆盖原项目或聊天。请选择此前下载的创作副本 ZIP。</p><input ref="input" type="file" accept=".zip" :disabled="working" aria-label="选择创作副本ZIP" @change="restore"/></details>
 </article></div></Teleport>
</template>
<style scoped>
.copy-trigger{display:inline-flex;align-items:center;gap:6px;position:relative;white-space:nowrap}.copy-trigger i{width:6px;height:6px;border-radius:50%;background:#b18b31}.creation-copy-modal article{max-width:580px}.creation-copy-modal p{line-height:1.7}.creation-copy-modal small{display:block;color:#75838b}.creation-copy-modal details{border-top:1px solid #e3e8eb;padding-top:16px;margin-top:22px}.creation-copy-modal summary{cursor:pointer}
@media(max-width:650px){.copy-trigger span{display:none}}
</style>
