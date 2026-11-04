"""Explicit downloadable working copies; no scheduled/full-database backups."""
import copy
import hashlib
import json
import os
import shutil
import tempfile
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from . import read_models
from .domain import uid
from .models import Project

KIND='animatedscroll-creation-copy'
MAX_BYTES=1024*1024*1024
SUFFIXES={'.png','.jpg','.jpeg','.webp','.pdf','.txt','.md','.mp4'}
_lock=threading.RLock()

def now():return datetime.now(timezone.utc).isoformat()
def digest(raw):return hashlib.sha256(raw).hexdigest()
def dumps(value):return json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
def clean(p):
    p=copy.deepcopy(read_models.clean_project(p));w=p.get('workspace',{})
    for field in ('jobs','batchReceipts'):w.pop(field,None)
    for field in ('generationNotice','reviewNotice','_experienceOldVersion'):p.pop(field,None)
    return p

def asset_names(value):
    names=set()
    def visit(item):
        if isinstance(item,dict):
            for key,v in item.items():
                if key in ('filename','documentFilename','sourceFilename') and isinstance(v,str) and Path(v).name==v and Path(v).suffix.lower() in SUFFIXES:names.add(v)
                visit(v)
        elif isinstance(item,list):
            for v in item:visit(v)
        elif isinstance(item,str) and item.startswith('/api/images/'):
            name=item.removeprefix('/api/images/')
            if Path(name).name==name and Path(name).suffix.lower() in SUFFIXES:names.add(name)
    visit(value);return names

def build(p,root,jobs):
    root=Path(root).resolve();project=clean(p);raw=dumps(project)
    if len(raw)>256*1024*1024:raise HTTPException(422,'项目数据超过副本的256MB限制')
    handle=tempfile.NamedTemporaryFile(prefix='animatedscroll-copy-',suffix='.zip',delete=False);path=Path(handle.name);handle.close()
    try:
        files=[];missing=[];videos=[]
        candidates=[(name,root/name,'asset') for name in sorted(asset_names(project))]
        # Only completed local results are copied. Remote submissions are never replayed on restore.
        for job in jobs:
            if job.get('status')=='succeeded' and not job.get('test'):
                candidates.append(('videos/'+job['id']+'.mp4',root/'videos'/(job['id']+'.mp4'),'video'))
                videos.append(copy.deepcopy(job))
        total=len(raw)
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as z:
            z.writestr('project.json',raw)
            for name,source,kind in candidates:
                if not source.resolve().is_relative_to(root) or not source.is_file():missing.append(dict(name=name,reason='原文件缺失'));continue
                total+=source.stat().st_size
                if total>MAX_BYTES-16*1024*1024:raise HTTPException(422,'素材超过副本的1GB限制，请先单独下载较大的视频')
                payload=source.read_bytes();member='assets/'+name
                z.writestr(member,payload);files.append(dict(name=name,path=member,sha256=digest(payload),size=len(payload),kind=kind))
            videos=[j for j in videos if any(f['name']=='videos/'+j['id']+'.mp4' for f in files)]
            z.writestr('manifest.json',dumps(dict(kind=KIND,schemaVersion=1,createdAt=now(),projectId=p['id'],projectVersion=p['version'],projectSha256=digest(raw),files=files,missingAssets=missing,videos=videos,includesAudienceRecords=False)))
            z.writestr('说明.txt','创作副本包含当前草稿、审核与依据，以及可读取的图片、文献和已完成视频。\n不包含密钥、整库操作日志或观众聊天。\n在工作台“保存副本”中选择“从副本恢复”，将建立独立项目，不覆盖现有项目或体验记录。\n缺失文件见 manifest.json 的 missingAssets；不会伪造缺失素材。\n')
        return path
    except BaseException:path.unlink(missing_ok=True);raise

def parse(path):
    try:
        with zipfile.ZipFile(path) as z:
            entries=z.infolist();names=[i.filename for i in entries]
            if len(names)!=len(set(names)) or sum(i.file_size for i in entries)>MAX_BYTES:raise ValueError('副本包含重复文件或解压后超过1GB')
            for i in entries:
                name=Path(i.filename)
                if name.is_absolute() or '..' in name.parts or '\\' in i.filename:raise ValueError('副本含不安全的文件路径')
            if z.getinfo('manifest.json').file_size>16*1024*1024 or z.getinfo('project.json').file_size>256*1024*1024:raise ValueError('副本清单或项目数据过大')
            m=json.loads(z.read('manifest.json'));raw=z.read('project.json')
            if m.get('kind')!=KIND or m.get('schemaVersion')!=1 or digest(raw)!=m.get('projectSha256'):raise ValueError('不是有效的创作副本，或项目校验失败')
            p=Project.model_validate_json(raw).model_dump();assets=[];seen=set()
            for f in m['files']:
                name=f['name'];relative=Path(name)
                if name in seen or f['path']!='assets/'+name or relative.suffix.lower() not in SUFFIXES or (len(relative.parts)!=1 and not (len(relative.parts)==2 and relative.parts[0]=='videos' and relative.suffix=='.mp4')):raise ValueError('素材清单格式无效')
                seen.add(name);payload=z.read(f['path'])
                if len(payload)!=f['size'] or digest(payload)!=f['sha256']:raise ValueError('素材校验失败：'+name)
                assets.append((f,payload))
            return p,m,assets
    except (ValueError,KeyError,TypeError,RuntimeError,OSError,zipfile.BadZipFile) as exc:raise HTTPException(422,'副本无法恢复：'+str(exc)[:180]) from exc

def install(app,get,save,db,data):
    @app.get('/api/projects/{pid}/creation-copy')
    def download(pid:str,version:int):
        p=get(pid)
        if p['version']!=version:raise HTTPException(409,'内容已更新，请重新点击保存副本')
        with db() as c:jobs=[json.loads(r[0]) for r in c.execute('SELECT body FROM video_jobs WHERE project=?',(pid,))]
        path=build(p,data(),jobs)
        return FileResponse(path,media_type='application/zip',filename='creation-'+pid+'-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'.zip',background=BackgroundTask(path.unlink,missing_ok=True),headers={'Cache-Control':'no-store'})

    @app.post('/api/creation-copies/restore')
    def restore(file:UploadFile):
        # Python 3.10 SpooledTemporaryFile lacks ZipFile's seekable interface.
        if file.size is not None and file.size>MAX_BYTES:raise HTTPException(422,'副本文件超过1GB')
        with tempfile.TemporaryFile() as staged:
            shutil.copyfileobj(file.file,staged);staged.seek(0);p,m,assets=parse(staged)
        root=Path(data()).resolve();mapping={};jobs=[];created=[]
        with _lock:
            try:
                for f,payload in assets:
                    if f.get('kind')=='video':
                        old=Path(f['name']).stem;jid=uid();target=root/'videos'/(jid+'.mp4');mapping[old]=jid
                        original=next((j for j in m.get('videos',[]) if j['id']==old and j.get('status')=='succeeded'),None)
                        if original:jobs.append(dict(original,id=jid,status='succeeded'))
                    else:target=root/('copy-'+f['sha256']+Path(f['name']).suffix.lower());mapping[f['name']]=target.name;mapping['/api/images/'+f['name']]='/api/images/'+target.name
                    target.parent.mkdir(parents=True,exist_ok=True)
                    if target.exists():
                        if digest(target.read_bytes())!=f['sha256']:raise HTTPException(409,'素材文件校验冲突，未覆盖现有文件')
                    else:target.write_bytes(payload);created.append(target)
                def remap(v):
                    if isinstance(v,dict):return {k:remap(x) for k,x in v.items()}
                    if isinstance(v,list):return [remap(x) for x in v]
                    return mapping.get(v,v) if isinstance(v,str) else v
                p=remap(clean(p));p['id']=uid();p['version']=0;p['archived']=False
                p['artworkName']=p.get('artworkName') or p['title']
                p['restoredFromCopy']=dict(createdAt=m['createdAt'],restoredAt=now(),missingAssets=m.get('missingAssets',[]))
                def store_jobs(c,old,project):
                    for job in jobs:
                        job=remap(job);job.update(projectId=project['id'],status='succeeded',remoteTaskId='',message='从手动副本恢复的本地结果')
                        c.execute('INSERT INTO video_jobs VALUES (?,?,?)',(job['id'],project['id'],json.dumps(job,ensure_ascii=False)))
                result=save(p,0,'studio:restore_creation_copy',transaction_hook=store_jobs)
            except BaseException:
                for path in created:path.unlink(missing_ok=True)
                raise
        return dict(projectId=result['id'],title=result['title'],missingAssets=m.get('missingAssets',[]))
