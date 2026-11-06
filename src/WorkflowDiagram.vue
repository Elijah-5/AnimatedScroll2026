<script setup lang="ts">
import {computed,nextTick,onMounted,onUnmounted,ref,useId,watch} from 'vue'
interface FlowNode {id:string;label:string;description?:string;status?:string;column?:number;row?:number;action?:string}
interface FlowEdge {from:string;to:string;secondary?:boolean}
const props=withDefaults(defineProps<{label:string;nodes:FlowNode[];edges:FlowEdge[];columns?:number;interactive?:boolean}>(),{columns:6,interactive:false})
const emit=defineEmits<{navigate:[id:string];action:[id:string]}>()
const root=ref<HTMLElement>(),paths=ref<{key:string;d:string;secondary:boolean}[]>([]),marker='flow-'+useId().replaceAll(':','')
const layout=computed(()=>props.nodes.map((n,i)=>({...n,column:n.column??i,row:n.row??0})))
let observer:ResizeObserver|undefined,frame=0
function measure(){
 const el=root.value;if(!el)return
 const bounds=el.getBoundingClientRect(),boxes=new Map<string,DOMRect>()
 el.querySelectorAll<HTMLElement>('[data-flow-node]').forEach(n=>boxes.set(n.dataset.flowNode!,n.getBoundingClientRect()))
 paths.value=props.edges.flatMap((e,i)=>{
  const a=boxes.get(e.from),b=boxes.get(e.to);if(!a||!b)return []
  let x1:number,y1:number,x2:number,y2:number,d:string
  if(Math.abs(a.top-b.top)<10){
   const right=b.left>a.left;x1=(right?a.right:a.left)-bounds.left;y1=a.top-bounds.top+a.height/2;x2=(right?b.left:b.right)-bounds.left;y2=b.top-bounds.top+b.height/2;d=`M${x1},${y1} L${x2},${y2}`
  }else{
   const down=b.top>a.top;x1=a.left-bounds.left+a.width/2;y1=(down?a.bottom:a.top)-bounds.top;x2=b.left-bounds.left+b.width/2;y2=(down?b.top:b.bottom)-bounds.top;const mid=(y1+y2)/2;d=`M${x1},${y1} V${mid} H${x2} V${y2}`
  }
  return [{key:e.from+'-'+e.to,d,secondary:!!e.secondary}]
 })
}
function schedule(){cancelAnimationFrame(frame);frame=requestAnimationFrame(measure)}
watch(()=>[props.nodes,props.edges],()=>nextTick(schedule),{deep:true})
onMounted(()=>{observer=new ResizeObserver(schedule);if(root.value)observer.observe(root.value);schedule()})
onUnmounted(()=>{observer?.disconnect();cancelAnimationFrame(frame)})
</script>
<template><div ref="root" class="workflow-diagram" :style="{'--flow-columns':columns}" role="group" :aria-label="label">
 <svg class="flow-connectors" aria-hidden="true"><defs><marker :id="marker" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0L7 3.5L0 7" fill="none" stroke="currentColor"/></marker></defs><path v-for="p in paths" :key="p.key" :d="p.d" :class="{secondary:p.secondary}" :marker-end="`url(#${marker})`"/></svg>
 <article v-for="(node,index) in layout" :key="node.id" :data-flow-node="node.id" class="flow-node" :style="{gridColumn:node.column+1,gridRow:node.row+1}">
  <span class="flow-index">{{String(index+1).padStart(2,'0')}}</span><button v-if="interactive" class="flow-title" @click="emit('navigate',node.id)">{{node.label}}</button><h4 v-else>{{node.label}}</h4><small v-if="node.status" class="flow-status">{{node.status}}</small><p v-if="node.description">{{node.description}}</p><button v-if="node.action" class="flow-action" @click="emit('action',node.id)">{{node.action}} ↓</button>
 </article>
</div></template>
<style scoped>
.workflow-diagram{position:relative;display:grid;grid-template-columns:repeat(var(--flow-columns),minmax(0,1fr));gap:44px 23px;padding:6px 0;margin:18px 0;color:#78968a}.flow-connectors{position:absolute;inset:0;width:100%;height:100%;overflow:visible;pointer-events:none}.flow-connectors>path{fill:none;stroke:#91aa9d;stroke-width:1.5}.flow-connectors>path.secondary{stroke-dasharray:4 4;stroke:#acb7b5}.flow-node{position:relative;z-index:1;min-width:0;padding:16px 12px;border:1px solid #dce5dd;border-radius:11px;background:#fcfdf9;display:flex;flex-direction:column;align-items:flex-start;gap:8px}.flow-index{font-size:10px;color:#889a8c}.flow-node h4,.flow-title{margin:0;font-size:13px;line-height:1.65;color:#304e43;font-weight:600;overflow-wrap:anywhere}.flow-title{padding:0;background:none;border:0;text-align:left;cursor:pointer}.flow-title:hover{text-decoration:underline}.flow-node p{margin:0;font-size:11px;line-height:1.7;color:#819087}.flow-status{font-size:10px;line-height:1.7;color:#728b7b}.flow-action{font-size:10px;padding:0;color:#417c64;background:transparent;border:0;margin-top:auto;text-align:left}.flow-title:focus-visible,.flow-action:focus-visible{outline:2px solid #4b856b;outline-offset:4px;border-radius:2px}
</style>
