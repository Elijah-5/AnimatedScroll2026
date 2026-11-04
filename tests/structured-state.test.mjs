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
