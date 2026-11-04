import {reactive} from 'vue'
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'
const source=readFileSync(new URL('../src/navigation.ts',import.meta.url),'utf8')
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
const {resolveRoute,creationPages,pendingItems,runningItems,shortReason}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'))

test('home and unrecognised links enter overview',()=>{
 assert.deepEqual(resolveRoute(''),{page:'overview',checks:false})
 assert.deepEqual(resolveRoute('#/unknown'),{page:'overview',checks:false})
})
test('legacy checks link opens drawer over overview; deep links remain valid',()=>{
 assert.deepEqual(resolveRoute('#/checks'),{page:'overview',checks:true})
 assert.deepEqual(resolveRoute('#/characters'),{page:'characters',checks:false})
 assert.deepEqual(resolveRoute('#/experience'),{page:'experience',checks:false})
 assert.deepEqual(creationPages.map(p=>p.id),['overview','library','outline','clues','characters','storyboards'])
})
test('abnormal states come before earlier unfinished steps',()=>{
 const items=[{id:'a',page:'library',state:'missing'},{id:'b',page:'characters',state:'draft'},{id:'c',page:'storyboards',state:'stale'},{id:'d',page:'outline',state:'review'},{id:'e',page:'clues',state:'failed'},{id:'f',page:'library',state:'interrupted'}]
 assert.deepEqual(pendingItems(items).map(i=>i.id),['f','e','c','d','a','b'])
})
test('same severity uses stage then stable item id, independent of poll order',()=>{
 const items=[{id:'b',page:'characters',state:'review'},{id:'a',page:'characters',state:'changed'},{id:'c',page:'library',state:'review'}]
 assert.deepEqual(pendingItems(items).map(i=>i.id),['c','a','b'])
 assert.deepEqual(pendingItems([...items].reverse()),pendingItems(items))
})
test('running and confirmed items are not actionable pending work',()=>{
 const items=[{id:'a',state:'running'},{id:'b',state:'confirmed'},{id:'c',state:'queued'},{id:'d',state:'draft'}]
 assert.deepEqual(pendingItems(items).map(i=>i.id),['d'])
 assert.deepEqual(runningItems(items).map(i=>i.id),['a','c'])
})
test('duplicate rows collapse, distinct people sharing a label remain distinct',()=>{
 const a={id:'knowledge:a',page:'characters',name:'人物知识',state:'draft'},b={...a,id:'knowledge:b'}
 assert.equal(pendingItems([a,a,b]).length,2)
})
test('banner truncates long errors while retaining full source reason',()=>{
 const row={page:'library',name:'背景',state:'failed',reason:'x'.repeat(200)}
 assert.equal(shortReason(row).length,69)
 assert.equal(row.reason.length,200)
 assert.equal(shortReason({state:'draft'}),'可生成本步骤内容或直接填写')
})

test('knowledge awaiting prerequisites is excluded from immediate pending count',()=>{
 const items=[{id:'character:a',page:'characters',state:'confirmed'},{id:'knowledge:a',page:'characters',state:'waiting'},{id:'clue:a',page:'clues',state:'draft'}]
 assert.deepEqual(pendingItems(items).map(i=>i.id),['clue:a'])
})

const narrativeSource=readFileSync(new URL('../src/narrative.ts',import.meta.url),'utf8')
const narrativeJs=ts.transpileModule(narrativeSource,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
const {narrativeText,setNarrativeText,narrativeLocked}=await import('data:text/javascript;base64,'+Buffer.from(narrativeJs).toString('base64'))
test('legacy narrative units display as one editable text without changing evidence',()=>{
 const clue={units:[{text:'第一段动作',references:[{quote:'原文'}]},{text:'第二段动作',references:[]}],plotIds:['p']}
 const before=structuredClone(clue)
 assert.equal(narrativeText(clue),'第一段动作\n第二段动作')
 assert.deepEqual(clue,before)
 setNarrativeText(clue,'一小段新的情节')
 assert.equal(narrativeText(clue),'一小段新的情节')
 assert.deepEqual(clue.units,before.units)
})
test('locked legacy narrative remains visibly locked',()=>{
 assert.equal(narrativeLocked({units:[{text:'情节',locked:true}]}),true)
 assert.equal(narrativeLocked({content:'情节',units:[]}),false)
})

const editSource=readFileSync(new URL('../src/editRuntime.ts',import.meta.url),'utf8')
const editJs=ts.transpileModule(editSource,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
const {mergeProject,valueAt,setAt,pathLocked,localInputChanged,elapsedLabel,pollUpdate}=await import('data:text/javascript;base64,'+Buffer.from(editJs).toString('base64'))
test('background result merges without dropping an unrelated unsaved edit',()=>{
 const base={version:1,title:'项目',workspace:{entities:{'character:a':{draft:{name:'甲'}},'clue:b':{draft:{content:'旧'}}},jobs:[]}}
 const local=structuredClone(base);local.workspace.entities['character:a'].draft.name='人工编辑'
 const incoming=structuredClone(base);incoming.version=2;incoming.workspace.entities['clue:b'].draft.content='生成结果'
 const merged=mergeProject(base,local,incoming)
 assert.equal(merged.value.version,2)
 assert.equal(merged.value.workspace.entities['character:a'].draft.name,'人工编辑')
 assert.equal(merged.value.workspace.entities['clue:b'].draft.content,'生成结果')
 assert.equal(merged.conflicts.length,0)
})
test('same-field conflicts retain local content until explicit choice',()=>{
 const merged=mergeProject({name:'旧'},{name:'本地'},{name:'远端'})
 assert.equal(merged.value.name,'本地');assert.equal(merged.conflicts[0].path,'/name')
 setAt(merged.value,'/name',merged.conflicts[0].incoming);assert.equal(merged.value.name,'远端')
})
test('ID lists merge independent additions and preserve concurrent row edits',()=>{
 const base={annotations:[{id:'a',x:.1,description:'旧'}]}
 const local={annotations:[{id:'a',x:.2,description:'旧'}]}
 const incoming={annotations:[{id:'a',x:.1,description:'观察'},{id:'b',x:.5,description:'新增'}]}
 const result=mergeProject(base,local,incoming)
 assert.deepEqual(result.value.annotations,[{id:'a',x:.2,description:'观察'},{id:'b',x:.5,description:'新增'}])
 assert.equal(result.conflicts.length,0)
})
test('task scopes lock output fields while other fields remain editable',()=>{
 const writes=['/workspace/entities/storyboard:s/draft/prompt']
 assert.equal(pathLocked(writes,'/workspace/entities/storyboard:s/draft/prompt'),true)
 assert.equal(pathLocked(writes,'/workspace/entities/storyboard:s/draft/region'),false)
 assert.equal(pathLocked(writes,'/workspace/entities/storyboard:s/draft'),false)
 assert.equal(pathLocked(writes,'/workspace/entities/storyboard:s',true),true)
 assert.equal(pathLocked(writes,'/workspace/entities/character:a/draft'),false)
})
test('only actual local input edits flag a running task',()=>{
 const base={imageVersion:1,title:'旧',annotations:[{id:'a',x:.1}]};const local=structuredClone(base)
 const job={readSet:['/imageVersion','/annotations/@a/x']}
 local.title='改名';assert.equal(localInputChanged(job,base,local),false)
 local.annotations[0].x=.2;assert.equal(localInputChanged(job,base,local),true)
 assert.equal(valueAt(local,'/annotations/@a/x'),.2)
 assert.equal(elapsedLabel('2026-10-31T00:00:00Z',Date.parse('2026-10-31T00:01:05Z')),'1:05')
})
test('unchanged polling keeps local drafts and only reports changed job status',()=>{
 const current={id:'p',version:3,workspace:{jobs:[],entities:{a:{draft:{name:'未保存姓名'}}}}},before=structuredClone(current)
 const update=pollUpdate(current,'p',{version:3,changed:false,jobs:[{id:'j',state:'running'}]})
 assert.equal(update.project,null);assert.equal(update.dataChanged,false);assert.equal(update.jobsChanged,true);assert.deepEqual(current,before)
})
test('late polling cannot restore an older project or cross project boundaries',()=>{
 const current={id:'new',version:5,workspace:{jobs:[]}}
 assert.equal(pollUpdate(current,'old',{version:6,changed:true,project:{id:'old',version:6}}),null)
 assert.equal(pollUpdate(current,'new',{version:4,changed:false,jobs:[]}),null)
 assert.equal(pollUpdate(current,'new',{version:6,changed:true,project:{id:'wrong',version:6}}),null)
})
test('new project snapshots merge while keeping concurrent unsaved input',()=>{
 const base={id:'p',version:1,workspace:{jobs:[],entities:{a:{draft:{name:'甲'}}}}},local=structuredClone(base),project=structuredClone(base)
 local.workspace.entities.a.draft.name='人工编辑';project.version=2
 const update=pollUpdate(local,'p',{version:2,changed:true,project})
 assert.equal(update.dataChanged,true);assert.equal(mergeProject(base,local,update.project).value.workspace.entities.a.draft.name,'人工编辑')
})

const peopleSource=readFileSync(new URL('../src/people.ts',import.meta.url),'utf8')
const peopleJs=ts.transpileModule(peopleSource,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
const {instanceName}=await import('data:text/javascript;base64,'+Buffer.from(peopleJs).toString('base64'))
test('group instances get distinct labels while sharing one character profile',()=>{
 const p={characters:[{id:'group',name:'宫女',roleType:'group'},{id:'named',name:'甲',roleType:'named'}],annotations:[{id:'a',kind:'character',characterId:'group',x:.5},{id:'b',kind:'character',characterId:'named'},{id:'c',kind:'character',characterId:'group',x:.1},{id:'d',kind:'character',characterId:''}]}
 const before=structuredClone(p)
 assert.deepEqual(p.annotations.map(a=>instanceName(p,a)),['宫女(1)','甲','宫女(2)','人物 4'])
 assert.deepEqual(p,before)
 p.annotations[0].x=.01
 assert.equal(instanceName(p,p.annotations[0]),'宫女(1)')
 assert.equal(p.characters.filter(c=>c.id==='group').length,1)
})

test('optional AI advice is retained outside required pending actions',()=>{
 const advice={id:'suggestion:one',page:'checks',state:'review',kind:'suggestion',name:'AI建议'}
 assert.equal(pendingItems([advice]).length,0)
})

const reviewSource=readFileSync(new URL('../src/reviewRuntime.ts',import.meta.url),'utf8')
const reviewJs=ts.transpileModule(reviewSource,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
const {editorProject,saveChanges,shouldScheduleSave,generationLabel}=await import('data:text/javascript;base64,'+Buffer.from(reviewJs).toString('base64'))
test('editor projection keeps history server-side and excludes it from autosave',()=>{
 const p={sources:[],workspace:{revisionArchive:{large:'history'},historyLibrary:{},entities:{'character:a':{draft:{name:'甲'},history:['old'],basisWarnings:[]}}}}
 const projected=editorProject(p)
 assert.equal(projected.workspace.revisionArchive,undefined)
 assert.equal(projected.workspace.entities['character:a'].history,undefined)
 assert.deepEqual(saveChanges(p,projected),[])
 assert.equal(p.workspace.revisionArchive.large,'history')
})
test('autosave patches keyed objects independently and retains incomplete input',()=>{
 const base={sources:[{id:'a',text:'原文'},{id:'b',text:'其他'}],workspace:{entities:{'character:a':{draft:{name:'甲',summary:'小传'}}}}}
 const current=structuredClone(base);current.sources[0].text='';current.workspace.entities['character:a'].draft.summary='新小传'
 const patches=saveChanges(base,current)
 assert.deepEqual(patches.map(p=>p.path),['/sources/@a/text','/workspace/entities/character:a/draft/summary'])
 assert.equal(patches[0].value,'');assert.equal(patches[0].before,'原文')
})
test('IME composition never schedules a save; first and repeat generation are distinct',()=>{
 assert.equal(shouldScheduleSave(true,1),false);assert.equal(shouldScheduleSave(false,0),false);assert.equal(shouldScheduleSave(false,2),true)
 assert.equal(generationLabel(false,false),'首次生成');assert.equal(generationLabel(false,true),'生成未完成内容');assert.equal(generationLabel(true,true),'重新生成')
})

test('autosave snapshots reactive additions before IndexedDB and never changes a retry payload',()=>{
 const base={workspace:{entities:{}}},current=reactive({authoringDrafts:{sourceForm:{title:'未写完的来源',text:''}},workspace:{entities:{'character:new':{draft:{name:'新人',mentions:[]}}}}})
 const changes=saveChanges(base,current),saved=structuredClone(changes)
 current.authoringDrafts.sourceForm.title='之后的编辑';current.workspace.entities['character:new'].draft.name='之后的姓名'
 assert.deepEqual(changes,saved)
 assert.equal(saved.find(v=>v.path==='/authoringDrafts').value.sourceForm.title,'未写完的来源')
})

const visualGroupJs=ts.transpileModule(readFileSync(new URL('../src/visualGroups.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
const {visualCards,selectedFigure,figureCardAnchor}=await import('data:text/javascript;base64,'+Buffer.from(visualGroupJs).toString('base64'))
test('explicit group roles form a single stacked card while named roles stay separate',()=>{
 const p={characters:[{id:'g',roleType:'group'},{id:'a',roleType:'named',name:'同名'},{id:'b',roleType:'named',name:'同名'}],annotations:[{id:'one',kind:'character',characterId:'g'},{id:'named1',kind:'character',characterId:'a'},{id:'two',kind:'character',characterId:'g'},{id:'named2',kind:'character',characterId:'b'}]}
 const before=structuredClone(p),cards=visualCards(p)
 assert.deepEqual(cards.map(c=>c.id),['visual-group:g','visual:named1','visual:named2'])
 assert.deepEqual(cards[0].members.map(a=>a.id),['one','two']);assert.deepEqual(p,before)
 assert.equal(selectedFigure(cards[0],'two').id,'two');assert.equal(selectedFigure(cards[0],'gone').id,'one')
 assert.equal(figureCardAnchor(cards,'two'),'person-group-g');assert.equal(figureCardAnchor(cards,'named1'),'person-named1')
 assert.equal(visualCards(p,false).length,4)
})

const treeJs=ts.transpileModule(readFileSync(new URL('../src/treeRuntime.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
const tree=await import('data:text/javascript;base64,'+Buffer.from(treeJs).toString('base64'))
const treeFolders=[{id:'culture',name:'文化',type:'culture',root:true,parentId:''},{id:'sub',name:'礼仪',type:'culture',parentId:'culture'},{id:'deep',name:'朝服',type:'culture',parentId:'sub'},{id:'relationship',name:'关系',type:'relationship',root:true,parentId:''}]
const treeClues=[{id:'a',draft:{name:'官服',type:'culture',parentId:'deep'}},{id:'b',draft:{name:'步辇',type:'culture',parentId:'sub'}},{id:'lost',draft:{name:'旧线索',type:'culture',parentId:'missing'}}]
test('graph preserves IDs, hierarchy and orphaned clues without mutation',()=>{const before=structuredClone(treeClues),f=tree.clueForest(treeFolders,treeClues);assert.deepEqual(tree.descendants(f[0]).map(n=>n.id),['c:a','c:b']);assert.equal(f.at(-1).name,'分类待整理');assert.equal(f.at(-1).children[0].id,'c:lost');assert.deepEqual(treeClues,before)})
test('search retains all ancestor nodes; clearing restores full tree',()=>{const f=tree.clueForest(treeFolders,treeClues),result=tree.filterForest(f,'官服');assert.equal(result[0].children[0].children[0].children[0].id,'c:a');assert.deepEqual(tree.filterForest(f,''),f);assert.equal(tree.filterForest(f,'无匹配').length,0)})
test('branch selection uses complete eligible descendants despite filtered rendering',()=>{const f=tree.clueForest(treeFolders,treeClues),state=tree.branchSelection(f[0],['a'],['a','b']);assert.equal(state.mixed,true);assert.equal(state.total,2);assert.deepEqual(tree.toggleBranch(f[0],['a','stale'],['a','b']),['a','stale','b']);assert.deepEqual(tree.toggleBranch(f[0],['a','b','stale'],['a','b']),['stale'])})
test('knowledge selection never adds unavailable clues',()=>{const f=tree.clueForest(treeFolders,treeClues);assert.deepEqual(tree.toggleBranch(f[0],[],['a']),['a']);assert.equal(tree.branchSelection(f[0],[],[]).checked,false)})
test('moves reject root, self, descendants and cross-type targets',()=>{const f=tree.clueForest(treeFolders,treeClues);assert.equal(tree.canReparent(f,'f:sub','f:deep'),false);assert.equal(tree.canReparent(f,'f:culture','f:sub'),false);assert.equal(tree.canReparent(f,'c:a','f:relationship'),false);assert.equal(tree.canReparent(f,'f:sub','f:sub'),false);assert.equal(tree.canReparent(f,'c:a','f:sub'),true)})
test('corrupted folder cycles stay visible as unclassified and do not recurse',()=>{const f=tree.clueForest([{id:'x',name:'x',parentId:'y'},{id:'y',name:'y',parentId:'x'}],[]);assert.equal(f[0].children.length,2)})
const boxJs=ts.transpileModule(readFileSync(new URL('../src/boxRuntime.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
const {hitFigure}=await import('data:text/javascript;base64,'+Buffer.from(boxJs).toString('base64'))
test('overlapping figures prefer selected resize, nearest edge then smaller area',()=>{const a=[{id:'large',x:.1,y:.1,w:.7,h:.7},{id:'small',x:.2,y:.2,w:.2,h:.2}];assert.deepEqual(hitFigure(a,.4,.4,1000,1000,'small'),{id:'small',resize:true});assert.equal(hitFigure(a,.3,.3,1000,1000,'').id,'small');assert.equal(hitFigure(a,.1,.3,1000,1000,'').id,'large');assert.equal(hitFigure(a,.95,.95,1000,1000,''),null)})
