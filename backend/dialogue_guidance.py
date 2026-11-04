"""Deterministic director state; never sends other roles' knowledge to a model."""
from . import persona
from .task_runtime import digest

def initial():return dict(offTopicCount=0,hint=None,recommendations={})

def recommend(p,session,current):
    from .experience import available_people
    state=session.setdefault('guidance',initial());collected=set(session['collectedClueIds']);counts=state['recommendations'];choices=[]
    for cid in sorted({v['characterId'] for v in available_people(p)}):
        role=persona.ready(p,cid)
        for row in role['knowledgeTiming']:
            if not persona.accessible(row,role) or row['clueId'] in collected or not row['question'].strip():continue
            choices.append((cid!=current,counts.get(cid,0),cid,row['clueId'],row))
    if not choices:return None
    _,_,cid,clue_id,row=min(choices,key=lambda c:c[:4])
    figure=next(v for v in available_people(p) if v['characterId']==cid)
    serial=state.get('serial',0)+1;state['serial']=serial;counts[cid]=counts.get(cid,0)+1
    return dict(id=digest([session['id'],serial,cid,clue_id])[:24],characterId=cid,annotationId=figure['annotationId'],name=figure['name'],topic=row['topic'],question=row['question'],clueId=clue_id)

def completed(p,session,turn):
    if session.get('dialogueVersion',1)<2:return
    state=session.setdefault('guidance',initial());config=session['guidanceConfig']
    fresh=set(turn.get('clueIds',[]))-set(session['collectedClueIds'])
    if fresh:state.update(offTopicCount=0,hint=None)
    else:state['offTopicCount']+=1
    if config['enabled'] and state['offTopicCount']>=config['offTopicThreshold'] and not state['hint']:
        state['hint']=recommend(p,session,turn['characterId'])

def reset(session):
    state=session.setdefault('guidance',initial());state.update(offTopicCount=0,hint=None)
