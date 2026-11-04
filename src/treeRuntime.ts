export type Branch={id:string,name:string,type:string,parentId:string,folder:boolean,root?:boolean,synthetic?:boolean,record?:any,children:Branch[]}
export function clueForest(folders:any[],clues:any[]):Branch[]{
 const by=new Map<string,Branch>(),roots:Branch[]=[]
 for(const f of folders)by.set('f:'+f.id,{...f,id:'f:'+f.id,parentId:f.parentId?'f:'+f.parentId:'',folder:true,children:[]})
 const valid=(node:Branch)=>{let p=node;const seen=new Set([p.id]);while(p.parentId){const next=by.get(p.parentId);if(!next||seen.has(next.id))return false;seen.add(next.id);p=next}return !!p.root}
 const lost:Branch={id:'missing',name:'分类待整理',type:'unknown',parentId:'',folder:true,synthetic:true,children:[]}
 for(const node of by.values()){if(!valid(node)){lost.children.push({...node,parentId:'missing',children:[]});continue}if(node.parentId)by.get(node.parentId)!.children.push(node);else roots.push(node)}
 for(const r of clues){const d=r.draft||r,folder=by.get('f:'+d.parentId),node:Branch={id:'c:'+r.id,name:d.name||'未命名线索',type:d.type,parentId:folder&&valid(folder)?folder.id:'missing',folder:false,record:r,children:[]};if(node.parentId==='missing')lost.children.push(node);else folder!.children.push(node)}
 if(lost.children.length)roots.push(lost);return roots
}
export function descendants(node:Branch):Branch[]{return node.folder?node.children.flatMap(descendants):[node]}
export function filterForest(nodes:Branch[],query:string):Branch[]{const q=query.trim().toLocaleLowerCase();if(!q)return nodes;return nodes.flatMap(n=>{if(n.name.toLocaleLowerCase().includes(q))return [n];const children=filterForest(n.children,q);return children.length?[{...n,children}]:[]})}
export function branchSelection(node:Branch,selected:string[],eligible:string[]){const ids=descendants(node).map(n=>n.id.slice(2)).filter(id=>eligible.includes(id)),count=ids.filter(id=>selected.includes(id)).length;return {ids,count,total:ids.length,checked:ids.length>0&&count===ids.length,mixed:count>0&&count<ids.length}}
export function toggleBranch(node:Branch,selected:string[],eligible:string[]){const state=branchSelection(node,selected,eligible);return state.checked?selected.filter(id=>!state.ids.includes(id)):[...new Set([...selected,...state.ids])]}
export function canReparent(nodes:Branch[],sourceId:string,targetId:string){const all:Branch[]=[];function walk(n:Branch){all.push(n);n.children.forEach(walk)}nodes.forEach(walk);const s=all.find(n=>n.id===sourceId),t=all.find(n=>n.id===targetId);if(!s||!t||!t.folder||s.root||s.synthetic||t.synthetic||s.id===t.id||s.type!==t.type)return false;let p:Branch|undefined=t;while(p){if(p.id===s.id)return false;p=all.find(n=>n.id===p!.parentId)}return true}
