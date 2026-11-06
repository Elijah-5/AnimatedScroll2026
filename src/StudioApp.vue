<script setup lang="ts">
import {ref,computed,onMounted,onUnmounted,provide,nextTick,shallowReactive,shallowRef} from 'vue'
import {id,states} from './studioContext'
import {restoredCreationPosition,serviceError,nextCompletionRequest,type CompletionRequest} from './experienceRuntime'
import {clone,mergeProject,valueAt,setAt,pathLocked,localInputChanged,elapsedLabel,pollUpdate,type EditConflict} from './editRuntime'
import {creationPages,routeNames,resolveRoute,pendingItems,runningItems,itemKey,shortReason,type CheckItem} from './navigation'
import AppIcon from './AppIcon.vue'
import CheckDrawer from './CheckDrawer.vue'
import OverviewPage from './pages/OverviewPage.vue'
import LibraryPage from './pages/LibraryPage.vue'
import CharactersPage from './pages/CharactersPage.vue'
import OutlinePage from './pages/OutlinePage.vue'
import CluesPage from './pages/CluesPage.vue'
import StoryboardsPage from './pages/StoryboardsPage.vue'
import ExperiencePage from './ExperiencePage.vue'
import BatchConfirm from './BatchConfirm.vue'
import GenerationButton from './GenerationButton.vue'
import FeedbackComposer from './FeedbackComposer.vue'
import {normalizedTarget,type SmartTarget} from './smartEditRuntime'
import {editorProject,saveChanges,shouldScheduleSave} from './reviewRuntime'
import {pendingEdits} from './pendingEdits'
import StartupScreen from './StartupScreen.vue'
import CreationCopy from './CreationCopy.vue'
import './extensions.css'
import {createExperimentTracker} from './experimentTracker'
import ExperimentPanel from './ExperimentPanel.vue'
import ScreenshotFeedback from './ScreenshotFeedback.vue'
const initial=resolveRoute(location.hash)
const booting=ref(true),bootError=ref(''),bootPhase=ref('正在读取项目列表…')
const baselineProject=shallowRef<any>(null),conflicts=ref<EditConflict[]>([]),showConflicts=ref(false),clock=ref(Date.now()),nameDialog=ref<''|'create'|'rename'>(''),nameInput=ref('')
const p=ref<any>(null),projects=ref<any[]>([]),page=ref(initial.page),busy=ref(false),libraryBusy=ref(false)
const generationSubmitting=ref(false)
const experiments=createExperimentTracker({project:()=>p.value?.id,page:()=>page.value,save:()=>saveAll()})
const error=ref(''),notice=ref(''),risk=ref<any>(null),focus=ref(''),baseline=ref<Record<string,string>>({}),libraryBaseline=ref('')
const checklist=ref<any>({ready:false,items:[]}),checksOpen=ref(false),checkTarget=ref(''),mobileNav=ref(false)
const returnTo=ref({page:'overview',focus:'',scrollY:0})
let returnFocus:HTMLElement|null=null
const experience=computed(()=>page.value==='experience')
const records=computed<any[]>(()=>p.value?Object.values(p.value.workspace.entities).filter((r:any)=>r.state!=='deleted'):[])
const activeJob=computed(()=>p.value?.workspace.jobs?.find((j:any)=>['queued','running'].includes(j.state)))
const generating=computed(()=>generationSubmitting.value||libraryBusy.value||!!activeJob.value)
const inputChanged=computed(()=>activeJob.value&&(activeJob.value.inputsChanged||localInputChanged(activeJob.value,baselineProject.value,p.value)))
function rootLocked(path:string,intersects=false){return pathLocked(activeJob.value?.writeSet||[],path,intersects)}
function locked(kind:string,rid:string,field=''){return rootLocked('/workspace/entities/'+kind+':'+rid+'/draft'+(field?'/'+field:''))}
function entityBusy(kind:string,rid:string){return rootLocked('/workspace/entities/'+kind+':'+rid,true)}
function resolveConflict(c:EditConflict,useRemote=false){if(useRemote)setAt(p.value,c.path,c.incoming);conflicts.value=conflicts.value.filter(v=>v.path!==c.path);if(!conflicts.value.length){showConflicts.value=false;queuedSave=null;scheduleAutosave()}}
const pending=computed(()=>checklist.value.pages?checklist.value.pages.filter((v:any)=>!v.complete).map((v:any)=>({id:v.id,page:v.id,name:v.name,state:'missing'})):pendingItems(checklist.value.items)),running=computed(()=>runningItems(checklist.value.items))
const nextItem=computed(()=>pending.value[0])
const nextAction=computed(()=>checklist.value.pages?.find((v:any)=>v.id===page.value)?.nextAction||checklist.value.nextAction)
const currentPage=computed(()=>creationPages.find(item=>item.id===page.value)||creationPages[0]!)
const pageComponents:Record<string,any>={library:LibraryPage,characters:CharactersPage,outline:OutlinePage,clues:CluesPage,storyboards:StoryboardsPage}
const draftSavers=shallowReactive(new Map<string,{save:()=>Promise<void>,dirty:()=>boolean}>())
function registerDraftSaver(key:string,save:()=>Promise<void>,dirty:()=>boolean){draftSavers.set(key,{save,dirty});return ()=>draftSavers.delete(key)}
const localChanges=computed(()=>p.value&&(changed().length>0||libraryData(p.value)!==libraryBaseline.value||[...draftSavers.values()].some(v=>v.dirty())))
function entries(kind:string){return records.value.filter(r=>r.kind===kind)}
function castEntries(){const allowed=p.value?.peoplePolicy?.eligibleCharacterIds;return entries('character').filter(r=>r.draft.inclusionDecision!=='exclude'&&(allowed?allowed.includes(r.id)||r.draft.namingOrigin==='creator':r.draft.depictionScope!=='background'))}
const smartComposer=ref<InstanceType<typeof FeedbackComposer>>(),smartScopes=ref<Record<string,any>>({})
const smartScope=computed(()=>smartScopes.value[(p.value?.id||'')+':'+page.value]||null)
async function openSmartEdit(target:SmartTarget,label:string,prepare?:()=>Promise<void>,focusPanel=true){smartScopes.value[p.value.id+':'+page.value]={target:normalizedTarget(target),label,prepare};await nextTick();if(focusPanel)void smartComposer.value?.focus()}
async function runSmartAction(target:SmartTarget,action:any,prepare?:()=>Promise<void>){if(prepare)await prepare();smartScopes.value[p.value.id+':'+page.value]={target:normalizedTarget(target),label:'资料批量处理 · '+target.itemIds.length+' 项',prepare};await nextTick();await smartComposer.value?.send(undefined,normalizedTarget(target),action)}

function rec(kind:string,key:string){return p.value?.workspace.entities[kind+':'+key]}
function title(r:any){return r?.draft?.name||r?.draft?.title||r?.id||''}
function libraryData(value:any){return JSON.stringify(['authoringDrafts','image','imageVersion','materialInputs','sources','annotations','observations','matches','visualDetectionProposal','documents','documentAnalysis','materialInputOrigins','targetArtwork'].map(k=>value[k]))}
function accepted(value:any,ack?:any){
 value=editorProject(value)
 if(!p.value||p.value.id!==value.id||!baselineProject.value){p.value=clone(value);conflicts.value=[]}
 else{
  const before=p.value,previousJob=activeJob.value,hasLocalInputs=previousJob&&localInputChanged(previousJob,baselineProject.value,before)
  const merged=mergeProject(ack||baselineProject.value,before,value)
  if(!ack&&hasLocalInputs){
   for(const path of previousJob.writeSet||[]){const local=valueAt(before,path),incoming=valueAt(value,path);if(JSON.stringify(local)!==JSON.stringify(incoming)){setAt(merged.value,path,local);merged.conflicts.push({path,local:clone(local),incoming:clone(incoming),baseline:clone(valueAt(baselineProject.value,path))})}}
  }
  p.value=merged.value
  const fresh=merged.conflicts
  conflicts.value=[...conflicts.value.filter(c=>JSON.stringify(valueAt(p.value,c.path))!==JSON.stringify(valueAt(value,c.path))&&!fresh.some(v=>v.path===c.path)),...fresh]
 }
 baselineProject.value=clone(value);libraryBaseline.value=libraryData(value)
 baseline.value=Object.fromEntries(Object.entries(value.workspace.entities).map(([k,r]:any)=>[k,JSON.stringify(r.draft)]))
 projects.value=projects.value.map(item=>item.id===value.id?{...item,title:value.title,version:value.version}:item)
}
let syncRequest:any=null
function syncLatest():Promise<any>{
 if(!p.value)return Promise.resolve(null)
 const pid=p.value.id,version=p.value.version
 if(syncRequest?.pid===pid&&syncRequest.version===version)return syncRequest.promise
 const request:any={pid,version}
 request.promise=(async()=>{try{
  let result
  try{result=await api(`/projects/${pid}/studio/poll?version=${version}&compact=true`)}catch(e:any){
   if(e.status!==404)throw e
   const project=await api(`/projects/${pid}/studio/editor`);result={changed:true,version:project.version,project}
  }
  const update=pollUpdate(p.value,pid,result)
  if(update?.dataChanged)accepted(update.project)
  else if(update?.jobsChanged)p.value.workspace.jobs=update.jobs
  return update
 }finally{if(syncRequest===request)syncRequest=null}})()
 syncRequest=request;return request.promise
}

async function api(path:string,method='GET',body?:any){
 const response=await fetch('/api'+path,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined})
 const value=await response.json()
 if(!response.ok){const e:any=Error(serviceError(response.status,value.detail));e.detail=value.detail;e.status=response.status;throw e}
 return value
}
async function run(fn:()=>Promise<void>){busy.value=true;error.value='';notice.value='';try{await fn();return true}catch(e:any){error.value=e.message||String(e);return false}finally{busy.value=false}}
function changed(){return records.value.filter(r=>baseline.value[r.kind+':'+r.id]!==JSON.stringify(r.draft))}
const autoStatus=ref('已保存'),reviewing=ref('')
let saveFlight:Promise<void>|null=null,saveTimer:any,localTimer:any,composing=false,queuedSave:any=null
function unit(uid:string){return checklist.value.units?.[uid]}
async function storeLocal(){
 if(!p.value)return
 const changes=saveChanges(baselineProject.value,p.value)
 if(changes.length)await pendingEdits(p.value.id,{version:p.value.version,requestId:crypto.randomUUID(),changes,inFlight:queuedSave?.pid===p.value.id?{body:queuedSave.body,snapshot:queuedSave.snapshot}:undefined})
}
function scheduleAutosave(){
 if(!p.value||!shouldScheduleSave(composing,1))return
 autoStatus.value='待保存';clearTimeout(saveTimer);clearTimeout(localTimer)
 localTimer=setTimeout(()=>void storeLocal().catch(()=>{}),120)
 saveTimer=setTimeout(()=>void saveAll().catch(()=>{}),800)
}
function compositionStart(){composing=true;clearTimeout(saveTimer)}
function compositionEnd(){composing=false;scheduleAutosave()}
function blurSave(){if(!composing&&localChanges.value)void saveAll().catch(()=>{})}
async function restoreEdits(){
 if(!p.value)return
 const saved=await pendingEdits(p.value.id).catch(()=>null);if(!saved)return
 for(const edit of saved.changes){
  const current=valueAt(p.value,edit.path)
  if(JSON.stringify(current??null)===JSON.stringify(edit.before)||JSON.stringify(current??null)===JSON.stringify(edit.value))setAt(p.value,edit.path,edit.delete?undefined:edit.value)
  else conflicts.value.push({path:edit.path,local:edit.value,incoming:current,baseline:edit.before})
 }
 queuedSave=saved.inFlight?{pid:p.value.id,...saved.inFlight}:{pid:p.value.id,body:{version:saved.version,requestId:saved.requestId,changes:saved.changes},snapshot:clone(p.value)}
 if(conflicts.value.length){autoStatus.value='有保存冲突';return}
 scheduleAutosave()
}
async function saveAll():Promise<void>{
 if(!p.value||composing)return
 if(saveFlight){await saveFlight;if(localChanges.value)return saveAll();return}
 if(conflicts.value.length){showConflicts.value=true;throw Error('请处理同一字段的并行修改，输入已保留')}
 const changes=saveChanges(baselineProject.value,p.value)
 if(!changes.length&&!queuedSave){autoStatus.value='已保存';return}
 const pid=p.value.id,submitted=clone(p.value)
 const request=queuedSave?.pid===pid?queuedSave:{pid,body:{version:p.value.version,requestId:crypto.randomUUID(),changes},snapshot:submitted}
 clearTimeout(localTimer);queuedSave=request;autoStatus.value='保存中…'
 saveFlight=(async()=>{try{
  await pendingEdits(pid,request.body)
  const value=await api(`/projects/${pid}/studio/units/workspace`,'PATCH',request.body)
  if(p.value?.id===pid)accepted(value,request.snapshot)
  queuedSave=null;clearTimeout(localTimer);await pendingEdits(pid,undefined,true);await storeLocal();autoStatus.value=saveChanges(baselineProject.value,p.value).length?'待保存':'已保存'
 }catch(e:any){autoStatus.value='保存失败，输入已保留';if(e.status===409){queuedSave=null;await syncLatest();showConflicts.value=conflicts.value.length>0}else if(e.status===400||e.status===422){queuedSave=null;await storeLocal();error.value=e.message}throw e}finally{saveFlight=null}})()
 await saveFlight
 if(p.value?.id===pid){await updateChecklist();if(saveChanges(baselineProject.value,p.value).length)scheduleAutosave()}
}
async function confirmUnit(uid:string){reviewing.value=uid;error.value='';try{await saveAll();await updateChecklist();const u=unit(uid);if(!u)throw Error('内容不存在');accepted(await api(`/projects/${p.value.id}/studio/units/${encodeURIComponent(uid)}/confirm`,'POST',{requestId:crypto.randomUUID(),contentHash:u.contentHash,dependencyHash:u.dependencyHash}));await updateChecklist()}catch(e:any){error.value=e.message}finally{reviewing.value=''}}
async function generateStep(targetPage:string,targets:string[]=[],regenerate=false,task='',clueScope='narrative'){
 if(generating.value)return
 generationSubmitting.value=true;error.value=''
 try{await saveAll();const job=await api(`/projects/${p.value.id}/studio/generation-batches`,'POST',{version:p.value.version,requestId:crypto.randomUUID(),page:targetPage,targets,mode:regenerate?'regenerate':'initial',task,clueScope});p.value.workspace.jobs=[job,...p.value.workspace.jobs.filter((j:any)=>j.id!==job.id)];notice.value='任务已排队，可以继续浏览和编辑其他内容'}catch(e:any){error.value=e.message}finally{generationSubmitting.value=false}
}

async function applyRecord(_record:any){await saveAll();accepted(await api(`/projects/${p.value.id}/studio/units/workspace`,'PATCH',{version:p.value.version,requestId:crypto.randomUUID(),changes:[]}));await updateChecklist()}
async function applyAll(){await saveAll()}
async function refresh(){if(!p.value)return;accepted(await api(`/projects/${p.value.id}/studio/editor`));await updateChecklist()}
async function updateChecklist(){if(p.value)checklist.value={items:[],...await api(`/projects/${p.value.id}/studio/units`)}}
async function changeProject(e:Event){const select=e.target as HTMLSelectElement;const pid=select.value;const ok=await run(async()=>{await saveAll();accepted(await api('/projects/'+pid+'/studio/editor'));localStorage.setItem('animatedscroll-project',pid);focus.value='';await restoreEdits();await updateChecklist()});if(!ok)select.value=p.value?.id||''}
function writeRoute(value:string,replace=false){if(replace)history.replaceState(null,'','#/'+value);else if(location.hash!=='#/'+value)location.hash='/'+value}
let navigationSequence=0
async function navigate(to:string,target=''){
 if(to==='checks'){openChecks(target);return}
 const destination=resolveRoute('#/'+to).page
 if(destination===page.value&&!target)return
 const previous=page.value,sequence=++navigationSequence
 // Drafts live in the shared project; changing a view neither writes nor waits
 // for server checks. KeepAlive retains local editor forms and selections.
  if(destination==='experience'&&p.value){returnTo.value={page:page.value==='experience'?returnTo.value.page:page.value,focus:focus.value,scrollY:window.scrollY};try{sessionStorage.setItem('animatedscroll-return:'+p.value.id,JSON.stringify(returnTo.value))}catch{};closeChecks(false)}
  page.value=destination;focus.value=target;mobileNav.value=false;writeRoute(destination)
  await nextTick()
  if(sequence!==navigationSequence)return
  if(target)document.querySelector<HTMLElement>(`[data-entity-key="${CSS.escape(target)}"]`)?.scrollIntoView({block:'start'})
  else if(destination!==previous)window.scrollTo(0,0)
}
async function returnToCreation(){try{const saved=sessionStorage.getItem('animatedscroll-return:'+p.value.id);if(saved)returnTo.value=restoredCreationPosition(saved)}catch{};const dest=returnTo.value;await navigate(dest.page,dest.focus);if(!error.value){await nextTick();window.scrollTo(0,dest.scrollY)}}
function beginName(mode:'create'|'rename'){nameDialog.value=mode;nameInput.value=mode==='rename'?(p.value.artworkName||p.value.title):'未命名画作';nextTick(()=>document.getElementById('project-name-input')?.focus())}
async function submitName(){const text=nameInput.value.trim();if(!text||text.length>120){error.value='请输入1至120字符的画作名称';return}if(nameDialog.value==='create'){await create(text);if(!error.value)nameDialog.value='';return}await run(async()=>{await syncLatest();const ack=clone(baselineProject.value);ack.title=text;const renamed=await api(`/projects/${p.value.id}/metadata`,'PATCH',{version:p.value.version,title:text});p.value.title=text;accepted(renamed,ack);nameDialog.value='';notice.value='画作名称已保存'})}
function selectEntity(kind:string,rid:string){focus.value=kind+':'+rid}
function openChecks(target=''){
 if(!p.value)return
 if(!checksOpen.value)returnFocus=document.activeElement as HTMLElement
 checkTarget.value=target;checksOpen.value=true;mobileNav.value=false
 // Checking observes saved state; it never saves an unfinished edit or starts a task.
 updateChecklist().catch(e=>{error.value=e.message})
}
function closeChecks(restore=true){checksOpen.value=false;if(restore)nextTick(()=>{if(returnFocus?.isConnected)returnFocus.focus()})}
async function goToCheck(row:CheckItem){
 if(row.kind==='suggestion'){checkTarget.value=itemKey(row);return}
 const destination=creationPages.some(p=>p.id===row.page)?row.page:'overview'
 const before=page.value;await navigate(destination,row.target||'')
 if(!error.value&&(page.value===destination||page.value!==before))closeChecks(false)
}
async function act(path:string,body:any){return api(`/projects/${p.value.id}/studio/${path}`,'POST',{version:p.value.version,...body})}
async function acknowledge(record:any){await run(async()=>{await saveAll();accepted(await act('acknowledge',{kind:record.kind,id:record.id}));notice.value='已记录复核，原生成依据和内容版本保持不变';await updateChecklist()})}
async function confirm(record:any,generate=false){const kind=record.kind,rid=record.id;if(entityBusy(kind,rid)){error.value='该结果区域正在生成，暂时不能确认';return}await run(async()=>{await saveAll();const plan=await act('preview',{kind,id:rid});if(plan.requiresRisk){closeChecks(false);risk.value={...plan,kind,id:rid,action:'confirm'};return}accepted(await act('confirm',{kind,id:rid,generate}));notice.value=p.value.generationNotice||'内容已确认';await updateChecklist()})}
async function acceptRisk(){const r=risk.value;await run(async()=>{accepted(await act(r.action,{kind:r.kind,id:r.id,acceptRisk:true,generate:false}));risk.value=null;notice.value='修改已保存';await updateChecklist()})}
async function discard(record:any){if(entityBusy(record.kind,record.id)){error.value='该结果区域正在生成，暂时不能撤回';return}await run(async()=>{await saveAll();accepted(await act('discard',{kind:record.kind,id:record.id}));await updateChecklist()})}
async function remove(record:any){if(entityBusy(record.kind,record.id)){error.value='该结果区域正在生成，暂时不能删除';return}await run(async()=>{await saveAll();try{accepted(await act('delete',{kind:record.kind,id:record.id}))}catch(e:any){if(e.detail?.code==='risk_confirmation_required'){closeChecks(false);risk.value={...e.detail,kind:record.kind,id:record.id,action:'delete'};return}throw e}await updateChecklist()})}
async function generate(task:string,target=''){
 if(task==='check'){await run(async()=>{await saveAll();accepted(await act('jobs',{task,target,trigger:'user_button'}));await updateChecklist()});return}
 const targetPage=({culture:'clues',relationship:'clues',plots:'outline',plot:'outline',plot_clues:'outline',clue:'clues',persona:'characters',knowledge:'characters',storyboard:'storyboards',structure_materials:'library'} as any)[task]||page.value
 await generateStep(targetPage,target?[target]:[],task==='structure_materials'||['plot','clue','persona'].includes(task)&&!!target||task==='storyboard'&&!!rec('storyboard',target)?.draft.prompt,task)
}
async function retryJob(job:any){
 if(job.family==='generation'||job.family==='completion'){await api(`/projects/${p.value.id}/studio/${job.family==='generation'?'generation-batches':'completions'}/${job.id}/continue`,'POST',{version:p.value.version,requestId:crypto.randomUUID()});await syncLatest();return}
 if(job.family!=='analysis'){await generate(job.task,job.target);return}
 await run(async()=>{await saveAll();await api(`/projects/${p.value.id}/tasks`,'POST',{version:p.value.version,kind:job.task,documentId:job.request?.documentId||'',pages:job.request?.pages||[],documents:job.request?.documents||[],targetArtwork:job.request?.targetArtwork||'',trigger:'user_button'});await refresh();notice.value='分析任务已提交'})
}
function add(kind:string,data:any,rid=id()){const r={id:rid,kind,draft:data,published:null,revision:0,state:'draft',refs:[],history:[]};p.value.workspace.entities[kind+':'+rid]=r;return r}
async function legacy(value:any){accepted(await api(`/projects/${value.id}/studio/editor`),value);await updateChecklist()}
async function openProject(pid:string){await saveAll();accepted(await api('/projects/'+pid+'/studio/editor'));localStorage.setItem('animatedscroll-project',pid);focus.value='';await restoreEdits();await updateChecklist()}
async function reloadProjects(){projects.value=await api('/projects');if(!p.value||!projects.value.some(item=>item.id===p.value.id)){if(projects.value.length){accepted(await api('/projects/'+projects.value[0].id+'/studio/editor'));localStorage.setItem('animatedscroll-project',projects.value[0].id);await updateChecklist()}else{p.value=null;baselineProject.value=null;checklist.value={ready:false,items:[]};page.value='overview';writeRoute('overview')}}}
async function create(projectName='未命名项目'){await run(async()=>{await saveAll();const project=await api('/projects','POST',{title:projectName});accepted(await api(`/projects/${project.id}/studio/editor`));projects.value=await api('/projects');localStorage.setItem('animatedscroll-project',project.id);page.value='library';focus.value='';writeRoute('library');await updateChecklist()})}
async function saveFolders(folders:any[]){await run(async()=>{await saveAll();accepted(await api(`/projects/${p.value.id}/studio/folders`,'PUT',{version:p.value.version,folders}))})}
const pollWarning=ref('')
let polling=false
async function poll(){
 if(!p.value||experience.value||busy.value||libraryBusy.value||polling||document.hidden)return
 polling=true
 const pid=p.value.id
 try{
  const update=await syncLatest();pollWarning.value=''
  if(p.value?.id===pid&&(update?.dataChanged||update?.jobsChanged))await updateChecklist()
 }catch(e:any){pollWarning.value='服务暂未连接，当前编辑已保留；将继续查询已有任务。'}finally{polling=false}
}
function hashChanged(){const route=resolveRoute(location.hash);if(route.checks){writeRoute('overview',true);navigate('overview').then(()=>openChecks());return}if(route.page!==page.value)navigate(route.page)}
let timer:any
async function initialize(){
 booting.value=true;bootError.value='';bootPhase.value='正在读取项目列表…'
 const ok=await run(async()=>{
  const saved=localStorage.getItem('animatedscroll-project')||''
  bootPhase.value='正在打开作品资料…'
  try{
   const result=await api('/studio/bootstrap?projectId='+encodeURIComponent(saved));projects.value=result.projects
   if(result.project){accepted(result.project);checklist.value={items:[],...result.checks};await restoreEdits()}
  }catch(e:any){
   if(e.status!==404)throw e
   projects.value=await api('/projects')
   if(projects.value.length){const pid=projects.value.find(p=>p.id===saved)?.id||projects.value[0].id;accepted(await api(`/projects/${pid}/studio/editor`));await updateChecklist();await restoreEdits()}
  }
 })
 if(!ok)bootError.value=error.value||'暂时无法读取项目，请重试'
 booting.value=false
 if(ok&&initial.checks){writeRoute('overview',true);openChecks()}
}
onMounted(async()=>{
 await initialize()
 if(!location.hash||!routeNames[location.hash.slice(2)])writeRoute(page.value,true)
 window.addEventListener('hashchange',hashChanged);timer=setInterval(()=>{clock.value=Date.now();poll()},3000)
})
onUnmounted(()=>{clearTimeout(saveTimer);clearTimeout(localTimer);clearInterval(timer);window.removeEventListener('hashchange',hashChanged)})
provide('studio',{experiments,openSmartEdit,runSmartAction,castEntries,unit,reviewing,confirmUnit,generateStep,scheduleAutosave,applyRecord,applyAll,registerDraftSaver,p,page,focus,busy,generating,error,notice,records,entries,rec,title,api,run,saveAll,refresh,navigate,confirm,acknowledge,discard,remove,generate,retryJob,add,legacy,saveFolders,checklist,updateChecklist,openChecks,goToCheck,pending,checkTarget,selectEntity,locked,entityBusy,rootLocked,syncLatest,activeJob,reloadProjects,openProject})
</script>

<template>
<StartupScreen v-if="booting||bootError" :phase="bootPhase" :error="bootError" @retry="initialize"/>
<div v-else class="app-frame" :class="{'experience-mode':experience}" @input="scheduleAutosave" @change="scheduleAutosave" @compositionstart="compositionStart" @compositionend="compositionEnd" @focusout="blurSave">
 <header class="app-topbar">
  <div class="brand-group"><button v-if="!experience" class="icon-button mobile-menu" aria-label="打开制作导航" :aria-expanded="mobileNav" @click="mobileNav=!mobileNav"><AppIcon name="menu"/></button><div class="brand"><span class="brand-mark"><AppIcon name="film" :size="19"/></span><span>AnimatedScroll</span></div></div>
  <button class="experiment-trigger" data-experiment-ignore @click="experiments.state.panel=true">{{experiments.recording()?'实验记录中':'实验面板'}}</button><nav class="mode-switch" aria-label="工作模式"><button :class="{active:!experience}" :aria-current="!experience?'page':undefined" :disabled="busy" @click="experience?returnToCreation():null">创作</button><button :class="{active:experience}" :aria-current="experience?'page':undefined" :disabled="busy" @click="navigate('experience')">欣赏作品</button></nav>
  <div class="topbar-actions" v-if="!experience"><label class="project-select"><span class="sr-only">当前项目</span><select :value="p?.id||''" :disabled="busy" @change="changeProject"><option v-if="!p" value="">选择项目</option><option v-for="item in projects" :key="item.id" :value="item.id">{{item.title}}</option></select></label><button class="icon-button" :disabled="busy||!p" @click="beginName('rename')" aria-label="修改画作名称" title="修改画作名称"><AppIcon name="edit" :size="16"/></button><button class="icon-button" :disabled="busy" @click="beginName('create')" aria-label="新建项目" title="新建项目"><AppIcon name="plus"/></button><span class="topbar-divider"/><CreationCopy/><button class="checks-trigger" aria-label="制作检查" :disabled="!p" :aria-expanded="checksOpen" @click="openChecks()"><AppIcon name="check" :size="17"/><span>制作检查</span><b class="count-badge" v-if="pending.length">{{pending.length}}</b></button></div>
  <button v-else class="return-creation" :disabled="busy" @click="returnToCreation"><AppIcon name="back" :size="17"/>返回创作</button>
 </header>
 <ExperimentPanel :tracker="experiments" :project-id="p?.id"/><ScreenshotFeedback :tracker="experiments" :project-id="p?.id" :page="page"/><div v-show="!experience" class="creation-space">
  <div v-if="mobileNav" class="mobile-nav-backdrop" @click="mobileNav=false"/>
  <aside class="creation-sidebar" :class="{open:mobileNav}"><div class="sidebar-caption">创作工作台</div><nav aria-label="制作步骤"><button v-for="item in creationPages" :key="item.id" :class="{active:page===item.id}" :aria-current="page===item.id?'page':undefined" :disabled="busy" @click="navigate(item.id)"><AppIcon :name="item.icon" :size="19"/><span>{{item.name}}</span><small>{{item.number}}</small></button></nav><div class="sidebar-foot"><span class="local-dot"/>本地创作空间<small>修改自动保存，AI内容可以继续使用。</small></div></aside>
  <div class="creation-main">
   <section class="global-todo" aria-label="当前制作步骤"><template v-if="activeJob"><span class="task-spinner"/><strong>{{activeJob.label}}</strong><span role="status">{{activeJob.progress}}<small v-if="activeJob.steps"> · {{activeJob.steps.filter((v:any)=>v.state==='completed').length}}/{{activeJob.steps.length}}</small></span><button @click="openChecks()">查看任务</button></template><template v-else-if="p"><strong>{{nextAction?.reason||'继续制作'}}</strong><button v-if="nextAction" @click="navigate(nextAction.page)">下一步：{{nextAction.label}}<AppIcon name="arrow" :size="15"/></button></template><span v-else>新建项目后导入画作和资料</span></section>
   <div v-if="pollWarning" class="app-message" role="status">{{pollWarning}}</div>
   <div v-if="error" class="app-message error" role="alert"><AppIcon name="alert" :size="17"/><span>{{error}}</span><button :disabled="busy||!p" @click="run(refresh)">重新加载</button><button class="icon-button" aria-label="关闭错误提示" @click="error=''"><AppIcon name="close" :size="16"/></button></div>
   <div v-if="conflicts.length" class="app-message error"><span>{{conflicts.length}} 个字段存在并行编辑冲突，当前编辑已保留。</span><button @click="showConflicts=true">查看差异</button></div><div v-if="notice" class="app-message" role="status"><span>{{notice}}</span><button class="icon-button" aria-label="关闭提示" @click="notice=''"><AppIcon name="close" :size="16"/></button></div>
   <main class="studio-shell">
    <div class="page-heading"><div><span class="eyebrow">{{page==='overview'?'系统概览':'当前步骤 · '+currentPage.number}}</span><h1>{{currentPage.name}}</h1></div><div class="project-meta" v-if="p"><GenerationButton v-if="page!=='overview'&&page!=='storyboards'" :page="page"/><small role="status">{{autoStatus}}</small></div></div>
    <section v-if="p&&page!=='overview'" class="page-guide"><template v-for="step in checklist.pages?.filter((v:any)=>v.id===page)"><span>{{step.done}}/{{step.total}} 项可用</span><span v-if="step.blocker">{{step.blocker}}</span><span v-else-if="step.complete">本步内容已可用，可继续下一步；人工核对为可选</span><span v-else>未完成项见下方卡片，其他可用内容不受影响</span><button v-if="step.nextAction&&step.nextAction.page!==page" @click="navigate(step.nextAction.page)">下一步：{{step.nextAction.label}}</button></template></section>
    <p v-if="p&&!['overview','library','experience'].includes(page)&&rec('material','main')?.draft.structured?.conflicts?.some((c:any)=>c.kind==='contradiction'&&c.status!=='retired'&&!['current','candidate'].includes(c.resolution))" class="material-dispute-note">资料中保留着不同说法，建议先处理相关分歧。继续创作时将保留不确定性。<button @click="navigate('library')">查看资料争议</button></p>
    <OverviewPage v-if="page==='overview'"/>
    <fieldset v-if="p" v-show="page!=='overview'" class="page-content" :disabled="busy"><KeepAlive :key="p.id" :max="5"><component v-if="pageComponents[page]" :is="pageComponents[page]" :key="page" v-on="page==='library'?{replace:legacy,running:(value:boolean)=>libraryBusy=value}:{}"/></KeepAlive></fieldset>
    <FeedbackComposer v-if="p&&!['overview','experience'].includes(page)" :key="p.id+':'+page" ref="smartComposer" :target="smartScope?.target||null" :label="smartScope?.label||''" :prepare="smartScope?.prepare"/>
    <section v-if="!p&&page!=='overview'" class="empty-project"><AppIcon :name="currentPage.icon" :size="40"/><h2>尚无项目</h2><p>新建项目后可导入画作和资料。项目内容保存在本机。</p><button class="primary" :disabled="busy" @click="beginName('create')">新建项目<AppIcon name="plus" :size="17"/></button></section>
   </main>
  </div>
  <CheckDrawer :open="checksOpen" :target="checkTarget" @close="closeChecks()"/>
 </div>
 <main v-show="experience" class="experience-stage" aria-label="欣赏作品"><h1 class="sr-only">欣赏作品</h1><KeepAlive><ExperiencePage v-if="experience&&p" :key="p.id"/></KeepAlive></main>
 <div v-if="nameDialog" class="modal name-modal" role="dialog" aria-modal="true" aria-labelledby="project-name-title" @keydown.esc="nameDialog=''"><article><h2 id="project-name-title">{{nameDialog==='create'?'新建项目':'修改画作名称'}}</h2><form @submit.prevent="submitName"><p class="muted">同名项目自动添加序号。</p><label>画作名称<input id="project-name-input" v-model="nameInput" maxlength="120" placeholder="输入画作名称" autocomplete="off"></label><div class="actions"><button type="submit" class="primary" :disabled="busy">保存</button><button type="button" :disabled="busy" @click="nameDialog=''">取消</button></div></form></article></div>
 <div v-if="showConflicts&&conflicts.length" class="modal" role="dialog" aria-modal="true" aria-label="处理编辑冲突"><article><h2>处理编辑冲突</h2><section v-for="c in conflicts" :key="c.path" class="card"><small>{{c.path}}</small><div class="columns"><div><h3>本地编辑</h3><pre>{{JSON.stringify(c.local,null,2)}}</pre><button @click="resolveConflict(c)">保留本地</button></div><div><h3>后台内容</h3><pre>{{JSON.stringify(c.incoming,null,2)}}</pre><button @click="resolveConflict(c,true)">采用后台内容</button></div></div></section><button @click="showConflicts=false">稍后处理</button></article></div>
 <div v-if="risk" class="modal risk-modal" role="dialog" aria-modal="true" aria-labelledby="risk-title"><article><h2 id="risk-title">{{risk.action==='delete'?'删除内容':'确认内容'}}前确认影响</h2><p>旧结果会保留，以下内容需要复核或重新生成。此次操作不会立即调用模型。</p><div v-for="c in risk.changes" class="change-row"><b>{{c.field}}</b><div class="columns"><pre>{{JSON.stringify(c.before,null,2)}}</pre><pre>{{JSON.stringify(c.after,null,2)}}</pre></div></div><ul><li v-for="a in risk.affected">{{a.name}} | {{a.mode==='review'?'待复核':'输入失效'}}</li></ul><div class="actions"><button class="primary" :disabled="busy" @click="acceptRisk">确认风险并{{risk.action==='delete'?'删除':'确认内容'}}</button><button :disabled="busy" @click="risk=null">取消，保留草稿</button></div></article></div>
</div>
</template>
