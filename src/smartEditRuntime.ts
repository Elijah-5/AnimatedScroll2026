export interface SmartTarget {kind:string;section?:string;itemIds:string[];fields?:string[];unitIds?:string[]}
export function normalizedTarget(target:SmartTarget){return {kind:target.kind,section:target.section||'content',itemIds:[...new Set(target.itemIds)].sort(),fields:[...new Set(target.fields||[])].sort(),unitIds:[...new Set(target.unitIds||[])].sort()}}
export function sameTarget(a:SmartTarget|undefined,b:SmartTarget|undefined){return !!a&&!!b&&JSON.stringify(normalizedTarget(a))===JSON.stringify(normalizedTarget(b))}
export function selectFiltered(selected:string[],ids:string[],all:boolean){const result=new Set(selected);for(const id of ids)all?result.add(id):result.delete(id);return [...result]}
