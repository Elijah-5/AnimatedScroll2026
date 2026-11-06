/** One explicit action for the source panel and the page toolbar. */
export async function organizeMaterials(s:any,selections?:{documentId:string;pages:number[]}[]){
 await s.saveAll()
 const pid=s.p.value.id,material=s.rec('material','main').draft,input=material.literatureInput
 if(input?.text?.trim()){
  const result=await s.api(`/projects/${pid}/documents/text`,'POST',{version:s.p.value.version,...input})
  await s.legacy(result.project)
  s.rec('material','main').draft.literatureInput={...input,documentId:result.documentId,sourceVersion:result.sourceVersion}
  await s.saveAll()
 }
 const documents=selections||s.p.value.documents.map((d:any)=>({documentId:d.id,pages:[]}))
 if(!documents.length&&!Object.values(s.p.value.materialInputs||{}).some((v:any)=>typeof v==='string'&&v.trim()))throw Error('请先加入文献或输入资料文本')
 const body=documents.length?{kind:'document_analysis',targetArtwork:s.p.value.targetArtwork||s.p.value.artworkName||s.p.value.title,documents}:{kind:'materials'}
 await s.api(`/projects/${pid}/tasks`,'POST',{version:s.p.value.version,...body,trigger:'user_button',autoEnable:true})
 await s.syncLatest()
}
