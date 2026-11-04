/** Narrative clues expose one paragraph; old unit evidence remains in saved history. */
export function narrativeText(d:any):string{return typeof d.content==='string'?d.content:(d.units||[]).map((u:any)=>u.text).join('\n')||d.summary||''}
export function setNarrativeText(d:any,text:string){
 d.content=text
 // The backend writes the edited paragraph as creative content and checks locks.
}
export function narrativeLocked(d:any):boolean{return (d.units||[]).some((u:any)=>u.locked)}
