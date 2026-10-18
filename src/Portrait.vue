<script lang="ts">
const imageCache=new Map<string,Promise<HTMLImageElement>>()
function original(url:string){if(!imageCache.has(url))imageCache.set(url,new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=()=>{imageCache.delete(url);reject(Error('图片加载失败'))};im.src=url}));return imageCache.get(url)!}
</script>
<script setup lang="ts">
import {ref,watch,onMounted} from 'vue'
const props=defineProps<{url:string,box:Record<string,any>}>();const canvas=ref<HTMLCanvasElement|null>(null)
let revision=0
async function draw(){const n=++revision;try{const im=await original(props.url);if(n!==revision||!canvas.value)return;const b=props.box;const w=Math.max(1,b.w*im.naturalWidth),h=Math.max(1,b.h*im.naturalHeight);const scale=Math.min(200/w,240/h);canvas.value.width=Math.round(w*scale);canvas.value.height=Math.round(h*scale);canvas.value.getContext('2d')?.drawImage(im,b.x*im.naturalWidth,b.y*im.naturalHeight,w,h,0,0,canvas.value.width,canvas.value.height)}catch{}}
watch(()=>[props.url,props.box.x,props.box.y,props.box.w,props.box.h],draw);onMounted(draw)
</script>
<template><canvas ref="canvas" role="img" aria-label="人物裁切缩略图"/></template>
<style scoped>canvas{max-width:100%;max-height:160px;object-fit:contain;background:#eee9d9;border-radius:5px}</style>
