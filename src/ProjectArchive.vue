<script setup lang="ts">
import {onMounted,ref} from 'vue'
import {useStudio} from './studioContext'
const s=useStudio(),items=ref<any[]>([]),open=ref(false),confirming=ref(false),error=ref(''),busy=ref(false)
const samples=ref<any[]>([]),sample=ref('bunian')
async function load(){items.value=await s.api('/projects?archived=true')}
async function archive(){busy.value=true;error.value='';try{await s.saveAll();await s.api(`/projects/${s.p.value.id}/archive`,'POST',{version:s.p.value.version});await s.reloadProjects();confirming.value=false;await load()}catch(e:any){error.value=e.message}finally{busy.value=false}}
async function restore(p:any){busy.value=true;error.value='';try{await s.api(`/projects/${p.id}/restore`,'POST',{version:p.version});await s.reloadProjects();await load()}catch(e:any){error.value=e.message}finally{busy.value=false}}
async function importSample(){busy.value=true;error.value='';try{await s.saveAll();const p=await s.api('/samples/artworks/'+sample.value,'POST',{});await s.reloadProjects();await s.openProject(p.id);await s.navigate('library')}catch(e:any){error.value=e.message}finally{busy.value=false}}
onMounted(async()=>{try{samples.value=await s.api('/samples/artworks')}catch(e:any){error.value=e.message}})
</script>
<template><section class="extension-panel"><h3>项目归档</h3><p class="muted">归档后从制作项目列表隐藏，保留资料、文件和历史，可随时恢复。</p><p v-if="error" class="extension-error">{{error}}</p><div class="actions"><button v-if="!confirming" :disabled="busy||!s.p.value" @click="confirming=true">归档当前项目</button><template v-else><span>确认归档「{{s.p.value?.title}}」？</span><button :disabled="busy" @click="archive">确认归档</button><button @click="confirming=false">取消</button></template><button @click="open=!open;open?load():null">{{open?'收起':'查看'}}已归档项目</button></div><template v-if="open"><p v-if="!items.length" class="muted">没有已归档项目。</p><div v-for="p in items" class="rail-heading"><span>{{p.title}}</span><button :disabled="busy" @click="restore(p)">恢复</button></div></template><h3>导入示例画作</h3><p class="muted">创建独立空白项目，只导入图片，人物身份与资料仍需整理确认。</p><div class="actions"><select v-model="sample"><option v-for="item in samples" :value="item.id">{{item.title}}</option></select><button :disabled="busy||!samples.length" @click="importSample">导入所选画作</button></div></section></template>
