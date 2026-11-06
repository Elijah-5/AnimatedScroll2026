import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import ts from 'typescript'
const code=ts.transpileModule(readFileSync(new URL('../src/structuredRuntime.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
const {editLibraryField,editLibraryRow,libraryPeople,resolveLibraryConflict,relationshipGraph}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'))
test('manual artwork changes preserve lineage without falsely citing the old value',()=>{
 const d={artwork:{artist:{value:'旧值',generatedValue:'旧值',origin:'generated',referenceIds:['old-quote']}}}
 editLibraryField(d,'artist','人工新值');assert.equal(d.artwork.artist.generatedValue,'旧值');assert.deepEqual(d.artwork.artist.referenceIds,[]);assert.deepEqual(d.artwork.artist.previousReferenceIds,['old-quote']);assert.equal(d.artwork.artist.origin,'creator')
})
test('changing relation direction requires reviewing the original evidence again',()=>{
 const d={relations:[{id:'r',fromId:'a',toId:'b',category:'supported',referenceIds:['quote']}]}
 editLibraryRow(d,'relations','r','fromId','c');assert.equal(d.relations[0].category,'uncertain');assert.deepEqual(d.relations[0].referenceIds,[])
})
test('creation-role filtering keeps grouped instances while preserving distinct people with the same name',()=>{
 const people=[{id:'a',name:'宫女',characterId:'group',annotationIds:['one','two']},{id:'b',name:'宫女',characterId:'another'},{id:'researcher',name:'作者',characterId:'',contextRoles:['scholar']}]
 assert.equal(libraryPeople(people,false,'').length,2);assert.equal(libraryPeople(people,true,'scholar')[0].id,'researcher');assert.equal(libraryPeople(people,false,'')[0].annotationIds.length,2)
})
test('choosing the current value never silently adopts a model alternative',()=>{
 const conflict={id:'c',field:'artwork.artist',current:'人工',candidate:'建议',referenceIds:['new-quote']},d={artwork:{artist:{value:'人工',referenceIds:['old']}},conflicts:[conflict]}
 resolveLibraryConflict(d,conflict,false);assert.equal(d.artwork.artist.value,'人工');assert.deepEqual(d.artwork.artist.referenceIds,['old'])
 resolveLibraryConflict(d,conflict,true);assert.equal(d.artwork.artist.value,'建议');assert.deepEqual(d.artwork.artist.referenceIds,['new-quote'])
})
test('graph merges origins without losing direction, group identity or draft status',()=>{
 const people=[{id:'a',name:'角色',characterId:'char-a'},{id:'b',name:'宫女',characterId:'group',annotationIds:['one','two']}]
 const canonical=[{id:'r',fromId:'a',toId:'b',label:'带领',state:'confirmed',referenceIds:['e']}]
 const clue={id:'clue',state:'draft',published:null,draft:{relations:[{fromId:'char-a',toId:'group',label:'带领',quote:'原文'},{fromId:'group',toId:'char-a',label:'随侍'}]}}
 const graph=relationshipGraph(people,canonical,[clue])
 assert.equal(graph.nodes.length,2);assert.equal(graph.edges.length,2);assert.equal(graph.edges[0].origins.length,2)
 assert.equal(graph.edges[0].origins[0].state,'confirmed');assert.equal(graph.edges[0].origins[1].state,'draft');assert.equal(graph.edges[1].fromId,'b');assert.deepEqual(graph.nodes[1].annotationIds,['one','two'])
})
test('background people stay distinct and require explicit inclusion in the graph',()=>{
 const people=[{id:'a',name:'同名',characterId:'a'},{id:'b',name:'同名',characterId:''}],relations=[{id:'r',fromId:'a',toId:'b',label:'涉及'},{id:'bad',fromId:'a',toId:'missing',label:'待核对'}]
 const initial=relationshipGraph(people,relations,[]);assert.equal(initial.nodes.length,1);assert.equal(initial.hidden,1);assert.equal(initial.unresolved,1)
 const full=relationshipGraph(people,relations,[],true);assert.equal(full.nodes.length,2);assert.equal(full.edges.length,1)
})
const smartCode=ts.transpileModule(readFileSync(new URL('../src/smartEditRuntime.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
const {sameTarget,selectFiltered}=await import('data:text/javascript;base64,'+Buffer.from(smartCode).toString('base64'))
test('bulk selection covers all filtered pages and keeps unrelated selections',()=>{
 const all=Array.from({length:118},(_,i)=>'person-'+i)
 const selected=selectFiltered(['existing'],all,true)
 assert.equal(selected.length,119);assert.ok(selected.includes('person-117'))
 assert.deepEqual(selectFiltered(selected,all,false),['existing'])
})
test('smart edit target identity preserves fields and unit boundaries',()=>{
 assert.ok(sameTarget({kind:'plot',itemIds:['b','a','a']},{kind:'plot',section:'content',itemIds:['a','b']}))
 assert.ok(!sameTarget({kind:'clue',itemIds:['a'],unitIds:['u1']},{kind:'clue',itemIds:['a'],unitIds:['u2']}))
 assert.ok(!sameTarget({kind:'persona',itemIds:['a']},{kind:'character',itemIds:['a']}))
})
test('an existing character ID cannot bypass the shared cast exclusion in relationships',()=>{
 const people=[{id:'a',characterId:'a',castEligible:true},{id:'b',characterId:'b',castEligible:false}]
 const relations=[{fromId:'a',toId:'b',label:'提及'}]
 assert.equal(relationshipGraph(people,relations,[]).nodes.length,1)
 assert.equal(relationshipGraph(people,relations,[],true).nodes.length,2)
})
const experimentCode=ts.transpileModule(readFileSync(new URL('../src/experimentRuntime.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
const {redactExperiment,normalizedSelection,cropPixels,experimentTime,captureScrollOffset}=await import('data:text/javascript;base64,'+Buffer.from(experimentCode).toString('base64'))
test('experiment logs keep instructions and changes but exclude nested credentials and sensitive patch values',()=>{
 const value=redactExperiment({instruction:'合并唐太宗与太宗',password:'private',nested:{api_key:'secret'},changes:[{path:'/settings/password',value:'secret',before:'old'}]})
 assert.equal(value.instruction,'合并唐太宗与太宗');assert.ok(!JSON.stringify(value).includes('secret'));assert.ok(!JSON.stringify(value).includes('private'));assert.equal(value.changes[0].value,'[已省略敏感输入]')
})
test('screenshot crop uses original pixels for reverse drags and clamps the selected region',()=>{
 const box=normalizedSelection({x:.8,y:.7},{x:.2,y:.1})
 assert.deepEqual(cropPixels(box,2000,1000),{x:400,y:100,w:1200,h:600})
 assert.deepEqual(cropPixels(normalizedSelection({x:-1,y:-1},{x:2,y:2}),1440,900),{x:0,y:0,w:1440,h:900})
})
test('experiment time displays full duration across hour boundaries',()=>{
 assert.equal(experimentTime(3661500),'01:01:01');assert.equal(experimentTime(-20),'00:00:00')
})

test('page capture applies document scrolling once for both body and html scrolling roots',()=>{
 assert.deepEqual(captureScrollOffset({x:20,y:705},{x:20,y:705}),{x:0,y:0})
 assert.deepEqual(captureScrollOffset({x:20,y:705},{x:0,y:0}),{x:20,y:705})
})
