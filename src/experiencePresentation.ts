export type Box={x:number;y:number;w:number;h:number}
export type Figure={annotationId:string;characterId:string;name:string;identity:string;box:Box;portraitBox?:Box;canChat?:boolean}
export function castGroups(people:Figure[]){
 const groups=new Map<string,{person:Figure;instances:Figure[]}>()
 for(const person of people){const group=groups.get(person.characterId);if(group)group.instances.push(person);else groups.set(person.characterId,{person,instances:[person]})}
 return [...groups.values()]
}
export function avatarBox(person:Figure):Box{return person.portraitBox||{...person.box,h:person.box.h/3}}
export function paintingFrame(width:number,height:number,imageWidth:number,imageHeight:number){
 const scale=Math.min(width/Math.max(1,imageWidth),height/Math.max(1,imageHeight))
 const w=imageWidth*scale,h=imageHeight*scale
 return {x:(width-w)/2,y:(height-h)/2,w,h}
}
export function focusTransform(frame:{x:number;y:number;w:number;h:number},width:number,height:number,box?:Box){
 if(!box)return {x:0,y:0,scale:1}
 const scale=Math.max(1.15,Math.min(4.8,width*.58/Math.max(1,box.w*frame.w),height*.7/Math.max(1,box.h*.5*frame.h)))
 return {scale,x:width*.5-frame.x-(box.x+box.w/2)*frame.w*scale,y:height*.47-frame.y-(box.y+box.h/4)*frame.h*scale}
}
export function regionTransform(frame:{x:number;y:number;w:number;h:number},width:number,height:number,box?:Box){
 if(!box||![box.x,box.y,box.w,box.h].every(Number.isFinite)||box.w<=0||box.h<=0||box.x<0||box.y<0||box.x+box.w>1.000001||box.y+box.h>1.000001)return {x:0,y:0,scale:1}
 const scale=Math.max(1,Math.min(4.8,width*.9/(box.w*frame.w),height*.86/(box.h*frame.h)))
 return {scale,x:width*.5-frame.x-(box.x+box.w/2)*frame.w*scale,y:height*.5-frame.y-(box.y+box.h/2)*frame.h*scale}
}
export function narrationSentences(text:string){return (text.match(/[^。！？；\n]+[。！？；]?/g)||[]).map(s=>s.trim()).filter(Boolean)}
export function messageTime(value:string){
 const date=new Date(value)
 return Number.isNaN(date.getTime())?'':date.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false})
}
