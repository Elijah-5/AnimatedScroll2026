import {reactive,onMounted,onUnmounted,watch} from 'vue'
import {localExperiment} from './experimentLocal'
import {redactExperiment,experimentFieldAllowed} from './experimentRuntime'
const STORAGE='animatedscroll-experiment-active'
export function createExperimentTracker(options:{project:()=>string|undefined;page:()=>string;save:()=>Promise<void>}){
 const nativeFetch=window.fetch.bind(window)
 const state=reactive<any>({run:null,pending:0,issue:'',elapsedMs:0,panel:false,loading:false,stopping:false,stopElapsedMs:null})
 let clientId=sessionStorage.getItem('experiment-client-id')||crypto.randomUUID();sessionStorage.setItem('experiment-client-id',clientId)
 let sequence=0,offset=0,flushing=false,disposed=false,timer:ReturnType<typeof setInterval>,write=Promise.resolve(),lastElapsed=0,lastPage=options.page(),lastProject=options.project(),wasFocused=false,lastNavigation=''
 const pending=new Map<string,any>(),inputs=new Map<Element,any>(),previous=new WeakMap<Element,any>(),fieldTimers=new Map<Element,ReturnType<typeof setTimeout>>()
 const effectivePage=()=>state.overlayPage||(state.panel?'experiment':options.page())
 const recording=()=>!disposed&&state.run?.status==='running'&&!state.stopping
 const elapsed=()=>Math.max(0,Date.now()+offset-(state.run?.startedAt||Date.now()))
 function remember(){try{localStorage.setItem(STORAGE,JSON.stringify({run:state.run,stopping:state.stopping,stopElapsedMs:state.stopElapsedMs,stopRequestId:state.stopRequestId,offset}))}catch{state.issue='浏览器无法保存实验恢复信息，请保持此页打开'}}
 async function request(path:string,method='GET',body?:any){const response=await nativeFetch('/api'+path,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const value=await response.json();if(!response.ok)throw Error(typeof value.detail==='string'?value.detail:'实验记录暂未同步');return value}
 function enqueue(kind:string,data:any={},page=effectivePage(),projectId=options.project(),force=false){
  if(disposed||!state.run||!recording()&&!force)return
  const event={id:crypto.randomUUID(),kind,page,projectId:projectId||null,clientId,sequence:sequence++,elapsedMs:Math.round(elapsed()),data:redactExperiment(data)}
  const row={id:event.id,runId:state.run.id,event};pending.set(row.id,row);state.pending=pending.size
  write=write.then(()=>localExperiment('events','put',row)).catch(()=>{state.issue='实验记录暂时无法写入本地，请保持页面打开并检查浏览器存储空间'})
  return event
 }
 async function flush(){
  if(flushing||!state.run)return
  flushing=true
  try{
   await write
   while(pending.size){const rows=[...pending.values()].filter(r=>r.runId===state.run.id).slice(0,20);if(!rows.length)break
    const result=await request(`/experiments/${state.run.id}/events`,'POST',{events:rows.map(r=>r.event)})
    for(const id of result.acknowledged){pending.delete(id);await localExperiment('events','delete',undefined,id)}state.pending=pending.size
   }
   if(!pending.size)state.issue=''
  }catch(e:any){state.issue='记录保存在本地，等待同步：'+e.message;throw e}finally{flushing=false}
 }
 function dwell(){
  if(!recording())return
  const current=Math.round(elapsed())
  if(wasFocused){for(let from=lastElapsed;from<current;from+=30000)enqueue('dwell',{fromMs:from,toMs:Math.min(current,from+30000)},lastPage,lastProject)}
  lastElapsed=current;lastPage=effectivePage();lastProject=options.project();wasFocused=!document.hidden&&document.hasFocus()
 }
 function navigation(){if(!recording()||state.run?.projectId&&!options.project())return;dwell();const nav=effectivePage()+':'+(options.project()||'');if(nav===lastNavigation)return;lastNavigation=nav;enqueue('navigation',{entity:location.hash});lastPage=effectivePage();lastProject=options.project()}
 function label(el:Element){return el.getAttribute('aria-label')||el.getAttribute('title')||(el as HTMLInputElement).labels?.[0]?.textContent?.trim()||el.getAttribute('placeholder')||el.textContent?.trim().slice(0,160)||el.tagName}
 function description(el:Element){const entity=el.closest('[data-entity-key]')?.getAttribute('data-entity-key')||'';return {label:label(el),fieldId:el.id||el.getAttribute('name')||'',entity,type:(el as HTMLInputElement).type||el.getAttribute('role')||el.tagName.toLowerCase()}}
 function fieldValue(el:HTMLInputElement|HTMLSelectElement|HTMLTextAreaElement){if(el instanceof HTMLInputElement&&el.type==='file')return Array.from(el.files||[]).map(f=>({name:f.name,size:f.size,type:f.type}));if(el instanceof HTMLInputElement&&['checkbox','radio'].includes(el.type))return el.checked;return el.value}
 function commitField(el:Element){clearTimeout(fieldTimers.get(el));fieldTimers.delete(el);const entry=inputs.get(el);if(!entry)return;inputs.delete(el);if(JSON.stringify(entry.before)!==JSON.stringify(entry.value))enqueue('input_change',entry,entry.page,entry.projectId);previous.set(el,entry.value)}
 function flushFields(){for(const el of inputs.keys())commitField(el)}
 function focus(e:Event){const el=e.target;if(el instanceof HTMLInputElement||el instanceof HTMLSelectElement||el instanceof HTMLTextAreaElement){if(experimentFieldAllowed(el))previous.set(el,fieldValue(el))}}
 function input(e:Event){if(!recording()||(e as InputEvent).isComposing)return;const el=e.target;if(!(el instanceof HTMLInputElement||el instanceof HTMLSelectElement||el instanceof HTMLTextAreaElement)||!experimentFieldAllowed(el))return
  const existing=inputs.get(el);inputs.set(el,{...description(el),before:existing?.before??previous.get(el)??('defaultValue' in el?el.defaultValue:''),value:fieldValue(el),page:options.page(),projectId:options.project()||null})
  clearTimeout(fieldTimers.get(el));fieldTimers.set(el,setTimeout(()=>commitField(el),900));if(e.type==='change')commitField(el)
 }
 function click(e:MouseEvent){if(!recording()||!(e.target instanceof Element)||!experimentFieldAllowed(e.target))return;const el=e.target.closest('button,a,summary,[role="button"],input[type="checkbox"],input[type="radio"]');if(el&&experimentFieldAllowed(el)){flushFields();enqueue('click',{...description(el),href:el.getAttribute('href')||'',checked:el instanceof HTMLInputElement?el.checked:undefined})}}
 function visibility(){flushFields();dwell();void flush().catch(()=>{})}
 function media(e:Event){const el=e.target;if(recording()&&el instanceof HTMLMediaElement)enqueue('media_'+e.type,{storyboardId:el.dataset.storyboardId||'',time:el.currentTime})}
 async function start(name:string){
  state.loading=true;state.issue=''
  try{await options.save();let startBody=JSON.parse(localStorage.getItem('experiment-pending-start')||'null');if(!startBody){startBody={requestId:crypto.randomUUID(),clientId,name,projectId:options.project()||null,page:options.page()};localStorage.setItem('experiment-pending-start',JSON.stringify(startBody))}const run=await request('/experiments/start','POST',startBody);localStorage.removeItem('experiment-pending-start');state.run=run;offset=run.serverNow-Date.now();state.stopping=false;state.stopElapsedMs=null;state.stopRequestId=null;lastNavigation='';lastPage=effectivePage();lastProject=options.project();lastElapsed=0;wasFocused=!document.hidden&&document.hasFocus();remember();navigation();void flush().catch(()=>{})}finally{state.loading=false}
 }
 async function stop(){
  if(!state.run)return
  state.loading=true
  try{
   if(!state.stopping){flushFields();dwell();state.stopElapsedMs=Math.round(elapsed());state.stopRequestId=crypto.randomUUID();state.stopping=true;remember()
    try{await options.save()}catch(e:any){enqueue('end_unsaved_changes',{message:e.message},options.page(),options.project(),true)}
   }
   // Wait for a flush already in flight, then drain every locally queued event.
   while(flushing)await new Promise(resolve=>setTimeout(resolve,50))
   await flush();state.run=await request(`/experiments/${state.run.id}/end`,'POST',{requestId:state.stopRequestId,elapsedMs:state.stopElapsedMs});state.elapsedMs=state.run.durationMs;state.stopping=false;remember()
  }catch(e:any){state.issue='已停止采集，结束记录待同步：'+e.message;remember();throw e}finally{state.loading=false}
 }
 async function restore(){
  try{
   if(localStorage.getItem('experiment-pending-start')){await start('');return}const saved=JSON.parse(localStorage.getItem(STORAGE)||'null');if(!saved?.run)return
   state.run=saved.run;state.stopping=!!saved.stopping;state.stopElapsedMs=saved.stopElapsedMs;state.stopRequestId=saved.stopRequestId;offset=saved.offset||0
   for(const row of await localExperiment('events','all'))if(row.runId===state.run.id)pending.set(row.id,row)
   state.pending=pending.size;lastElapsed=Math.round(elapsed());wasFocused=!document.hidden&&document.hasFocus()
   const report=await request('/experiments/'+saved.run.id);if(disposed)return;state.run=report.run;offset=report.serverNow-Date.now();state.stopping=!!saved.stopping;state.stopElapsedMs=saved.stopElapsedMs;state.stopRequestId=saved.stopRequestId
   for(const row of await localExperiment('events','all'))if(row.runId===state.run.id)pending.set(row.id,row)
   state.pending=pending.size;lastElapsed=Math.round(elapsed());wasFocused=!document.hidden&&document.hasFocus();if(recording())navigation();void flush().catch(()=>{})
  }catch(e:any){state.issue='实验恢复信息保留在本地：'+e.message}
 }
 const wrappedFetch:typeof fetch=async (input,init)=>{
  const url=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url,location.href),method=(init?.method||(input instanceof Request?input.method:'GET')).toUpperCase()
  if(!recording()||url.origin!==location.origin||!url.pathname.startsWith('/api/')||url.pathname.startsWith('/api/experiment')||url.pathname.includes('/video-budget/grants')||['GET','HEAD','OPTIONS'].includes(method))return nativeFetch(input,init)
  const requestId=crypto.randomUUID(),headers=new Headers(init?.headers||(input instanceof Request?input.headers:undefined));headers.set('X-Experiment-Id',state.run.id);headers.set('X-Experiment-Client',clientId);headers.set('X-Experiment-Request',requestId);headers.set('X-Experiment-Page',effectivePage())
  let body:any={};if(typeof init?.body==='string'){try{body=JSON.parse(init.body)}catch{body={text:init.body}}}else if(init?.body instanceof FormData){init.body.forEach((value,key)=>{body[key]=value instanceof File?{name:value.name,size:value.size,type:value.type}:value})}
  enqueue(url.pathname.endsWith('/feedback')&&body.instruction?'agent_submit':'api_request',{requestId,path:url.pathname,method,body:redactExperiment(body)})
  try{const response=await nativeFetch(input,{...init,headers});enqueue('api_response',{requestId,path:url.pathname,status:response.status});return response}catch(e){enqueue('api_response',{requestId,path:url.pathname,status:0});throw e}
 }
 onMounted(()=>{window.fetch=wrappedFetch;void restore();document.addEventListener('click',click,true);document.addEventListener('focusin',focus,true);document.addEventListener('input',input,true);document.addEventListener('change',input,true);document.addEventListener('compositionend',input,true);document.addEventListener('visibilitychange',visibility);window.addEventListener('blur',visibility);window.addEventListener('focus',visibility);window.addEventListener('pagehide',visibility);for(const type of ['play','pause','ended'])document.addEventListener(type,media,true)
  let ticks=0;timer=setInterval(()=>{if(disposed)return;state.elapsedMs=state.run?.status==='ended'?state.run.durationMs:elapsed();if(++ticks%5===0){if(recording())dwell();if(state.run?.status==='running')void flush().catch(()=>{})}},1000)
 })
 watch([options.page,options.project,()=>state.panel,()=>state.overlayPage],()=>{flushFields();navigation()})
 onUnmounted(()=>{flushFields();dwell();disposed=true;void flush().catch(()=>{});clearInterval(timer);for(const t of fieldTimers.values())clearTimeout(t);if(window.fetch===wrappedFetch)window.fetch=nativeFetch;document.removeEventListener('click',click,true);document.removeEventListener('focusin',focus,true);for(const type of ['input','change','compositionend'])document.removeEventListener(type,input,true);document.removeEventListener('visibilitychange',visibility);window.removeEventListener('blur',visibility);window.removeEventListener('focus',visibility);window.removeEventListener('pagehide',visibility);for(const type of ['play','pause','ended'])document.removeEventListener(type,media,true)})
 return {state,record:enqueue,recording,elapsed,flush,start,stop,request,clientId,localRecords:()=>localExperiment('events','all')}
}
export type ExperimentTracker=ReturnType<typeof createExperimentTracker>
