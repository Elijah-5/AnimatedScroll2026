<script setup lang="ts">
import {computed,ref} from 'vue'
import {id,useStudio,states,state} from './studioContext'
import {clone} from './editRuntime'
const s=useStudio(),tab=ref('painting'),query=ref(''),editing=ref(''),error=ref(''),form=ref<any>({}),relationId=ref(''),editBase=ref<any>(null)
const mat=computed(()=>s.rec('material','main')),people=computed<any[]>(()=>s.entries('character'))
const sources=computed<any[]>(()=>(mat.value.draft.sources||[]).filter((v:any)=>(v.title+' '+v.text+' '+v.citation).includes(query.value)))
const events=computed<any[]>(()=>mat.value.draft.historicalEvents||[])
const nodes=computed(()=>people.value.map((r:any,i:number)=>({id:r.id,name:r.draft.name,x:250+170*Math.cos(i*Math.PI*2/Math.max(people.value.length,1)),y:170+115*Math.sin(i*Math.PI*2/Math.max(people.value.length,1))})))
const relations=computed<any[]>(()=>s.entries('clue').filter((r:any)=>r.draft.type==='relationship').flatMap((r:any)=>(r.draft.relations||[]).map((e:any)=>({...e,clueId:r.id,state:state(r)}))))
const edges=computed(()=>relations.value.map((r:any)=>({...r,from:nodes.value.find(n=>n.id===r.fromId),to:nodes.value.find(n=>n.id===r.toId)})).filter((r:any)=>r.from&&r.to))
const fields:Record<string,string>={name:'作品名称',artist:'作者',period:'绘画年代',storyPeriod:'故事时代',medium:'材质与技法',dimensions:'尺寸',collection:'收藏机构',accession:'馆藏编号',description:'作品说明'}
function start(kind:string,item?:any){editBase.value=clone(kind==='painting'?(mat.value.draft.paintingInfo||{}):kind==='event'?(item||null):null);editing.value=kind;error.value='';relationId.value='';form.value=kind==='painting'?clone(mat.value.draft.paintingInfo||{}):kind==='event'?clone(item||{id:id(),title:'',time:'',description:'',evidence:{sourceId:'',sourceVersion:1,quote:''}}):{fromId:'',toId:'',label:'',sourceId:'',sourceVersion:1,quote:''}}
async function save(){error.value='';try{
 await s.syncLatest()
 const current=editing.value==='painting'?(mat.value.draft.paintingInfo||{}):editing.value==='event'?events.value.find((e:any)=>e.id===form.value.id)||null:null
 if(editing.value!=='relation'&&JSON.stringify(current)!==JSON.stringify(editBase.value)&&JSON.stringify(current)!==JSON.stringify(form.value))throw Error('这条资料已在其他位置修改，当前表单已保留；请取消后基于最新内容重新编辑')
 if(editing.value==='painting')mat.value.draft.paintingInfo=clone(form.value)
 if(editing.value==='event'){if(!form.value.title?.trim())throw Error('请填写事件标题');const list=mat.value.draft.historicalEvents||=[];const i=list.findIndex((v:any)=>v.id===form.value.id);if(i<0)list.push(clone(form.value));else list[i]=clone(form.value)}
 if(editing.value==='relation'){
  const f=form.value,source=(mat.value.published?.sources||[]).find((v:any)=>v.id===f.sourceId)
  if(!f.fromId||!f.toId||f.fromId===f.toId||!f.label.trim()||!source||!f.quote.trim()||!source.text.includes(f.quote))throw Error('请选择两个不同人物、填写关系名称，并逐字引用已确认资料')
  f.sourceVersion=source.version
  const data={name:f.label,type:'relationship',parentId:'relationship',characterIds:[f.fromId,f.toId],plotIds:[],summary:f.label,relations:[clone(f)],units:[{id:id(),text:f.label,kind:'clue',category:'supported',speakerId:'',rationale:'',references:[{sourceId:f.sourceId,sourceVersion:f.sourceVersion,quote:f.quote}]}]}
  if(relationId.value)s.rec('clue',relationId.value).draft=data;else relationId.value=s.add('clue',data).id
 }
 await s.saveAll();editing.value=''
}catch(e:any){error.value=e.message||String(e)}}
function bindEvent(){const src=(mat.value.draft.sources||[]).find((v:any)=>v.id===form.value.evidence.sourceId);form.value.evidence.sourceVersion=src?.version||1}
</script>
<template>
<section class="extension-panel catalog-extension"><div class="rail-heading"><h3>结构化资料库</h3><span class="muted">资料版本：{{states[state(mat)]}}</span></div><nav class="extension-tabs" aria-label="资料库视图"><button v-for="t in [{id:'painting',name:'作品档案'},{id:'relations',name:'人物关系图'},{id:'events',name:'历史事件时间线'},{id:'sources',name:'来源检索'}]" :class="{selected:tab===t.id}" @click="tab=t.id">{{t.name}}</button></nav>
<p class="muted">展示当前草稿。修改沿用资料与线索的确认、发布和撤回规则；历史事件与创作剧情分别保存。</p>
<template v-if="tab==='painting'"><dl class="catalog-metadata"><template v-for="(label,key) in fields"><dt>{{label}}</dt><dd>{{mat.draft.paintingInfo?.[key]||'待补充'}}</dd></template></dl><button :disabled="!!editing||s.locked('material','main')" @click="start('painting')">编辑作品档案</button></template>
<template v-if="tab==='relations'"><svg v-if="nodes.length" class="catalog-graph" viewBox="0 0 500 340" role="img" aria-label="人物方向关系图"><defs><marker id="relation-arrow" viewBox="0 0 10 10" refX="26" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor"/></marker></defs><g v-for="edge in edges"><line :x1="edge.from.x" :y1="edge.from.y" :x2="edge.to.x" :y2="edge.to.y" stroke="currentColor" :stroke-dasharray="edge.state==='confirmed'?'':'5 4'" marker-end="url(#relation-arrow)"/><text :x="(edge.from.x+edge.to.x)/2" :y="(edge.from.y+edge.to.y)/2-8" text-anchor="middle">{{edge.label}}</text></g><g v-for="n in nodes" @click="s.navigate('characters','character:'+n.id)" class="catalog-node"><circle :cx="n.x" :cy="n.y" r="25"/><text :x="n.x" :y="n.y+5" text-anchor="middle">{{n.name}}</text></g></svg><p v-if="!relations.length" class="muted">尚无方向关系；现有关系线索继续保留，可到人物档案显式生成关系建议。</p><p v-for="r in relations">{{people.find((p:any)=>p.id===r.fromId)?.draft.name}} → {{r.label}} → {{people.find((p:any)=>p.id===r.toId)?.draft.name}} <small>{{states[r.state]}}</small> <button @click="s.navigate('clues','clue:'+r.clueId)">编辑／确认线索</button></p><button :disabled="!!editing" @click="start('relation')">新增有依据的方向关系</button></template>
<template v-if="tab==='events'"><p v-if="!events.length" class="muted">尚未录入历史事件；不从创作剧情自动推定史实或年份。</p><article v-for="event in events" class="catalog-event"><small>{{event.time||'时间未注明'}}</small><h4>{{event.title}}</h4><p>{{event.description}}</p><q v-if="event.evidence?.quote">{{event.evidence.quote}}</q><small v-else>未关联原文，请核对后再确认资料。</small><button :disabled="!!editing||s.locked('material','main')" @click="start('event',event)">编辑</button><button :disabled="s.locked('material','main')" @click="mat.draft.historicalEvents=events.filter((e:any)=>e.id!==event.id)">从草稿移除</button></article><button :disabled="!!editing||s.locked('material','main')" @click="start('event')">添加历史事件</button></template>
<template v-if="tab==='sources'"><label>搜索标题、出处与原文<input v-model="query" placeholder="输入关键词"/></label><details v-for="source in sources" :key="source.id"><summary>{{source.title}} · v{{source.version}}</summary><small>{{source.citation}}</small><p class="pre">{{source.text}}</p></details></template>
<fieldset v-if="editing" class="catalog-editor" :disabled="s.busy.value"><h4>编辑{{editing==='painting'?'作品档案':editing==='event'?'历史事件':'方向关系'}}</h4><p v-if="error" class="extension-error" role="alert">{{error}}</p>
<template v-if="editing==='painting'"><label v-for="(label,key) in fields">{{label}}<input v-model="form[key]"/></label></template>
<template v-if="editing==='event'"><label>事件标题<input v-model="form.title"/></label><label>时间说明<input v-model="form.time" placeholder="仅填写资料记载的时间"/></label><label>事件说明<textarea v-model="form.description"/></label><label>来源<select v-model="form.evidence.sourceId" @change="bindEvent"><option value="">未关联</option><option v-for="source in mat.draft.sources" :value="source.id">{{source.title}}</option></select></label><label>逐字引文<textarea v-model="form.evidence.quote"/></label></template>
<template v-if="editing==='relation'"><label>甲<select v-model="form.fromId"><option value="">选择人物</option><option v-for="p in people" :value="p.id">{{p.draft.name}}</option></select></label><label>甲是乙的什么关系<input v-model="form.label" placeholder="如：弟子"/></label><label>乙<select v-model="form.toId"><option value="">选择人物</option><option v-for="p in people" :value="p.id">{{p.draft.name}}</option></select></label><label>已确认资料<select v-model="form.sourceId"><option value="">选择来源</option><option v-for="source in mat.published?.sources||[]" :value="source.id">{{source.title}}</option></select></label><label>逐字引文<textarea v-model="form.quote"/></label></template>
<div class="actions"><button @click="save">保存为草稿</button><button @click="editing=''">取消</button></div></fieldset>
</section>
</template>
