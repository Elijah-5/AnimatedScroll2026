import {domToCanvas} from 'modern-screenshot'
import {captureScrollOffset} from './experimentRuntime'

/** Render only this page locally. No display sharing, upload or browser permissions. */
export async function capturePage():Promise<string>{
 const root=(document.fullscreenElement||document.body) as HTMLElement
 const width=document.documentElement.clientWidth,height=window.innerHeight
 const offset=root===document.body?captureScrollOffset({x:window.scrollX,y:window.scrollY},{x:root.scrollLeft,y:root.scrollTop}):{x:0,y:0}
 const marker='data-page-capture-node',records=new Map<string,{node:HTMLElement;rect:DOMRect;position:string;frame?:string;private:boolean}>()
 const previous=new Map<HTMLElement,string|null>(),videos=new Map<HTMLElement,Array<{node:HTMLVideoElement;frame?:string;index:number}>>()
 const privateSelector='[data-experiment-private],input[type="password"],input[autocomplete="current-password"],input[autocomplete="new-password"]'
 try{
  // Stable metadata also lets us freeze video frames without seeking or recording.
  for(const node of [root,...Array.from(root.querySelectorAll<HTMLElement>('*'))]){
   if(!(node instanceof HTMLElement)||node.closest('[data-screenshot-ignore]'))continue
   const position=getComputedStyle(node).position,isPrivate=!!node.closest(privateSelector),video=node instanceof HTMLVideoElement
   if(!isPrivate&&!video&&!node.matches('input,textarea,select')&&!['fixed','sticky'].includes(position)&&!node.matches('dialog[open]'))continue
   const rect=node.getBoundingClientRect();let frame:string|undefined
   if(video&&node.readyState>=2){try{const c=document.createElement('canvas');c.width=node.videoWidth;c.height=node.videoHeight;c.getContext('2d')!.drawImage(node,0,0);frame=c.toDataURL('image/png')}catch{/* Protected media remains a visible placeholder. */}}
   if(video&&node.parentElement){const rows=videos.get(node.parentElement)||[];rows.push({node,frame,index:Array.from(node.parentElement.children).indexOf(node)});videos.set(node.parentElement,rows)}
   const id=String(records.size);previous.set(node,node.getAttribute(marker));node.setAttribute(marker,id);records.set(id,{node,rect,position,frame,private:isPrivate})
  }
  for(const node of videos.keys()){if(previous.has(node))continue;const id=String(records.size);previous.set(node,node.getAttribute(marker));node.setAttribute(marker,id);records.set(id,{node,rect:node.getBoundingClientRect(),position:getComputedStyle(node).position,private:false})}
  const canvas=await domToCanvas(root,{
   width,height,scale:Math.min(2,window.devicePixelRatio||1),maximumCanvasSize:8192,timeout:7000,font:false,
   backgroundColor:getComputedStyle(document.body).backgroundColor||'#fafbfc',
   features:{restoreScrollPosition:true},
   filter:node=>!(node instanceof HTMLVideoElement)&&!(node instanceof Element&&node.closest('[data-screenshot-ignore]')),
   onCloneEachNode:clone=>{
    if(!(clone instanceof HTMLElement))return
    const entry=records.get(clone.getAttribute(marker)||'')
    if(entry?.node instanceof HTMLTextAreaElement)clone.textContent=entry.node.value
    if(entry?.node instanceof HTMLInputElement&&clone instanceof HTMLInputElement){clone.value=entry.node.value;if(entry.node.checked)clone.setAttribute('checked','');else clone.removeAttribute('checked')}
    if(entry?.node instanceof HTMLSelectElement){const original=entry.node;Array.from(clone.querySelectorAll('option')).forEach((option,index)=>{if(original.options[index]?.selected)option.setAttribute('selected','');else option.removeAttribute('selected')})}
    if(entry)for(const video of videos.get(entry.node)||[]){
     const still=document.createElement(video.frame?'img':'div');const style=getComputedStyle(video.node);for(let i=0;i<style.length;i++){const key=style[i]!;still.style.setProperty(key,style.getPropertyValue(key))}
     if(still instanceof HTMLImageElement){still.src=video.frame!;still.alt='当前视频画面'}else{still.textContent='视频画面暂不可截图';still.style.background='#dfe5da';still.style.color='#52664d'}
     clone.insertBefore(still,clone.children[video.index]||null)
    }
    clone.style.animation='none';clone.style.transition='none';clone.style.caretColor='transparent'
    if(entry?.private){if(clone instanceof HTMLInputElement)clone.value='';clone.removeAttribute('value');clone.textContent='';clone.style.color='transparent';clone.style.backgroundColor='#e5e9e3';clone.style.backgroundImage='none'}
   },
   // Avoid the renderer seeking a fresh video element (which can stall at t=0).
   // Video originals are replaced in the detached clone using placeholders below.
   onCloneNode:clone=>{
    if(!(clone instanceof HTMLElement))return
    clone.style.position='relative';clone.style.margin='0';clone.style.overflow='hidden'
    // The renderer restores body scroll itself; add only scroll owned by <html>.
    const content=document.createElement('div');content.style.cssText=`position:absolute;left:0;top:0;width:${width}px;transform:translate(${-offset.x}px,${-offset.y}px);`
    while(clone.firstChild)content.appendChild(clone.firstChild)
    clone.appendChild(content)
    for(const element of Array.from(content.querySelectorAll<HTMLElement>('['+marker+']'))){
     const entry=records.get(element.getAttribute(marker)||'');if(!entry)continue
     if(['fixed','sticky'].includes(entry.position)||entry.node.matches('dialog[open]')){
      // Keep a space in flow, but place fixed/sticky UI at its visible coordinates.
      const spacer=element.cloneNode(false) as HTMLElement;spacer.removeAttribute(marker);spacer.style.visibility='hidden';spacer.style.width=entry.rect.width+'px';spacer.style.height=entry.rect.height+'px';element.replaceWith(spacer)
      element.style.position='absolute';element.style.inset='auto';element.style.left=entry.rect.left+'px';element.style.top=entry.rect.top+'px';element.style.width=entry.rect.width+'px';element.style.height=entry.rect.height+'px';element.style.margin='0';element.style.transform='none';clone.appendChild(element)
     }
    }
   }
  })
  return canvas.toDataURL('image/png')
 }finally{for(const [node,value] of previous){if(value===null)node.removeAttribute(marker);else node.setAttribute(marker,value)}}
}
