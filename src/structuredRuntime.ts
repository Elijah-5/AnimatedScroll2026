/** Human edits retain the old lineage but never present it as proof of new text. */
export const libraryFields:Record<string,string>={name:'作品名称',artist:'作者',period:'绘画年代',storyPeriod:'故事时代',medium:'材质与技法',dimensions:'尺寸',collection:'收藏机构',accession:'馆藏编号',description:'作品说明',circulation:'作品流传',storyOneLiner:'画中故事'}
export function editLibraryField(data:any,key:string,value:string){
 const field=data.artwork[key]
 if(field.value!==value){field.previousReferenceIds=[...(field.referenceIds||[])];field.referenceIds=[]}
 field.value=value;field.origin='creator'
}
export function editLibraryRow(data:any,kind:string,id:string,key:string,value:any){
 const row=data[kind].find((v:any)=>v.id===id)
 if(['text','label','personId','fromId','toId','phase','time','aspect'].includes(key)&&row[key]!==value){row.previousReferenceIds=[...(row.referenceIds||[])];row.referenceIds=[];row.category='uncertain'}
 row[key]=value;row.origin='creator'
}
export function libraryPeople(people:any[],showAll:boolean,query:string){return people.filter(p=>(showAll||p.characterId)&&(p.name+' '+(p.contextRoles||[]).join(' ')).includes(query))}
export function resolveLibraryConflict(data:any,conflict:any,useCandidate:boolean){
 if(useCandidate){
  const [kind,rid,key]=conflict.field.split('.')
  const row=kind==='artwork'?data.artwork[rid]:data[kind]?.find((v:any)=>v.id===rid)
  if(row){row[kind==='artwork'?'value':key]=conflict.candidate;row.referenceIds=[...(conflict.referenceIds||[])];row.origin='creator';if(kind!=='artwork')row.category='uncertain'}
 }
 data.conflicts.find((v:any)=>v.id===conflict.id).resolution=useCandidate?'candidate':'current'
}

/** Read-only graph: keep identity, direction, status and each origin separate. */
export function relationshipGraph(people:any[],relations:any[],clues:any[],includeBackground=false){
 const ids=new Map(people.map(p=>[p.id,p])),aliases=new Map(people.filter(p=>p.characterId).map(p=>[p.characterId,p.id]))
 const edges=new Map<string,any>();let unresolved=0
 function add(row:any,origin:any){
  const fromId=aliases.get(row.fromId)||row.fromId,toId=aliases.get(row.toId)||row.toId,label=(row.label||'').trim()
  if(!label||!ids.has(fromId)||!ids.has(toId)||fromId===toId){unresolved++;return}
  const key=JSON.stringify([fromId,toId,label]);if(!edges.has(key))edges.set(key,{id:key,fromId,toId,label,origins:[]})
  edges.get(key).origins.push(origin)
 }
 for(const r of relations)add(r,{kind:'material',id:r.id,state:r.state||'draft',referenceIds:r.referenceIds||[]})
 for(const c of clues.filter(c=>c.state!=='deleted'))for(const r of c.draft?.relations||[])add(r,{kind:'clue',id:c.id,state:c.published?.relations?.some((old:any)=>JSON.stringify(old)===JSON.stringify(r))?'confirmed':'draft',references:r.quote?[r]:[]})
 const connected=new Set([...edges.values()].flatMap(e=>[e.fromId,e.toId]))
 const nodes=people.filter(p=>p.characterId||(includeBackground&&connected.has(p.id))),visible=new Set(nodes.map(p=>p.id))
 return {nodes,edges:[...edges.values()].filter(e=>visible.has(e.fromId)&&visible.has(e.toId)),unresolved,hidden:[...edges.values()].filter(e=>!visible.has(e.fromId)||!visible.has(e.toId)).length}
}
