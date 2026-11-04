/** Stable editable projection; historical bases remain on the server. */
export function editorProject(value:any){
 const entities=Object.fromEntries(Object.entries(value.workspace.entities).map(([k,r]:any)=>{const {history,basisWarnings,...rest}=r;return [k,rest]}))
 const {revisionArchive,historyLibrary,batchReceipts,...w}=value.workspace
 return {...value,workspace:{...w,entities}}
}
const same=(a:any,b:any)=>JSON.stringify(a)===JSON.stringify(b)
const plain=(value:any)=>JSON.parse(JSON.stringify(value??null))
export function saveChanges(base:any,current:any){
 const changes:any[]=[]
 function diff(a:any,b:any,path:string){
  if(same(a,b))return
  if(a&&b&&!Array.isArray(a)&&!Array.isArray(b)&&typeof a==='object'&&typeof b==='object'){
   for(const key of new Set([...Object.keys(a),...Object.keys(b)]))diff(a[key],b[key],path+'/'+key)
  }else if(Array.isArray(a)&&Array.isArray(b)&&[...a,...b].every(v=>v&&typeof v.id==='string')){
   const aa=new Map(a.map(v=>[v.id,v])),bb=new Map(b.map(v=>[v.id,v]))
   for(const id of new Set([...aa.keys(),...bb.keys()]))diff(aa.get(id),bb.get(id),path+'/@'+id)
  }else changes.push({path,before:plain(a),value:plain(b),delete:b===undefined})
 }
 for(const key of ['authoringDrafts','image','imageVersion','sources','annotations','observations','matches','documents','documentAnalysis','materialInputs','materialInputOrigins','targetArtwork','visualDetectionProposal','visualOverview'])diff(base?.[key],current?.[key],'/'+key)
 for(const [key,r] of Object.entries(current?.workspace.entities||{}) as any)diff(base?.workspace.entities[key]?.draft,r.draft,'/workspace/entities/'+key+'/draft')
 return changes
}
export function shouldScheduleSave(composing:boolean,changes:number){return !composing&&changes>0}
export function generationLabel(complete:boolean,hasAny:boolean){return complete?'重新生成':hasAny?'生成未完成内容':'首次生成'}
