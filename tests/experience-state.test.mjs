import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import ts from 'typescript'
const source=readFileSync(new URL('../src/experienceRuntime.ts',import.meta.url),'utf8')
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
const {nextMessageRequest,savedVideoReady,restoredCreationPosition,serviceError,hintedDraft,replySegments,nextCompletionRequest}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'))
const presentation=ts.transpileModule(readFileSync(new URL('../src/experiencePresentation.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
const {castGroups,avatarBox,paintingFrame,focusTransform,regionTransform,narrationSentences,messageTime}=await import('data:text/javascript;base64,'+Buffer.from(presentation).toString('base64'))
test('experience reload restores a validated creation position',()=>{
 assert.deepEqual(restoredCreationPosition(JSON.stringify({page:'storyboards',focus:'storyboard:abc',scrollY:140})),{page:'storyboards',focus:'storyboard:abc',scrollY:140})
 assert.equal(restoredCreationPosition('{broken').page,'overview')
 assert.equal(restoredCreationPosition(JSON.stringify({page:'experience',scrollY:-1})).page,'overview')
})
test('an old backend explains missing feature routes without confusing a missing project',()=>{
 assert.match(serviceError(404,'Not Found'),/重启服务器/)
 assert.equal(serviceError(404,'项目不存在'),'项目不存在')
 assert.equal(serviceError(409,{message:'项目版本已变化'}),'项目版本已变化')
})
test('network retry reuses the same message ID without creating more paid work',()=>{
 const previous={requestId:'original',characterId:'c',text:'问题'}
 assert.equal(nextMessageRequest(previous,'c','问题',false,()=>{throw Error('must not allocate')}),previous)
})
test('changing the selected character does not reuse another character request',()=>{
 assert.deepEqual(nextMessageRequest({requestId:'old',characterId:'a',text:'问题'},'b','问题',false,()=> 'new'),{requestId:'new',characterId:'b',text:'问题'})
})
test('editing a question or explicitly retrying a failed answer creates a fresh request',()=>{
 const p={requestId:'old',characterId:'a',text:'旧问题'}
 assert.equal(nextMessageRequest(p,'a','新问题',false,()=> 'edited').requestId,'edited')
 assert.equal(nextMessageRequest(p,'a','旧问题',true,()=> 'retry').requestId,'retry')
})
test('only a saved current prompt can be submitted for video generation',()=>{
 const preview={customized:true,stale:false}
 assert.equal(savedVideoReady(preview,'审核文本','审核文本'),true)
 assert.equal(savedVideoReady(preview,'未保存编辑','审核文本'),false)
 assert.equal(savedVideoReady({...preview,stale:true},'审核文本','审核文本'),false)
 assert.equal(savedVideoReady({...preview,customized:false},'编译草稿','编译草稿'),false)
 assert.equal(savedVideoReady(preview,'  ','  '),false)
})
test('group instances share one card without losing their individual painting targets',()=>{
 const a={annotationId:'a',characterId:'group',name:'宫人',box:{x:.1,y:.1,w:.2,h:.6}},b={...a,annotationId:'b'},c={...a,annotationId:'c',characterId:'other'}
 const grouped=castGroups([a,b,c]);assert.equal(grouped.length,2);assert.deepEqual(grouped[0].instances,[a,b]);assert.equal(grouped[0].person,a)
})
test('avatar uses a calibrated face, otherwise exactly the upper third',()=>{
 const p={box:{x:.1,y:.2,w:.2,h:.6}}
 assert.deepEqual(avatarBox(p),{x:.1,y:.2,w:.2,h:.6/3})
 const portraitBox={x:.12,y:.21,w:.05,h:.08};assert.equal(avatarBox({...p,portraitBox}),portraitBox)
})
test('focus preserves painting aspect and centers the upper half of the chosen figure',()=>{
 const frame=paintingFrame(800,500,1200,400);assert.ok(Math.abs(frame.w/frame.h-3)<1e-12)
 const box={x:.6,y:.1,w:.1,h:.8},focus=focusTransform(frame,800,500,box)
 assert.ok(focus.scale>1)
 assert.ok(Math.abs(frame.x+focus.x+(box.x+box.w/2)*frame.w*focus.scale-400)<.001)
 assert.ok(Math.abs(frame.y+focus.y+(box.y+box.h/4)*frame.h*focus.scale-235)<.001)
 assert.deepEqual(focusTransform(frame,800,500),{x:0,y:0,scale:1})
 assert.equal(messageTime('invalid'),'')
})

test('applying a hint fills only once and preserves the draft for restoration',()=>{
 const first=hintedDraft('未发送的问题','建议问题',false)
 assert.deepEqual(first,{text:'建议问题',backup:'未发送的问题'})
 assert.deepEqual(hintedDraft('修改过的建议问题','建议问题',true),{text:'修改过的建议问题',backup:null})
})
test('legacy replies stay unclassified and unknown segment labels stay creative',()=>{
 assert.equal(replySegments({answer:'旧内容'})[0].category,'legacy')
 assert.equal(replySegments({dialogueVersion:2,segments:[{text:'新内容',category:'invented',evidence:[]} ]})[0].category,'fiction')
 assert.deepEqual(replySegments({dialogueVersion:2,segments:[{text:'原话',category:'supported',evidence:[]} ]})[0],{text:'原话',category:'supported',evidence:[]})
})

test('completion network retries keep their request id for the same saved inputs',()=>{
 const first=nextCompletionRequest(undefined,'p',4,'characters',()=> 'a')
 assert.equal(nextCompletionRequest(first,'p',4,'characters',()=> 'b'),first)
})
test('completion identities never cross projects, pages or changed versions',()=>{
 const first=nextCompletionRequest(undefined,'p',4,'characters',()=> 'a')
 for(const [pid,version,page] of [['other',4,'characters'],['p',5,'characters'],['p',4,'all']])assert.equal(nextCompletionRequest(first,pid,version,page,()=> 'new').requestId,'new')
})

const assetJs=ts.transpileModule(readFileSync(new URL('../src/experienceAssets.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
const {productionToken,reusablePresentation,loadImage}=await import('data:text/javascript;base64,'+Buffer.from(assetJs).toString('base64'))
test('creation warning token ignores local drafts and artwork renaming',()=>{const p={title:'旧画名',version:3,workspace:{entities:{'character:c':{revision:1,state:'confirmed',published:{name:'人物'},draft:{name:'草稿'}}}}};const token=productionToken(p);p.title='新画名';p.version++;p.workspace.entities['character:c'].draft.name='新草稿';assert.equal(productionToken(p),token);p.workspace.entities['character:c'].published.name='新人物';assert.notEqual(productionToken(p),token)})
test('presentation reuse requires matching session and manifest, never just a project',()=>{const a={id:'manifest',sessionId:'old'};assert.equal(reusablePresentation(a,{...a}),true);assert.equal(reusablePresentation(a,{...a,sessionId:'new'}),false);assert.equal(reusablePresentation(a,{...a,id:'new-assets'}),false)})
test('image preparation shares one load and decode across portraits and painting',async()=>{let created=0,decoded=0;const previous=globalThis.Image;globalThis.Image=class{constructor(){created++}set src(value){queueMicrotask(()=>this.onload())}async decode(){decoded++}};try{const a=loadImage('test-shared-source'),b=loadImage('test-shared-source');assert.equal(a,b);assert.equal(await a,await b);assert.equal(created,1);assert.equal(decoded,1)}finally{globalThis.Image=previous}})
test('image loading failure can be explicitly retried without retaining a rejected cache',async()=>{let count=0;const previous=globalThis.Image;globalThis.Image=class{set src(value){queueMicrotask(()=>{count++;if(count===1)this.onerror();else this.onload()})}async decode(){}};try{await assert.rejects(loadImage('test-failed-source'));await loadImage('test-failed-source');assert.equal(count,2)}finally{globalThis.Image=previous}})

test('storyboard focus centers the complete region, without the portrait upper-half bias',()=>{const frame=paintingFrame(800,500,1200,600),box={x:.1,y:.15,w:.25,h:.6};const t=regionTransform(frame,800,500,box);assert.ok(t.scale>1);assert.ok(Math.abs(frame.x+t.x+(box.x+box.w/2)*frame.w*t.scale-400)<.001);assert.ok(Math.abs(frame.y+t.y+(box.y+box.h/2)*frame.h*t.scale-250)<.001);assert.deepEqual(regionTransform(frame,800,500,{...box,x:NaN}),{x:0,y:0,scale:1})})
test('narration captions preserve reviewed words and split at Chinese sentence boundaries',()=>{assert.deepEqual(narrationSentences('太宗坐于辇上。\n使者行礼；此为文献叙事！'),['太宗坐于辇上。','使者行礼；','此为文献叙事！']);assert.deepEqual(narrationSentences(''),[])})
