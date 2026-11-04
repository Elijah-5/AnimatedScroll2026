<script setup lang="ts">
import {ref} from 'vue'
const props=defineProps<{image:string,modelValue:any}>();const emit=defineEmits(['update:modelValue']);const start=ref<any>(null)
function pos(e:PointerEvent){const r=(e.currentTarget as HTMLElement).getBoundingClientRect();return {x:Math.max(0,Math.min(1,(e.clientX-r.x)/r.width)),y:Math.max(0,Math.min(1,(e.clientY-r.y)/r.height))}}
function down(e:PointerEvent){start.value=pos(e);(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)}
function up(e:PointerEvent){if(!start.value)return;const p=pos(e),a=start.value;if(Math.abs(p.x-a.x)>.005&&Math.abs(p.y-a.y)>.005)emit('update:modelValue',{x:Math.min(a.x,p.x),y:Math.min(a.y,p.y),w:Math.abs(a.x-p.x),h:Math.abs(a.y-p.y)});start.value=null}
</script>
<template><div><small>在画作上拖动选择大致区域</small><div v-if="image" class="region-picker" @pointerdown="down" @pointerup="up"><img :src="image" draggable="false"><span v-if="modelValue" :style="{left:modelValue.x*100+'%',top:modelValue.y*100+'%',width:modelValue.w*100+'%',height:modelValue.h*100+'%'}"/></div><div v-else class="empty">请先上传画作</div><button v-if="modelValue" @click="emit('update:modelValue',null)">清除区域</button></div></template>
