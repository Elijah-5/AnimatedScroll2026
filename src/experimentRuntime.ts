export const privateField=/password|secret|api.?key|authorization|access.?token|credential|cookie/i
export function redactExperiment(value:any):any{
 if(Array.isArray(value))return value.map(redactExperiment)
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,v])=>[key,privateField.test(key)||(privateField.test(value.path||'')&&['value','before','after'].includes(key))?'[已省略敏感输入]':redactExperiment(v)]))
 return value
}
export function experimentFieldAllowed(el:Element){return !el.closest('[data-experiment-ignore],[data-experiment-private]')&&!(el instanceof HTMLInputElement&&['password','hidden'].includes(el.type))&&!privateField.test([el.id,el.getAttribute('name'),el.getAttribute('autocomplete')].filter(Boolean).join(' '))}
export function normalizedSelection(a:{x:number,y:number},b:{x:number,y:number}){const x=Math.max(0,Math.min(1,Math.min(a.x,b.x))),y=Math.max(0,Math.min(1,Math.min(a.y,b.y)));return {x,y,w:Math.max(0,Math.min(1,Math.max(a.x,b.x))-x),h:Math.max(0,Math.min(1,Math.max(a.y,b.y))-y)}}
export function cropPixels(box:{x:number,y:number,w:number,h:number},width:number,height:number){const x=Math.max(0,Math.min(width-1,Math.round(box.x*width))),y=Math.max(0,Math.min(height-1,Math.round(box.y*height)));return {x,y,w:Math.max(1,Math.min(width-x,Math.round(box.w*width))),h:Math.max(1,Math.min(height-y,Math.round(box.h*height)))}}
export function experimentTime(ms:number){const seconds=Math.max(0,Math.floor(ms/1000));return `${String(Math.floor(seconds/3600)).padStart(2,'0')}:${String(Math.floor(seconds/60)%60).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`}

export function experimentPageLabel(page:string){return ({overview:'总览',library:'资料库',outline:'剧本',clues:'线索',characters:'人物档案',storyboards:'分镜',experience:'欣赏作品',experiment:'实验面板',feedback:'截图便笺'} as Record<string,string>)[page]||page}

export function captureScrollOffset(windowScroll:{x:number;y:number},rootScroll:{x:number;y:number}){return {x:windowScroll.x-rootScroll.x,y:windowScroll.y-rootScroll.y}}
