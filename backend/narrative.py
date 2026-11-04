"""Portable confirmed-workspace packages, excluding reader state and secrets."""
import copy
import io
import json
import zipfile
from pathlib import Path
from typing import Literal
from fastapi import HTTPException
from fastapi.responses import Response
from . import consumption as consume, workspace as ws, video


def local_file(root,name):
    if not name or '/' in name or '\\' in name or Path(name).name!=name:return None
    root=Path(root).resolve();path=(root/name).resolve()
    return path if path.is_relative_to(root) and path.is_file() else None


def package(p,data,jobs,draft=True):
    issues=[];entities={};skipped=[]
    for key,r in ws.ensure(p)['entities'].items():
        if r['state']=='deleted':continue
        if r['kind'] in ('persona','experience_config') and r['published'] is None:continue
        try:
            entities[key]=consume.confirmed(p,r['kind'],r['id'])
        except ValueError as exc:
            item=dict(entity=key,message=str(exc))
            if r.get('published') is None:skipped.append(item)
            else:issues.append(item)
    mat=entities.get('material:main',{})
    if not mat:issues.append(dict(entity='material:main',message='请确认画作与资料'))
    if not any(k.startswith('storyboard:') for k in entities):issues.append(dict(entity='storyboards',message='尚无有效的已确认分镜'))
    # AI consistency suggestions remain visible, but are not a publishing gate.
    image=local_file(data,Path(mat.get('image','')).name) if mat.get('image','').startswith('/api/images/') else None
    if not image:issues.append(dict(entity='material:main',message='已确认画作文件不存在'))
    if not draft and issues:raise HTTPException(422,dict(message='请先处理制作与确认事项',issues=issues))
    # No project root, unconfirmed drafts, task logs, model configuration, or reader sessions.
    if mat:
        mat.pop('literatureInput',None)  # Input editor buffer is not published narrative content.
        mat['annotations']=[a for a in mat.get('annotations',[]) if a.get('identityConfirmed') and not a.get('needsReview')]
        mat['observations']=[a for a in mat.get('observations',[]) if a.get('confirmed') and not a.get('stale')]
        mat['matches']=[a for a in mat.get('matches',[]) if a.get('confirmed') and not a.get('stale')]
        mat['image']='assets/painting/'+image.name if image else ''
    media=[]
    for key,shot in entities.items():
        if not key.startswith('storyboard:'):continue
        sid=key.split(':',1)[1]
        usable=[j for j in jobs if j.get('storyboardId')==sid and video.job_usable(p,j,data)]
        selected=p['workspace'].get('media',{}).get(sid,{}).get('selectedJobId')
        chosen=next((j for j in usable if j['id']==selected),None) or max(usable,key=lambda j:j['time'],default=None)
        media.append(dict(storyboardId=sid,clueId=shot['clueId'],kind='video' if chosen else 'storyboard',jobId=chosen['id'] if chosen else '',path='assets/videos/'+chosen['id']+'.mp4' if chosen else ''))
        if chosen:media[-1].update(sourceVersion=chosen.get('sourceVersion'),oldVersion=not video.job_current(p,chosen,data))
        if draft and not chosen:
            from .acceptance_media import fixture
            local=fixture(p,data,sid)
            if local:media[-1].update(kind='placeholder',origin='local_fixture',label=local['label'],path='assets/test-media/'+local['filename'])
    from . import revisions
    basis_warnings=[dict(entity=k,**notice) for k,r in p['workspace']['entities'].items() for notice in revisions.warnings(p['workspace'],r)]
    # Only published archival bases, with source edition labels, never audience data.
    basis_versions={k:consume.dependencies(p,*k.split(':',1)) for k in entities}
    for key in entities:
        if not key.startswith('persona:'):continue
        for ref in p['workspace']['entities'][key].get('generationRefs',[]):
            for token,value in revisions.bases(p['workspace'],ref['key'],ref['revision']).items():basis_versions[key].setdefault(token,value)
    from .structured import view,published_payload
    for warning in basis_warnings:
        if warning['key']=='material:main':
            warning['changes']=[c for c in warning['changes'] if c['field']!='literatureInput']
            for change in warning['changes']:
                if change['field']=='structured':
                    for side in ('before','after'):
                        if change.get(side):change[side]=published_payload(change[side])
    structured=published_payload(view(p)) if mat else None
    if mat.get('structured'):mat['structured']=published_payload(mat['structured'])
    for bases in basis_versions.values():
        for basis in bases.values():
            if basis['key']=='material:main':basis['data'].pop('literatureInput',None)
            if basis['key']=='material:main' and basis['data'].get('structured'):basis['data']['structured']=published_payload(basis['data']['structured'])
    from .structured import material_sources
    materials=[mat]+[basis['data'] for bases in basis_versions.values() for basis in bases.values() if basis['key']=='material:main']
    documents={d['id']:d for d in p.get('documents',[])};assets={}
    for material in materials:
        for source in material_sources(material):
            did=source.get('documentId');doc=documents.get(did,{})
            # Text edits create immutable files. Never attach a newer draft file
            # to an older confirmed quote merely because the document ID matches.
            filename=source.get('documentFilename') or doc.get('filename')
            if did and local_file(data,filename):assets[(did,filename)]=dict(id=did,title=source.get('title') or doc.get('title',''),filename=filename)
    docs=list(assets.values())
    return dict(kind='animatedscroll-narrative',schemaVersion='3.4',skippedItems=skipped,structuredMaterial=structured,state='draft' if draft else 'approved',basisWarnings=basis_warnings,basisVersions=basis_versions,
                reviewUnits={k:copy.deepcopy(p['workspace'].get('reviewUnits',{}).get(k,{})) for k in ('policy','members','units')},projectId=p['id'],projectVersion=p['version'],title=p['title'],fingerprint=consume.snapshot(p),entities=entities,
                folders=copy.deepcopy(p['workspace']['folders']),issues=issues,media=media,documents=docs,activationInfo={k:copy.deepcopy(p['workspace']['entities'][k].get('activation',dict(method='legacy_confirmed'))) for k in entities},
                interaction=dict(mode='grounded-live-dialogue',knowledgePolicy='confirmed-character-clues-only',
                                 unlock=[dict(clueId=m['clueId'],storyboardId=m['storyboardId']) for m in media],
                                 dialogueVersion=2,guidanceDefaults=dict(enabled=True,offTopicThreshold=3),offlineModelService=False,readerProgressIncluded=False))


def read_package(bundle):
    """Read older manifests without fabricating published roles or truth labels."""
    if isinstance(bundle,(str,bytes)):bundle=json.loads(bundle)
    if bundle.get('kind')!='animatedscroll-narrative' or bundle.get('schemaVersion') not in ('3.0','3.1','3.2','3.3','3.4'):raise ValueError('不支持的叙事包版本')
    result=copy.deepcopy(bundle)
    result.setdefault('entities',{})
    for field in ('media','documents','folders','issues','basisWarnings'):result.setdefault(field,[])
    result.setdefault('basisVersions',{})
    result.setdefault('interaction',{}).setdefault('dialogueVersion',1 if bundle['schemaVersion'] not in ('3.3','3.4') else 2)
    return result

def markdown(bundle):
    bundle=read_package(bundle)
    lines=['# '+bundle['title'],'','状态：'+bundle['state'],'']
    for key,d in bundle['entities'].items():
        kind=key.split(':')[0]
        if kind=='material':continue
        lines.extend(['## '+(d.get('name') or d.get('title') or key),''])
        for field in ('identity','biography','summary','body','content','prompt','startFrame','endFrame'):
            if d.get(field):lines.append(str(d[field]))
        if kind=='knowledge':lines.append('已确认知识线索：'+', '.join(d.get('clueIds',[])))
        if kind=='persona':
            lines.append('角色设定（口吻与性格属于创作）：'+d.get('temperament',''))
            for row in d.get('knowledgeTiming',[]):lines.append('可知时间：'+row['clueId']+' · '+row['status']+' · '+row.get('reason',''))
        for u in d.get('units',[]):
            lines.append('['+u.get('category','fiction')+'] '+u['text'])
            for ref in u.get('references',[]):lines.append('依据：'+ref.get('quote',''))
        lines.append('')
    lines.extend(['## 资料与出处',''])
    for source in bundle['entities'].get('material:main',{}).get('sources',[]):
        lines.extend(['### '+source['title'],source.get('citation',''),source['text'],''])
    return '\n'.join(lines)


def archive(bundle,data):
    bundle=read_package(bundle)
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json',json.dumps(bundle,ensure_ascii=False,indent=2))
        z.writestr('story.md',markdown(bundle))
        z.writestr('README.md','已确认制作内容和本地素材包。manifest.json包含人物知识绑定与线索解锁关系。\n离线包不提供实时模型服务，也不包含观众聊天、API密钥或项目草稿。\n')
        image_name=Path(bundle['entities'].get('material:main',{}).get('image','')).name
        image=local_file(data,image_name)
        if image:z.write(image,'assets/painting/'+image.name)
        for item in bundle['media']:
            if item['kind']=='video':
                path=local_file(Path(data)/'videos',item['jobId']+'.mp4')
                if path and item['path'] not in z.namelist():z.write(path,item['path'])
            elif item['kind']=='placeholder':
                path=local_file(Path(data)/'acceptance-media',Path(item['path']).name)
                if path and item['path'] not in z.namelist():z.write(path,item['path'])
        for doc in bundle['documents']:
            path=local_file(data,doc['filename'])
            if path:z.write(path,'assets/documents/'+path.name)
    return stream.getvalue()


def install(app,get,save,db,data):
    def make(pid,draft,p=None):
        p=get(pid) if p is None else p
        with db() as c:jobs=[json.loads(r[0]) for r in c.execute('SELECT body FROM video_jobs WHERE project=?',(pid,))]
        return package(p,data(),jobs,draft)
    @app.get('/api/projects/{pid}/narrative/inspect')
    def inspect(pid:str):return make(pid,True)
    @app.get('/api/projects/{pid}/narrative/export')
    def export(pid:str,format:Literal['zip','json','md']='zip',draft:bool=True,reviewed:bool=False,version:int|None=None):
        p=get(pid)
        if version is not None and version!=p['version']:raise HTTPException(409,'项目已变化，请重新检查')
        if not draft and version is None:raise HTTPException(422,'请指定当前项目版本后导出')
        bundle=make(pid,draft,p)
        bundle['exportReview']=dict(manualReviewed=reviewed)
        if not draft and not reviewed:bundle['state']='enabled'
        if format=='zip':body=archive(bundle,data());mime='application/zip'
        elif format=='json':body=json.dumps(bundle,ensure_ascii=False,indent=2);mime='application/json'
        else:body=markdown(bundle);mime='text/markdown; charset=utf-8'
        return Response(body,media_type=mime,headers={'Content-Disposition':f'attachment; filename="narrative-{pid}.{format}"'})
