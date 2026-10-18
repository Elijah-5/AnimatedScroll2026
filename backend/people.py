from .domain import uid

PROFILE_FIELDS=('name','identity','biography','relationships','summary','mentions','namingOrigin','knowledge','evidence')

def profile(c):
    if c.get('namingOrigin')=='creator':return '创作者命名，资料未提供历史身份／经历。'
    if c.get('summary'):return c['summary']
    return '；'.join(filter(None,[c.get('identity'),c.get('biography')])) or '资料中提及；未提供具体身份／经历。'

def invalidate(old,new):
    before={c['id']:c for c in old['characters']}
    changed={c['id'] for c in new['characters'] if c['id'] in before and any(before[c['id']].get(k)!=c.get(k) for k in PROFILE_FIELDS)}
    for c in new['characters']:
        if c['id'] in changed:c['confirmed']=False
    old_boxes={a['id']:a for a in old['annotations']}
    for a in new['annotations']:
        prior=old_boxes.get(a['id'],{})
        if a.get('characterId') in changed or (a['id'] in old_boxes and prior.get('characterId','')!=a.get('characterId','')):
            a['identityConfirmed']=False;a['needsReview']=True
            for m in new.get('matches',[]):
                if m.get('annotationId')==a['id']:m['confirmed']=False;m['stale']=True

def install(app,get,save):
    from fastapi import HTTPException
    from pydantic import BaseModel,Field
    class Confirm(BaseModel):
        version:int
        characterId:str
    class Name(BaseModel):
        version:int
        name:str=Field(min_length=1,max_length=100)
        useExisting:bool=False
    def current(pid,version):
        p=get(pid)
        if p['version']!=version:raise HTTPException(409,'版本已变化，请重新加载后确认')
        return p
    @app.post('/api/projects/{pid}/people/{aid}/confirm')
    def confirm(pid:str,aid:str,req:Confirm):
        p=current(pid,req.version)
        a=next((a for a in p['annotations'] if a['id']==aid),None)
        c=next((c for c in p['characters'] if c['id']==req.characterId),None)
        if not a or not c or a.get('characterId')!=req.characterId:raise HTTPException(422,'请选择有效姓名并保存后确认')
        c['confirmed']=True;a['identityConfirmed']=True;a['needsReview']=False
        for m in p['matches']:
            if m.get('annotationId')==aid:m.update(characterId=c['id'],confirmed=True,stale=False)
        return save(p,req.version,'confirm_person',dict(characterId=c['id'],annotationId=aid,trigger='user_button'))
    @app.post('/api/projects/{pid}/characters/{cid}/confirm')
    def confirm_role(pid:str,cid:str,req:Confirm):
        if req.characterId!=cid:raise HTTPException(422,'人物ID不匹配')
        p=current(pid,req.version);c=next((c for c in p['characters'] if c['id']==cid),None)
        if not c:raise HTTPException(404,'角色不存在')
        c['confirmed']=True
        return save(p,req.version,'confirm_character',dict(characterId=cid,trigger='user_button'))
    @app.post('/api/projects/{pid}/people/{aid}/name')
    def name(pid:str,aid:str,req:Name):
        p=current(pid,req.version);a=next((a for a in p['annotations'] if a['id']==aid),None)
        if not a:raise HTTPException(404,'人物框不存在')
        name=req.name.strip()
        if not name:raise HTTPException(422,'请输入姓名或称谓')
        c=next((c for c in p['characters'] if c['name'].strip()==name),None)
        if c and not req.useExisting:raise HTTPException(409,dict(code='name_exists',message='已有同名角色，是否关联已有角色？',characterId=c['id']))
        if not c:
            c=dict(id=uid(),name=name,identity='',biography='',relationships='',knowledge='',evidence='创作者命名，资料未提供历史身份／经历',summary='创作者命名，资料未提供历史身份／经历。',mentions=[],namingOrigin='creator',confirmed=False)
            p['characters'].append(c)
        a.update(characterId=c['id'],identityConfirmed=False,needsReview=True)
        for m in p['matches']:
            if m.get('annotationId')==aid:m.update(characterId=c['id'],confirmed=False,manual=True,stale=False)
        p['checks']=[];p['outlineConfirmed']=False
        return save(p,req.version,'name_person',dict(characterId=c['id'],annotationId=aid,trigger='user_button'))
