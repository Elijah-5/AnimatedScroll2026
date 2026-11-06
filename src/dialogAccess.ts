import {watch,nextTick,onUnmounted,type Ref} from 'vue'
let locks=0,previousOverflow=''
export function useDialogAccess(open:()=>boolean,element:Ref<HTMLElement|undefined>){
 let previous:HTMLElement|null=null,locked=false
 function release(){if(!locked)return;locked=false;if(--locks===0)document.body.style.overflow=previousOverflow;if(previous?.isConnected)previous.focus()}
 watch(open,async value=>{if(value){previous=document.activeElement as HTMLElement;if(!locks++)previousOverflow=document.body.style.overflow;locked=true;document.body.style.overflow='hidden';await nextTick();(element.value?.querySelector<HTMLElement>('button,input,textarea,select,[tabindex]')||element.value)?.focus()}else release()})
 onUnmounted(release)
 function keyboard(e:KeyboardEvent){if(e.key!=='Tab')return;const nodes=Array.from(element.value?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary,[tabindex="0"]')||[]).filter(el=>el.getClientRects().length>0);const first=nodes[0],last=nodes.at(-1);if(!first){e.preventDefault();return}if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}}
 return keyboard
}
