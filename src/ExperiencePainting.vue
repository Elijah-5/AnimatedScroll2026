<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref} from 'vue'
import type {PreparedAssets} from './experienceAssets'
import {paintingFrame,focusTransform,regionTransform,type Figure,type Box} from './experiencePresentation'
const props=defineProps<{image:string;people:Figure[];focused:string;cutouts:Record<string,any>;loading:boolean;assets?:PreparedAssets;region?:Box}>()
const emit=defineEmits<{choose:[person:Figure];reset:[]}>()
const stage=ref<HTMLElement>(),size=ref({w:800,h:480}),natural=ref({w:800,h:480}),hovered=ref('')
const alpha=computed(()=>new Map(Object.entries(props.assets?.alpha||{})))
const frame=computed(()=>paintingFrame(size.value.w,size.value.h,props.assets?.width||natural.value.w,props.assets?.height||natural.value.h))
const focusPerson=computed(()=>props.people.find(p=>p.annotationId===props.focused))
const transform=computed(()=>props.region?regionTransform(frame.value,size.value.w,size.value.h,props.region):focusTransform(frame.value,size.value.w,size.value.h,focusPerson.value?.box))
const planeStyle=computed(()=>({left:frame.value.x+'px',top:frame.value.y+'px',width:frame.value.w+'px',height:frame.value.h+'px','--edge-size':(1.2/transform.value.scale)+'px','--edge-glow':(2/transform.value.scale)+'px',transform:`translate(${transform.value.x}px,${transform.value.y}px) scale(${transform.value.scale})`}))
const highlighted=computed(()=>focusPerson.value||props.people.find(p=>p.annotationId===hovered.value))
function boxStyle(p:Figure){const b=p.box;return {left:b.x*100+'%',top:b.y*100+'%',width:b.w*100+'%',height:b.h*100+'%'}}
const labelStyle=computed(()=>{
 const p=highlighted.value;if(!p)return {}
 const f=frame.value,t=transform.value
 return {left:Math.max(88,Math.min(size.value.w-88,f.x+t.x+(p.box.x+p.box.w/2)*f.w*t.scale))+'px',top:Math.max(20,Math.min(size.value.h-64,f.y+t.y+p.box.y*f.h*t.scale-32))+'px'}
})
function nearest(e:PointerEvent|MouseEvent){
 if(!stage.value)return
 const r=stage.value.getBoundingClientRect(),f=frame.value,t=transform.value,x=(e.clientX-r.left-f.x-t.x)/(f.w*t.scale),y=(e.clientY-r.top-f.y-t.y)/(f.h*t.scale)
 const candidates=props.people.map(p=>{
  const b=p.box,m=alpha.value.get(p.annotationId),dx=Math.max(b.x-x,0,x-b.x-b.w)*f.w*t.scale,dy=Math.max(b.y-y,0,y-b.y-b.h)*f.h*t.scale
  let distance=Math.hypot(dx,dy)
  if(m){
   const px=(x-b.x)/b.w*m.w,py=(y-b.y)/b.h*m.h
   const rx=Math.max(1,Math.ceil(18/(b.w*f.w*t.scale)*m.w)),ry=Math.max(1,Math.ceil(18/(b.h*f.h*t.scale)*m.h))
   distance=Infinity
   for(let yy=Math.max(0,Math.floor(py-ry));yy<Math.min(m.h,py+ry+1);yy++)for(let xx=Math.max(0,Math.floor(px-rx));xx<Math.min(m.w,px+rx+1);xx++)if(m.data[(yy*m.w+xx)*4+3]>100)distance=Math.min(distance,Math.hypot((xx-px)/m.w*b.w*f.w*t.scale,(yy-py)/m.h*b.h*f.h*t.scale))
  }
  return {p,distance,area:b.w*b.h}
 }).filter(v=>v.distance<=18).sort((a,b)=>a.distance-b.distance||a.area-b.area)
 return candidates[0]?.p
}
function move(e:PointerEvent){hovered.value=nearest(e)?.annotationId||''}
function click(e:MouseEvent){const p=nearest(e);if(p)emit('choose',p);else{hovered.value='';emit('reset')}}
function reset(){hovered.value='';emit('reset')}
let observer:ResizeObserver
function escape(e:KeyboardEvent){if(e.key==='Escape'&&(props.focused||props.region))reset()}
onMounted(()=>{observer=new ResizeObserver(entries=>{const r=entries[0]!.contentRect;if(r.width>0&&r.height>0)size.value={w:r.width,h:r.height}});if(stage.value)observer.observe(stage.value);window.addEventListener('keydown',escape)})
onUnmounted(()=>{observer?.disconnect();window.removeEventListener('keydown',escape)})
</script>
<template>
 <div class="painting-viewer" :class="{'is-focused':!!focused}">
  <div ref="stage" class="painting-stage" :class="{'has-hover':!!hovered}" @pointermove="move" @pointerleave="hovered=''" @click="click" @keydown.esc="reset">
   <div class="painting-plane" :style="planeStyle">
    <img class="painting-original" :src="image" alt="已确认的原画，可选择画中人物" draggable="false" @load="natural={w:($event.target as HTMLImageElement).naturalWidth,h:($event.target as HTMLImageElement).naturalHeight}">
    <div class="painting-shade" :class="{visible:!!focused}"/>
    <div v-for="p in people" :key="p.annotationId" class="painting-figure" :class="{highlighted:highlighted?.annotationId===p.annotationId}" :style="boxStyle(p)">
     <img v-if="cutouts[p.annotationId]?.url" :src="cutouts[p.annotationId].url" alt="" draggable="false" >
    </div>
   </div>
   <button v-for="(p,index) in people" :key="p.annotationId" class="painting-accessible-person" @focus="hovered=p.annotationId" @blur="hovered=''" @click.stop="emit('choose',p)" :aria-label="'聚焦'+p.name+'，画中身影'+(index+1)"/>
   <div v-if="highlighted" class="painting-name" :style="labelStyle"><b>{{highlighted.name}}</b><small>{{highlighted.canChat?'点击与人物交谈':'人物知识尚未开放'}}</small></div>
   <button v-if="focused||region" class="painting-reset" @click.stop="reset" aria-label="还原画作全景">↙ 返回全景 <kbd>Esc</kbd></button>
   <div class="painting-media-slot" @click.stop @pointermove.stop><slot/></div>
  </div>
  <div class="painting-caption"><span>{{focused?'点击背景，返回画作全景':'移动到人物附近，点击进入对话'}}</span><small v-if="loading" role="status">正在本地分离人物轮廓…</small><small v-else-if="Object.values(cutouts).some((v:any)=>v.error)" role="status">部分轮廓未能分离，仍可通过人物卡片交谈</small></div>
 </div>
</template>
<style scoped>
.painting-viewer{border:1px solid #d8d0bd;border-radius:18px;overflow:hidden;background:#eee9dd;box-shadow:0 10px 30px #594a2510}
.painting-media-slot{position:absolute;inset:0;pointer-events:none;z-index:5;display:flex;align-items:center;justify-content:center}.painting-media-slot:empty{display:none}
.painting-stage{height:clamp(340px,35vw,560px);border-radius:0;position:relative;overflow:hidden;background:#ede7da;line-height:normal;cursor:default;isolation:isolate}
.painting-stage.has-hover{cursor:pointer}.is-focused .painting-stage{background:#282c27}
.painting-plane{position:absolute;transform-origin:0 0;transition:transform .7s cubic-bezier(.22,.7,.2,1);will-change:transform;pointer-events:none}
.painting-original{display:block;width:100%;height:100%;user-select:none}
.painting-shade{position:absolute;inset:0;background:#121c19;opacity:0;transition:opacity .55s;pointer-events:none}.painting-shade.visible{opacity:.65}
.painting-figure{position:absolute;pointer-events:none;opacity:0;transition:opacity .22s;filter:drop-shadow(0 0 var(--edge-size,1px) #fff3c2) drop-shadow(0 0 var(--edge-glow,2px) #dfb963)}
.painting-figure.highlighted{opacity:1;z-index:2}.painting-figure img{display:block;width:100%;height:100%;user-select:none}
.painting-outline-pending{position:absolute;inset:0;border:1px dashed #f3d99f;border-radius:30% 30% 12% 12%;background:#fff3bb0d}
.painting-name{position:absolute;z-index:3;transform:translateX(-50%);max-width:176px;box-sizing:border-box;padding:9px 16px;border:1px solid #e6d8b9;border-radius:10px;background:#fffdf2f5;color:#3c4739;box-shadow:0 3px 18px #251e1d20;pointer-events:none;text-align:center;line-height:1.4}
.painting-name b{display:block;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.painting-name small{font-size:10px;color:#817559;white-space:nowrap}
.painting-reset{position:absolute;z-index:4;right:16px;bottom:16px;background:#fffdf4ed;border:1px solid #d5c9ae;border-radius:30px;padding:9px 15px;color:#39493e;font-size:12px;cursor:pointer;line-height:1.3}.painting-reset kbd{font-size:9px;margin-left:8px;opacity:.6}
.painting-caption{display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px;padding:13px 17px;font-size:12px;color:#746f60;background:#fbf8ef;border-top:1px solid #ddd4c2}.painting-caption small{font-size:11px;color:#8c7852}
.painting-accessible-person{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);padding:0;border:0}.painting-accessible-person:focus-visible{clip-path:none;width:auto;height:auto;top:14px;left:14px;z-index:5;background:#fff8e7;padding:10px;border:2px solid #637863}.painting-accessible-person:focus-visible::after{content:attr(aria-label)}
@media(max-width:600px){.painting-stage{height:360px}.painting-caption{font-size:11px}.painting-name{padding:7px 11px}}
@media(prefers-reduced-motion:reduce){.painting-plane,.painting-shade,.painting-figure{transition:none}}
</style>
