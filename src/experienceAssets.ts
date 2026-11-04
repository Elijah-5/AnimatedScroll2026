/** Browser-decoded resources shared by portraits, restored sessions and refreshed works. */
export type AlphaMask={data:Uint8ClampedArray,w:number,h:number}
export type PreparedAssets={width:number,height:number,alpha:Record<string,AlphaMask>}
const images=new Map<string,Promise<HTMLImageElement>>(),masks=new Map<string,Promise<AlphaMask>>(),videos=new Map<string,Promise<void>>()
export function loadImage(url:string):Promise<HTMLImageElement>{
 if(!images.has(url))images.set(url,new Promise((resolve,reject)=>{const image=new Image();image.onload=async()=>{try{await image.decode();resolve(image)}catch{images.delete(url);reject(Error('图片无法解码，请重试准备'))}};image.onerror=()=>{images.delete(url);reject(Error('图片加载失败，请重试准备'))};image.src=url}))
 return images.get(url)!
}
function mask(row:any){if(!masks.has(row.key))masks.set(row.key,loadImage(row.url).then(image=>{const c=document.createElement('canvas');c.width=Math.min(240,image.naturalWidth);c.height=Math.max(1,Math.round(image.naturalHeight*c.width/image.naturalWidth));const ctx=c.getContext('2d',{willReadFrequently:true});if(!ctx)throw Error('浏览器无法准备人物命中数据');ctx.drawImage(image,0,0,c.width,c.height);return {data:ctx.getImageData(0,0,c.width,c.height).data,w:c.width,h:c.height}}).catch(error=>{masks.delete(row.key);throw error}));return masks.get(row.key)!}
function metadata(url:string){if(!videos.has(url))videos.set(url,new Promise<void>((resolve,reject)=>{const video=document.createElement('video');video.preload='metadata';let timer:any,settled=false;const done=(error?:Error)=>{if(settled)return;settled=true;video.onloadedmetadata=null;video.onerror=null;clearTimeout(timer);video.removeAttribute('src');video.load();if(error){videos.delete(url);reject(error)}else resolve()};video.onloadedmetadata=()=>done();video.onerror=()=>done(Error('视频元数据载入失败，请重试准备'));timer=setTimeout(()=>done(Error('视频元数据载入超时，请重试准备')),20000);video.src=url}));return videos.get(url)!}
export async function prepareAssets(manifest:any,progress:(stage:string,done:number,total:number)=>void):Promise<PreparedAssets>{
 const source=await loadImage(manifest.image),alpha:Record<string,AlphaMask>={};let completed=0
 progress('载入人物图片',0,manifest.cutouts.length)
 for(let start=0;start<manifest.cutouts.length;start+=4)await Promise.all(manifest.cutouts.slice(start,start+4).map(async(row:any)=>{alpha[row.annotationId]=await mask(row);progress('准备交互',++completed,manifest.cutouts.length)}))
 const urls=[...new Set<string>((manifest.mediaCatalog||[]).map((v:any)=>v.videoUrl).filter(Boolean))]
 for(let i=0;i<urls.length;i+=3)await Promise.all(urls.slice(i,i+3).map(metadata))
 return {width:source.naturalWidth,height:source.naturalHeight,alpha}
}
export function productionToken(project:any){return JSON.stringify(Object.entries<any>(project?.workspace?.entities||{}).filter(([,r])=>r.published!==null).map(([id,r])=>[id,r.revision,r.state==='deleted',r.published]).sort((a,b)=>String(a[0]).localeCompare(String(b[0]))))}
export function reusablePresentation(current:any,candidate:any){return !!current&&current.id===candidate?.id&&current.sessionId===candidate?.sessionId}
