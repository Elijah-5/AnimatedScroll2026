/** Pure merge and task-scope helpers. No API calls. */
export const clone=<T>(v:T):T=>v===undefined?v:JSON.parse(JSON.stringify(v))
const equal=(a:any,b:any)=>JSON.stringify(a)===JSON.stringify(b)
export interface EditConflict{path:string;local:any;incoming:any;baseline:any}
const object=(v:any)=>v!==null&&typeof v==='object'&&!Array.isArray(v)
const keyed=(v:any)=>Array.isArray(v)&&v.every((r:any)=>object(r)&&typeof r.id==='string')
export function mergeProject(base:any,local:any,incoming:any){
 const conflicts:EditConflict[]=[]
 function merge(b:any,l:any,r:any,path:string):any{
  if(path==='/version'||path==='/workspace/jobs')return clone(r)
  if(equal(l,b))return clone(r)
  if(equal(r,b)||equal(l,r))return clone(l)
  if(object(b)&&object(l)&&object(r)){
   const result:any={}
   for(const k of new Set([...Object.keys(b),...Object.keys(l),...Object.keys(r)])){
    const value=merge(b[k],l[k],r[k],path+'/'+k)
    if(value!==undefined)result[k]=value
   }
   return result
  }
  if(keyed(b)&&keyed(l)&&keyed(r)){
   const bm=new Map(b.map((v:any)=>[v.id,v])),lm=new Map(l.map((v:any)=>[v.id,v])),rm=new Map(r.map((v:any)=>[v.id,v]))
   const ids=[...new Set([...r.map((v:any)=>v.id),...l.map((v:any)=>v.id),...b.map((v:any)=>v.id)])]
   return ids.map(id=>merge(bm.get(id),lm.get(id),rm.get(id),path+'/@'+id)).filter(v=>v!==undefined)
  }
  conflicts.push({path,local:clone(l),incoming:clone(r),baseline:clone(b)})
  return clone(l)
 }
 return {value:merge(base,local,incoming,''),conflicts}
}
export function valueAt(value:any,path:string):any{
 for(const token of path.split('/').filter(Boolean))value=Array.isArray(value)&&token.startsWith('@')?value.find((r:any)=>r.id===token.slice(1)):value?.[token]
 return value
}
export function setAt(value:any,path:string,next:any){
 const tokens=path.split('/').filter(Boolean),last=tokens.pop()!
 for(const token of tokens)value=Array.isArray(value)&&token.startsWith('@')?value.find((r:any)=>r.id===token.slice(1)):value[token]
 if(Array.isArray(value)&&last.startsWith('@')){const i=value.findIndex((r:any)=>r.id===last.slice(1));if(next===undefined&&i>=0)value.splice(i,1);else if(i>=0)value[i]=clone(next);else value.push(clone(next))}
 else if(next===undefined)delete value[last];else value[last]=clone(next)
}
export function pathLocked(writeSet:string[],path:string,intersects=false){
 return writeSet.some(p=>path===p||path.startsWith(p+'/')||(intersects&&p.startsWith(path+'/')))
}
export function localInputChanged(job:any,base:any,local:any){return !!base&&(job.readSet||[]).some((path:string)=>!equal(valueAt(base,path),valueAt(local,path)))}
export function elapsedLabel(time:string|undefined,now:number){const sec=Math.max(0,Math.floor((now-Date.parse(time||new Date(now).toISOString()))/1000));return `${Math.floor(sec/60)}:${String(sec%60).padStart(2,'0')}`}

/** Ignore late responses; unchanged polls never replace the editable project. */
export function pollUpdate(current:any,pid:string,response:any){
 if(!current||current.id!==pid||response.version<current.version||(response.changed&&response.project?.id!==pid))return null
 const project=response.changed&&response.project?.version>current.version?response.project:null
 const jobs=response.changed?response.project?.workspace.jobs:response.jobs
 return {project,jobs:jobs||[],dataChanged:!!project,jobsChanged:JSON.stringify(current.workspace.jobs||[])!==JSON.stringify(jobs||[])}
}
