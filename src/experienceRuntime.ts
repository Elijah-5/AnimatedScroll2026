/** Request identities survive network errors; only explicit retries start new work. */
export type MessageRequest = {requestId:string;characterId:string;text:string}
export function serviceError(status:number,detail:any){
 if(status===404&&detail==='Not Found')return '当前后端仍是旧版本，尚未加载此功能。请先保存编辑，再运行项目中的“重启服务器.command”，刷新网页后重试。'
 return typeof detail==='string'?detail:detail?.message||JSON.stringify(detail)||'请求未完成，请重试'
}
export function nextMessageRequest(previous:MessageRequest|null,characterId:string,text:string,retry:boolean,newId:()=>string):MessageRequest {
  if(!retry&&previous?.characterId===characterId&&previous.text===text)return previous
  return {requestId:newId(),characterId,text}
}
export function savedVideoReady(preview:any,text:string,saved:string){
  return !!preview?.customized&&!preview.stale&&text===saved&&!!text.trim()
}
export function restoredCreationPosition(raw:string|null){
 const fallback={page:'overview',focus:'',scrollY:0}
 try{
  const value=JSON.parse(raw||'null')
  if(!value||!['overview','library','characters','outline','clues','storyboards'].includes(value.page))return fallback
  return {page:value.page,focus:typeof value.focus==='string'?value.focus:'',scrollY:Number.isFinite(value.scrollY)&&value.scrollY>=0?value.scrollY:0}
 }catch{return fallback}
}
/** Applying a director suggestion is local; repeated clicks preserve edits. */
export function hintedDraft(current:string,question:string,alreadyApplied:boolean){
 return {text:alreadyApplied?current:question,backup:alreadyApplied?null:current}
}
export function replySegments(turn:any){
 if(turn.dialogueVersion!==2||!Array.isArray(turn.segments))return [{text:turn.answer,category:'legacy',evidence:[]}]
 return turn.segments.map((v:any)=>({...v,category:['supported','inference','fiction'].includes(v.category)?v.category:'fiction'}))
}
export type CompletionRequest={projectId:string;version:number;page:string;requestId:string}
/** Retries keep their identity, while a different input version starts fresh work. */
export function nextCompletionRequest(previous:CompletionRequest|undefined,projectId:string,version:number,page:string,newId:()=>string):CompletionRequest{
 if(previous?.projectId===projectId&&previous.version===version&&previous.page===page)return previous
 return {projectId,version,page,requestId:newId()}
}
