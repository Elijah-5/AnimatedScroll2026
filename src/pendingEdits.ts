const dbName='animatedscroll-edits'
async function database(){return new Promise<IDBDatabase>((resolve,reject)=>{const r=indexedDB.open(dbName,1);r.onupgradeneeded=()=>r.result.createObjectStore('pending');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)})}
async function accessEdits(pid:string,value?:any,remove=false){
 const db=await database()
 try{return await new Promise<any>((resolve,reject)=>{const tx=db.transaction('pending',value===undefined&&!remove?'readonly':'readwrite'),store=tx.objectStore('pending');let result:any;const request=remove?store.delete(pid):value===undefined?store.get(pid):store.put(JSON.parse(JSON.stringify(value)),pid);request.onsuccess=()=>result=request.result;tx.oncomplete=()=>resolve(result);tx.onerror=()=>reject(tx.error)})}finally{db.close()}
}

const operations=new Map<string,Promise<any>>()
/** Keep writes/deletes in call order even if IndexedDB opens resolve out of order. */
export function pendingEdits(pid:string,value?:any,remove=false){
 const next=(operations.get(pid)||Promise.resolve()).catch(()=>{}).then(()=>accessEdits(pid,value,remove))
 operations.set(pid,next);void next.finally(()=>{if(operations.get(pid)===next)operations.delete(pid)}).catch(()=>{})
 return next
}
