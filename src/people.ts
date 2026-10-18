export function personState(project:any,a:any){
 const c=project.characters.find((c:any)=>c.id===a.characterId)
 if(!c)return {key:'unnamed',label:'未命名'}
 if(a.identityConfirmed&&c.confirmed)return {key:'confirmed',label:'已确认'}
 if(a.needsReview||project.matches.some((m:any)=>m.annotationId===a.id&&m.stale))return {key:'review',label:'需复核'}
 return {key:'pending',label:'待确认'}
}
export function profile(c:any){if(!c)return '未关联资料人物。';if(c.namingOrigin==='creator')return '创作者命名，资料未提供历史身份／经历。';return c.summary||[c.identity,c.biography].filter(Boolean).join('；')||'资料中提及；未提供具体身份／经历。'}
