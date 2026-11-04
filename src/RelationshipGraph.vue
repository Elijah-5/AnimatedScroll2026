<script setup lang="ts">
import {computed,ref,useId} from 'vue'
import {useStudio} from './studioContext'
import {relationshipGraph} from './structuredRuntime'
const props=defineProps<{people:any[],relations:any[],evidence:any[],publishedRelations:any[]}>(),s=useStudio(),includeBackground=ref(false),selected=ref(''),arrow='relation-'+useId().replaceAll(':','')
const people=computed(()=>{
 const result=props.people.map(p=>({...p}));for(const c of s.entries('character')){
  const known=result.find(p=>p.characterId===c.id)
  if(known)known.name=c.draft.name
  else result.push({id:c.id,characterId:c.id,name:c.draft.name,roleType:c.draft.roleType,annotationIds:[],scope:c.draft.depictionScope})
 }return result
})
const graph=computed(()=>relationshipGraph(people.value,props.relations.map(r=>({...r,state:props.publishedRelations.some(old=>JSON.stringify(old)===JSON.stringify(r))?'confirmed':'draft'})),s.entries('clue'),includeBackground.value))
const width=1000,height=computed(()=>graph.value.nodes.length>8?Math.max(420,Math.ceil(graph.value.nodes.length/5)*130+60):420)
const nodes=computed(()=>graph.value.nodes.map((n,i,all)=>({...n,x:all.length>8?100+(i%5)*200:500+350*Math.cos(-Math.PI/2+i*Math.PI*2/all.length),y:all.length>8?80+Math.floor(i/5)*130:210+135*Math.sin(-Math.PI/2+i*Math.PI*2/all.length)})))
const node=(id:string)=>nodes.value.find(n=>n.id===id)!
const edges=computed(()=>graph.value.edges.map(e=>{
 const a=node(e.fromId),b=node(e.toId),dx=b.x-a.x,dy=b.y-a.y,length=Math.hypot(dx,dy)||1
 const siblings=graph.value.edges.filter(v=>[v.fromId,v.toId].sort().join('|')===[e.fromId,e.toId].sort().join('|'))
 const bend=siblings.length>1?38+siblings.indexOf(e)*30:15,cx=(a.x+b.x)/2-dy/length*bend,cy=(a.y+b.y)/2+dx/length*bend
 function end(n:any){const vx=cx-n.x,vy=cy-n.y,t=Math.min(70/Math.max(.01,Math.abs(vx)),34/Math.max(.01,Math.abs(vy)));return {x:n.x+vx*t,y:n.y+vy*t}}
 const start=end(a),finish=end(b)
 return {...e,from:a,to:b,path:`M ${start.x} ${start.y} Q ${cx} ${cy} ${finish.x} ${finish.y}`,x:(start.x+2*cx+finish.x)/4,y:(start.y+2*cy+finish.y)/4,confirmed:e.origins.some((o:any)=>o.state==='confirmed')}
}))
const active=computed(()=>edges.value.find(e=>e.id===selected.value))
function scopeLabel(n:any){return n.scope==='background'?'画外资料人物':n.scope==='depicted'?'画中资料人物':'范围待核对'}
function open(n:any){if(n.characterId)s.navigate('characters','character:'+n.characterId)}
function label(text:string){const parts=Array.from(text);return parts.length>12?parts.slice(0,12).join('')+'…':text}
</script>
<template><section class="relationship-graph" aria-label="人物关系图"><div class="graph-heading"><div><h3>人物关系图</h3><p>沿用同一人物与关系。箭头从关系起点指向终点，点击连线查看依据，点击角色进入档案。</p></div><label class="extension-check"><input type="checkbox" v-model="includeBackground">显示其他资料人物</label></div>
<p class="graph-legend"><span>实线：已确认关系版本</span><span>虚线：当前草稿关系</span><span>{{graph.nodes.length}} 位人物 · {{graph.edges.length}} 条方向关系</span></p>
<div v-if="nodes.length" class="graph-canvas"><svg :viewBox="`0 0 ${width} ${height}`" role="group" aria-label="人物方向关系图"><defs><marker :id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#738773"/></marker></defs>
<g v-for="e in edges" :key="e.id" class="graph-edge" :class="{selected:active?.id===e.id}" role="button" tabindex="0" :aria-label="e.from.name+' → '+e.label+' → '+e.to.name" @click="selected=e.id" @keydown.enter.prevent="selected=e.id" @keydown.space.prevent="selected=e.id"><title>{{e.from.name}} → {{e.label}} → {{e.to.name}}</title><path class="edge-hit" :d="e.path"/><path :d="e.path" :stroke-dasharray="e.confirmed?undefined:'7 5'" :marker-end="`url(#${arrow})`"/><text :x="e.x" :y="e.y-7" text-anchor="middle">{{label(e.label)}}</text></g>
<g v-for="n in nodes" :key="n.id" class="graph-node" :class="{linked:!!n.characterId}" :role="n.characterId?'button':'group'" :tabindex="n.characterId?0:undefined" :aria-label="n.name+(n.characterId?'，打开人物档案':'，'+scopeLabel(n))" @click="open(n)" @keydown.enter.prevent="open(n)" @keydown.space.prevent="open(n)"><title>{{n.name}}</title><rect :x="n.x-65" :y="n.y-28" width="130" height="56" rx="14"/><text :x="n.x" :y="n.y-2" text-anchor="middle">{{label(n.name)}}</text><text class="node-type" :x="n.x" :y="n.y+15" text-anchor="middle">{{n.roleType==='group'?'群体 · '+(n.annotationIds?.length||0)+' 个实例':n.characterId?'创作角色':scopeLabel(n)}}</text></g>
</svg></div><p v-else class="muted">尚无人物关系。资料整理或新增关系后，将在这里显示。</p>
<p v-if="!graph.edges.length&&nodes.length" class="muted">人物已保留，尚无方向关系；可在下方补充关系，或在人物档案生成并核对关系线索。</p><p v-if="graph.hidden" class="muted">另有 {{graph.hidden}} 条涉及其他资料人物的关系，可勾选显示。</p><p v-if="graph.unresolved" class="muted">{{graph.unresolved}} 条关系的端点或名称需核对，未绘制为有效连线。</p>
<article v-if="active" class="graph-detail"><h4>{{active.from.name}} → {{active.label}} → {{active.to.name}}</h4><section v-for="(origin,i) in active.origins" :key="i"><small>{{origin.kind==='material'?'作品资料':'人物关系线索'}} · {{origin.state==='confirmed'?'已确认版本':'草稿待确认'}}</small><template v-if="origin.kind==='material'"><blockquote v-for="e in evidence.filter(e=>origin.referenceIds.includes(e.id))" :key="e.id">{{e.quote}}<small>来源 {{e.sourceTitle||e.sourceId}} · v{{e.sourceVersion}}</small></blockquote><p v-if="!origin.referenceIds.length" class="muted">未关联原文，请在下方关系编辑中核对。</p></template><template v-else><blockquote v-for="r in origin.references">{{r.quote}}<small>来源 {{r.sourceId}} · v{{r.sourceVersion}}</small></blockquote><button @click="s.navigate('clues','clue:'+origin.id)">编辑／确认这条关系线索</button></template></section></article>
</section></template>
<style scoped>
.relationship-graph{margin:20px 0 28px;padding:20px;border:1px solid #dddccb;border-radius:12px;background:#f9faf5}.graph-heading{display:flex;justify-content:space-between;gap:18px;align-items:start}.graph-heading h3{margin:0 0 6px}.graph-heading p,.graph-legend,.graph-detail p{font-size:12px;color:#7c806e}.graph-heading label{white-space:nowrap;font-size:11px}.graph-legend{display:flex;gap:18px;flex-wrap:wrap}.graph-canvas{overflow:auto;background:#fffef9;border-radius:9px}.graph-canvas svg{display:block;width:100%;min-width:650px;max-height:600px}.graph-edge{cursor:pointer;outline:none}.graph-edge path{fill:none;stroke:#84957e;stroke-width:1.8}.graph-edge .edge-hit{stroke:transparent;stroke-width:18}.graph-edge text{font-size:12px;fill:#65725f;paint-order:stroke;stroke:#fffef9;stroke-width:6;stroke-linejoin:round}.graph-edge.selected path:not(.edge-hit),.graph-edge:focus path:not(.edge-hit){stroke:#ad8748;stroke-width:3}.graph-node rect{fill:#f0f4e8;stroke:#b5c3ac;stroke-width:1.5}.graph-node text{font-size:13px;fill:#3b4e3c}.graph-node .node-type{font-size:10px;fill:#8a937e}.graph-node.linked{cursor:pointer}.graph-node.linked:hover rect,.graph-node:focus rect{stroke:#5b805e;stroke-width:2.5}.graph-detail{margin-top:14px;padding:16px;background:#fffef8;border-radius:9px}.graph-detail h4{margin-top:0}.graph-detail section+section{margin-top:14px;border-top:1px solid #e0e3d8;padding-top:12px}.graph-detail blockquote{font-size:12px;margin:10px 0;border-left:2px solid #bfccb5;padding:6px 12px;white-space:pre-wrap}.graph-detail small{display:block;color:#92947e;font-size:10px}@media(max-width:760px){.graph-heading{display:block}.relationship-graph{padding:14px}}
</style>
