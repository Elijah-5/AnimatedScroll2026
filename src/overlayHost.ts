import {shallowRef,onMounted,onUnmounted} from 'vue'
export function useOverlayHost(){
 const host=shallowRef<Element|string>('body');let observer:MutationObserver
 function update(){const dialogs=Array.from(document.querySelectorAll('dialog[open]'));host.value=dialogs.at(-1)||document.fullscreenElement||'body'}
 onMounted(()=>{update();observer=new MutationObserver(update);observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['open']});document.addEventListener('fullscreenchange',update)})
 onUnmounted(()=>{observer?.disconnect();document.removeEventListener('fullscreenchange',update)})
 return host
}
