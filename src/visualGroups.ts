/** Group only explicitly shared group roles, never people who merely share a name. */
export type VisualCard={id:string,characterId:string,grouped:boolean,members:any[]}
export function visualCards(project:any,combine=true):VisualCard[]{
 const roles=new Map(project.characters.map((c:any)=>[c.id,c])),cards:VisualCard[]=[],groups=new Map<string,VisualCard>()
 for(const a of project.annotations.filter((v:any)=>v.kind==='character')){
  const grouped=combine&&(roles.get(a.characterId) as any)?.roleType==='group'
  if(grouped){let card=groups.get(a.characterId);if(!card){card={id:'visual-group:'+a.characterId,characterId:a.characterId,grouped:true,members:[]};groups.set(a.characterId,card);cards.push(card)}card.members.push(a)}
  else cards.push({id:'visual:'+a.id,characterId:a.characterId||'',grouped:false,members:[a]})
 }
 return cards
}
export function selectedFigure(card:VisualCard,selected:string){return card.members.find(a=>a.id===selected)||card.members[0]}
export function figureCardAnchor(cards:VisualCard[],annotationId:string){const card=cards.find(c=>c.members.some(a=>a.id===annotationId));return card?.grouped?'person-group-'+card.characterId:'person-'+annotationId}
