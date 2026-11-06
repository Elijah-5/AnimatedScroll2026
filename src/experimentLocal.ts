const NAME='animatedscroll-experiments'
let opening:Promise<IDBDatabase>|undefined
function database(){return opening||=(new Promise<IDBDatabase>((resolve,reject)=>{const request=indexedDB.open(NAME,1);request.onupgradeneeded=()=>{request.result.createObjectStore('events',{keyPath:'id'});request.result.createObjectStore('drafts')};request.onsuccess=()=>resolve(request.result);request.onerror=()=>{opening=undefined;reject(request.error)}}))}
export async function localExperiment(storeName:'events'|'drafts',action:'get'|'put'|'delete'|'all',value?:any,key?:string){
 const db=await database();return new Promise<any>((resolve,reject)=>{const tx=db.transaction(storeName,action==='get'||action==='all'?'readonly':'readwrite'),store=tx.objectStore(storeName);let result:any;const plain=action==='put'?JSON.parse(JSON.stringify(value)):undefined;const request=action==='get'?store.get(key!):action==='all'?store.getAll():action==='delete'?store.delete(key!):key?store.put(plain,key):store.put(plain);request.onsuccess=()=>result=request.result;tx.oncomplete=()=>resolve(result);tx.onerror=()=>reject(tx.error)})
}
