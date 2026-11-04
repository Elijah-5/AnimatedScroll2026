<script setup lang="ts">
import {ref,watch,nextTick,onUnmounted} from 'vue'
import ChecksPage from './pages/ChecksPage.vue'
import AppIcon from './AppIcon.vue'
const props=defineProps<{open:boolean,target:string}>();const emit=defineEmits(['close'])
const dialog=ref<HTMLElement|null>(null)
let previousOverflow=''
watch(()=>props.open,async open=>{
 if(open){previousOverflow=document.body.style.overflow;document.body.style.overflow='hidden';await nextTick();dialog.value?.querySelector<HTMLButtonElement>('[data-close]')?.focus()}
 else document.body.style.overflow=previousOverflow
},{immediate:true})
onUnmounted(()=>{if(props.open)document.body.style.overflow=previousOverflow})
function keyboard(e:KeyboardEvent){
 if(e.key==='Escape'){e.preventDefault();e.stopPropagation();emit('close');return}
 if(e.key!=='Tab')return
 const nodes=Array.from(dialog.value?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]')||[]).filter(el=>el.getClientRects().length>0)
 const first=nodes[0],last=nodes.at(-1)
 if(!first){e.preventDefault();return}
 if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus()}
 else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}
}
</script>
<template><Teleport to="body"><div v-if="open" class="drawer-backdrop" @click.self="emit('close')"><section class="check-drawer" role="dialog" aria-modal="true" aria-labelledby="check-drawer-title" ref="dialog" @keydown="keyboard"><header class="drawer-header"><div><span class="eyebrow">PROJECT CHECKS</span><h2 id="check-drawer-title">制作检查</h2></div><button data-close class="icon-button" aria-label="关闭检查" @click="emit('close')"><AppIcon name="close"/></button></header><div class="drawer-body"><ChecksPage :highlighted="target"/></div></section></div></Teleport></template>
