export function hitFigure(boxes:any[],x:number,y:number,width:number,height:number,selected:string,handles=true){
 if(handles){const a=boxes.find(a=>a.id===selected);if(a&&Math.abs((a.x+a.w-x)*width)<=8&&Math.abs((a.y+a.h-y)*height)<=8)return {id:a.id,resize:true}}
 const hits=boxes.map((a,i)=>{const inside=x>=a.x&&x<=a.x+a.w&&y>=a.y&&y<=a.y+a.h,edge=Math.min(Math.abs((x-a.x)*width),Math.abs((x-a.x-a.w)*width),Math.abs((y-a.y)*height),Math.abs((y-a.y-a.h)*height));return {a,i,inside,edge}}).filter(v=>v.inside||(x>=v.a.x-5/width&&x<=v.a.x+v.a.w+5/width&&y>=v.a.y-5/height&&y<=v.a.y+v.a.h+5/height&&v.edge<=5))
 hits.sort((a,b)=>Number(b.edge<=5)-Number(a.edge<=5)||(a.edge<=5&&b.edge<=5?a.edge-b.edge:0)||a.a.w*a.a.h-b.a.w*b.a.h||a.i-b.i)
 return hits.length?{id:hits[0]!.a.id,resize:false}:null
}
