// Match Python Unicode code point offsets, including characters outside the BMP.
export function locateQuotation(snapshot:string,quote:string){
  if(!quote)return null
  const offset=snapshot.indexOf(quote)
  if(offset<0)return null
  const start=Array.from(snapshot.slice(0,offset)).length
  return {source_start:start,source_end:start+Array.from(quote).length}
}
