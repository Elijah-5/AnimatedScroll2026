"""Wan image-to-video jobs with durable IDs and explicit prompt approval."""
import asyncio
import base64
import hashlib
import io
import json
import os
import re
import math
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse
import httpx
from PIL import Image,ImageOps
from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

LIMIT=20
PROMPT_POLICY_VERSION='painting-director-v5'
MEDIA_MODE='reference_images'
STYLE='画风与人物延续是最高优先级：与所附古画保持完全相同的绘画风格，延续其笔触、线条、设色、材质和人物造型，不真人化、不3D化、不改成现代卡通。优先使用画作中已有的人物，保持每位人物的面貌、发式、衣冠、服饰纹样及身份特征；人物姓名仅用于识别，不能凭姓名重新设计人物或生成替身。'
# Legacy snapshot defaults only. New submissions require an explicitly
# registered adapter; video_generation.ADAPTERS is intentionally empty.
VIDEO_MODEL='wan3.0-video'
VIDEO_PARAMETERS=dict(resolution='480P',ratio='adaptive',duration=5,audio=True,prompt_extend=False,seed=20261026)

from . import consumption as consume, video_generation as generation, video_budget as allowance, video_prompt
from .task_runtime import digest

def model_info():return generation.profile()

def shot_inputs(p, sid, data):
    shot=consume.confirmed(p,'storyboard',sid)
    clue=consume.bound(p,'storyboard',sid,'clue',shot['clueId'])
    mat=consume.confirmed(p,'material','main')
    path=Path(data)/Path(mat.get('image','')).name
    if not mat.get('image','').startswith('/api/images/') or not path.is_file():raise ValueError('已确认的原画文件不存在')
    refs=[dict(label='图1',kind='painting',name='原画画风与场景参考')]
    people=[]
    for cid in shot.get('characterIds',[]):
        person=consume.confirmed(p,'character',cid)
        knowledge=consume.confirmed(p,'knowledge',cid)
        boxes=[a for a in mat.get('annotations',[]) if a.get('characterId')==cid and a.get('identityConfirmed') and not a.get('needsReview')]
        if not boxes:raise ValueError('请先确认出场人物的画中身份对应：'+person['name'])
        from .structured import role_context
        people.append(dict(id=cid,name=person['name'],identity=person.get('identity',''),profile=person,knowledge=knowledge,boxes=boxes,structuredFacts=role_context(p,cid)))
        # Prefer the instance closest to the selected storyboard region.
        region=shot.get('region') or dict(x=0,y=0,w=1,h=1)
        a=min(boxes,key=lambda b:abs(b['x']+b['w']/2-region['x']-region['w']/2)+abs(b['y']+b['h']/2-region['y']-region['h']/2))
        if not all(isinstance(a.get(k),(int,float)) and math.isfinite(a[k]) for k in ('x','y','w','h')) or min(a['x'],a['y'])<0 or min(a['w'],a['h'])<=0 or a['x']+a['w']>1.000001 or a['y']+a['h']>1.000001:raise ValueError('人物参考框范围无效')
        refs.append(dict(label='图'+str(len(refs)+1),kind='character',characterId=cid,name=person['name'],box={k:a[k] for k in ('x','y','w','h')}))
    if len(refs)>10:raise ValueError('本模型最多接收原画和9个人物参考，请减少本镜出场人物')
    image_hash=hashlib.sha256(path.read_bytes()).hexdigest()
    # Approval identity includes exactly the provider body, not authoring metadata.
    config=generation.request_config()
    body=payload(dict(prompt='',referencePlan=refs,requestConfig=config),path)
    inputs=dict(shot=shot,clue=clue,people=people,references=refs,imageSha256=image_hash)
    inputs['scopeFingerprint']=digest(body)
    inputs['directorFingerprint']=digest(compile_prompt(inputs))
    return inputs,path


def compile_prompt(inputs):
    return video_prompt.compile(inputs,model_info()['duration'],STYLE)


def preview(p,sid,data):
    inputs,_=shot_inputs(p,sid,data)
    saved=p['workspace'].get('media',{}).get(sid,{})
    compiled=compile_prompt(inputs)
    return dict(prompt=saved.get('prompt') or compiled,compiledPrompt=compiled,customized=bool(saved.get('prompt')),
                stale=bool(saved.get('prompt')) and saved.get('baseFingerprint')!=inputs['scopeFingerprint'],
                directorChanged=bool(saved.get('directorFingerprint')) and saved['directorFingerprint']!=inputs['directorFingerprint'],
                baseFingerprint=inputs['scopeFingerprint'],references=inputs['references'],model=model_info()['model'],
                parameters=generation.request_config()['parameters'],generation=model_info(),
                audit=video_prompt.audit(inputs,saved.get('prompt') or compiled,model_info()['duration']),
                mediaMode=MEDIA_MODE,approved=saved.get('approval')==approval_hash(inputs,saved.get('prompt','')))


def approval_hash(inputs,text):
    return digest(dict(scope=inputs['scopeFingerprint'],text=text))


def job_current(p,job,data):
    try:
        inputs,_=shot_inputs(p,job['storyboardId'],data)
        saved=p['workspace'].get('media',{}).get(job['storyboardId'],{})
        return (saved.get('baseFingerprint')==inputs['scopeFingerprint'] and
                job.get('requestFingerprint')==approval_hash(inputs,saved.get('prompt','')))
    except (ValueError,KeyError):return False


def job_usable(p,job,data):
    r=p.get('workspace',{}).get('entities',{}).get('storyboard:'+str(job.get('storyboardId','')))
    return bool(r and r['state']!='deleted' and job.get('status')=='succeeded' and not job.get('test') and job.get('reviewStatus')!='needs_revision' and (Path(data)/'videos'/(job['id']+'.mp4')).is_file())


class Version(BaseModel):version:int
class PromptDraft(Version):
    text:str=Field(min_length=1,max_length=19500)
    baseFingerprint:str
class VideoRequest(Version):
    storyboardId:str
    retryOf:str=''
    requestId:str=Field(default='',max_length=100)
class Selection(Version):jobId:str

def endpoint():return os.getenv('DASHSCOPE_VIDEO_BASE_URL','https://cn-beijing.maas.qianwenaiapi.com/api/v1').rstrip('/')
def headers(async_mode=False):
    key=os.getenv('DASHSCOPE_API_KEY','')
    if not key:raise ValueError('未配置 DASHSCOPE_API_KEY')
    result={'Authorization':'Bearer '+key}
    if async_mode:result['X-DashScope-Async']='enable'
    return result

def reserve(data,jobid):
    """Keep submission records without enforcing or resetting a quota."""
    folder=Path(data)/'video-budget';folder.mkdir(exist_ok=True)
    try:
        with (folder/f'{jobid}.ticket').open('x',encoding='utf-8') as f:f.write(jobid)
    except FileExistsError:pass
    return jobid

def remaining(data):return None

def payload(job,path):
    image=ImageOps.exif_transpose(Image.open(path)).convert('RGB')
    if min(image.size)<240 or max(image.size)>8000 or max(image.size)/min(image.size)>8:raise ValueError('古画需每边240–8000像素，长宽比不超过8:1；不会自动裁切原画')
    buf=io.BytesIO();image.save(buf,format='PNG')
    if len(buf.getvalue())>20*1024*1024:raise ValueError('古画图片超过20MB')
    url='data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()
    if job.get('requestConfig'):
        config=job['requestConfig']
        if config.get('mediaMode')=='reference_images':
            media=[]
            for ref in job.get('referencePlan',[dict(kind='painting')]):
                target=image
                if ref['kind']=='character':
                    b=ref['box'];w,h=image.size
                    target=image.crop((round(b['x']*w),round(b['y']*h),round((b['x']+b['w'])*w),round((b['y']+b['h'])*h)))
                    if min(target.size)<=0:raise ValueError('人物参考裁切范围无效')
                    scale=max(1,240/min(target.size));target=target.resize((round(target.width*scale),round(target.height*scale)),Image.Resampling.LANCZOS)
                    if max(target.size)>8000 or max(target.size)/min(target.size)>8:raise ValueError('人物参考裁切过窄，请调整标注范围')
                blob=io.BytesIO();target.save(blob,format='PNG')
                if len(blob.getvalue())>20*1024*1024:raise ValueError('参考图超过20MB')
                media.append(dict(type='reference_image',url='data:image/png;base64,'+base64.b64encode(blob.getvalue()).decode()))
        else:media=[dict(type='first_frame',url=url)]
    elif job.get('promptPolicyVersion')!=PROMPT_POLICY_VERSION:
        # Preserve exact legacy behavior when resuming an old queued job.
        config=dict(model=VIDEO_MODEL,parameters=dict(VIDEO_PARAMETERS));media=[dict(type='first_frame',url=url),dict(type='last_frame',url=url)]
    else:config=dict(model=VIDEO_MODEL,parameters=dict(VIDEO_PARAMETERS));media=[dict(type='first_frame',url=url)]
    return dict(model=config['model'],input=dict(prompt=job['prompt'],media=media),parameters=dict(config['parameters']))


def install(app,get,save,db,data):
    workers=set();inflight=set();creation_lock=asyncio.Lock()
    def store(job):
        with db() as conn:conn.execute('UPDATE video_jobs SET body=? WHERE id=?',(json.dumps(job,ensure_ascii=False),job['id']))
    def read(jid):
        with db() as conn:row=conn.execute('SELECT body FROM video_jobs WHERE id=?',(jid,)).fetchone()
        if not row:raise HTTPException(404,'视频任务不存在')
        return json.loads(row[0])
    async def work_adapter(job):
        adapter=generation.ADAPTERS.get(job['adapter'])
        if not adapter:
            job.update(status='paused',message='原视频通道暂未接入，任务及预留额度保留');store(job);return
        try:
            if not job.get('remoteId'):
                job.update(status='submitting',message='正在提交分镜');store(job)
                body=adapter.build_request(job,Path(data())/'video-inputs'/(job['id']+'.png'))
                remote=await adapter.submit(job,body)
                if not remote:raise ValueError('未返回任务编号，提交状态待核实')
                job.update(remoteId=remote,status='pending',message='已提交，等待生成');store(job)
            result=job.get('providerResult')
            for _ in range(240):
                if not result:
                    try:result=await adapter.inspect(job)
                    except httpx.HTTPError:
                        job.update(status='paused',message='查询暂时失败，可继续查询原任务');store(job);return
                if result['status']=='succeeded':
                    job.update(status='downloading',providerResult=result,message='正在保存视频');store(job)
                    content=await adapter.download(job,result)
                    if not 100<=len(content)<=150*1024*1024:raise ValueError('视频文件大小异常')
                    folder=Path(data())/'videos';folder.mkdir(exist_ok=True)
                    temporary=folder/(job['id']+'.part');temporary.write_bytes(content);temporary.replace(folder/(job['id']+'.mp4'))
                    job.update(status='succeeded',message='视频已保存',videoUrl=f"/api/projects/{job['projectId']}/videos/{job['id']}/file");store(job);return
                if result['status']=='failed':
                    job.update(status='failed',providerFailed=True,message=result.get('message','视频未生成，额度已释放'));store(job);return
                job.update(status='running',message=result.get('message','正在生成分镜'));store(job);result=None
                await asyncio.sleep(15)
            job.update(status='paused',message='等待较久，可继续查询原任务');store(job)
        except Exception as exc:
            known=not job.get('remoteId') and isinstance(exc,httpx.HTTPStatusError) and 400<=exc.response.status_code<500 and exc.response.status_code!=408
            job.update(status='download_failed' if job.get('providerResult') else 'paused' if job.get('remoteId') else 'failed' if known else 'submission_unknown',
                       submissionKnownRejected=known,message='下载未完成，可继续下载原结果' if job.get('providerResult') else '提交被拒绝，未扣额度' if known else '远端状态待核实；保留额度且不会重复提交')
            store(job)
    async def download(job,url):
        parsed=urlparse(url)
        if parsed.scheme!='https' or not (parsed.hostname or '').endswith('.aliyuncs.com'):raise ValueError('视频地址不是受支持的阿里云结果地址')
        folder=Path(data())/'videos';folder.mkdir(exist_ok=True)
        final=folder/(job['id']+'.mp4');partial=final.with_suffix('.part')
        # Never forward the model credential to an object-storage download.
        async with httpx.AsyncClient(timeout=120,follow_redirects=False) as client:
            async with client.stream('GET',url) as response:
                response.raise_for_status();size=0
                with partial.open('wb') as out:
                    async for chunk in response.aiter_bytes():
                        size+=len(chunk)
                        if size>150*1024*1024:raise ValueError('视频下载超过大小限制')
                        out.write(chunk)
        if partial.stat().st_size<100:raise ValueError('视频文件为空')
        partial.replace(final);job['videoUrl']=f"/api/projects/{job['projectId']}/videos/{job['id']}/file"
    async def work(job):
        jid=job['id']
        if jid in inflight:return
        inflight.add(jid)
        try:
            if job.get('adapter'):
                await work_adapter(job);return
            async with httpx.AsyncClient(timeout=90) as client:
                if job.get('status')=='download_failed' and job.get('remoteVideoUrl'):
                    await download(job,job['remoteVideoUrl'])
                    job.update(status='succeeded',message='视频已保存');store(job);return
                if not job.get('remoteId'):
                    job.update(status='submitting',message='正在提交古画与分镜');store(job)
                    body=payload(job,Path(data())/'video-inputs'/(jid+'.png'))
                    try:
                        response=await client.post(endpoint()+'/services/aigc/video-generation/video-synthesis',headers=headers(async_mode=True),json=body)
                        response.raise_for_status();result=response.json()
                    except httpx.TimeoutException:
                        job.update(status='submission_unknown',message='提交响应超时，可能已创建远端任务；不会自动重复提交，请核对服务端记录');store(job);return
                    except httpx.TransportError:
                        job.update(status='submission_unknown',message='提交连接中断，远端状态待核对；不会自动重复提交');store(job);return
                    out=result.get('output',{})
                    if not out.get('task_id'):
                        job.update(status='failed' if result.get('code') else 'submission_unknown',submissionKnownRejected=bool(result.get('code')),message=str(result.get('code','提交状态待核对'))+'：'+str(result.get('message','未返回任务编号'))[:250]);store(job);return
                    job.update(remoteId=out['task_id'],status='pending',message='已提交，等待视频生成');store(job)
                # Bounded polling; a restart resumes this same remote ID, never creates a duplicate.
                for _ in range(240):
                    try:
                        response=await client.get(endpoint()+'/tasks/'+job['remoteId'],headers=headers());response.raise_for_status();result=response.json()
                    except (httpx.TransportError,httpx.HTTPStatusError):
                        job.update(message='查询暂时失败，将继续查询原任务');store(job);await asyncio.sleep(15);continue
                    out=result.get('output',{});state=out.get('task_status','UNKNOWN')
                    if state=='SUCCEEDED':
                        job.update(status='downloading',message='生成完成，正在保存视频',remoteVideoUrl=out.get('video_url',''));store(job)
                        await download(job,job['remoteVideoUrl'])
                        job.update(status='succeeded',message='视频已保存',usage=result.get('usage',{}));store(job);return
                    if state in ('FAILED','CANCELED','UNKNOWN'):
                        job.update(status='failed',message=str(out.get('code',state))+'：'+str(out.get('message','远端任务未成功'))[:300]);store(job);return
                    job.update(status='running' if state=='RUNNING' else 'pending',message='正在生成古画动画' if state=='RUNNING' else '等待视频生成');store(job)
                    await asyncio.sleep(15)
                job.update(status='paused',message='等待时间较长，稍后可继续查询原任务');store(job)
        except Exception as exc:
            if isinstance(exc,httpx.HTTPStatusError):
                try:body=exc.response.json();message=str(body.get('code',exc.response.status_code))+'：'+str(body.get('message','请求失败'))[:250]
                except ValueError:message='视频接口返回 '+str(exc.response.status_code)
            else:message=str(exc)[:300] if isinstance(exc,ValueError) else type(exc).__name__+'：视频处理未完成'
            unknown=isinstance(exc,httpx.HTTPStatusError) and not job.get('remoteId') and (exc.response.status_code>=500 or exc.response.status_code==408)
            rejected=isinstance(exc,httpx.HTTPStatusError) and not job.get('remoteId') and 400<=exc.response.status_code<500 and exc.response.status_code!=408
            job.update(status='submission_unknown' if unknown else 'download_failed' if job.get('remoteVideoUrl') else 'failed',message=message,submissionKnownRejected=rejected);store(job)
        finally:inflight.discard(jid)
    def launch(job):
        task=asyncio.create_task(work(job));workers.add(task);task.add_done_callback(workers.discard)

    def inputs_for(p,sid):
        try:return shot_inputs(p,sid,data())
        except (ValueError,KeyError) as exc:raise HTTPException(422,str(exc)) from exc
    def versioned(pid,version):
        p=get(pid)
        if p['version']!=version:raise HTTPException(409,'项目已变化，当前编辑已保留，请重新载入')
        if p.get('archived'):raise HTTPException(422,'请先恢复项目')
        return p
    def media(p,sid):return p['workspace'].setdefault('media',{}).setdefault(sid,{})
    def owned(pid,jid):
        job=read(jid)
        if job['projectId']!=pid:raise HTTPException(404,'视频不存在')
        return job
    def list_jobs(pid):
        p=get(pid)
        with db() as c:jobs=[json.loads(r[0]) for r in c.execute('SELECT body FROM video_jobs WHERE project=?',(pid,))]
        for job in jobs:
            job['matchesCurrentScript']=job_current(p,job,data())
            job['availableForExperience']=job_usable(p,job,data())
            job['versionNotice']='' if job['matchesCurrentScript'] else '基于旧版本的视频，仍可播放或选择'
            job['selectedForExperience']=p['workspace'].get('media',{}).get(job.get('storyboardId',''),{}).get('selectedJobId')==job['id']
            job.pop('remoteVideoUrl',None)
        return sorted(jobs,key=lambda j:j['time'],reverse=True)

    @app.get('/api/projects/{pid}/storyboards/{sid}/video-prompt')
    def prompt_preview(pid:str,sid:str):
        p=get(pid);inputs_for(p,sid)
        return preview(p,sid,data())

    @app.put('/api/projects/{pid}/storyboards/{sid}/video-prompt')
    def save_prompt(pid:str,sid:str,req:PromptDraft):
        p=versioned(pid,req.version);inputs,_=inputs_for(p,sid)
        if inputs['scopeFingerprint']!=req.baseFingerprint:raise HTTPException(409,'分镜输入已变化，请重新查看提示词')
        if not req.text.strip():raise HTTPException(422,'提示词不能为空')
        media(p,sid).update(prompt=req.text,baseFingerprint=req.baseFingerprint,directorFingerprint=inputs['directorFingerprint'],approval=None)
        return save(p,req.version,'studio:video:prompt',dict(storyboardId=sid))

    @app.post('/api/projects/{pid}/storyboards/{sid}/confirm-video')
    def confirm_video(pid:str,sid:str,req:Version):
        p=versioned(pid,req.version);inputs,_=inputs_for(p,sid);saved=media(p,sid)
        if not saved.get('prompt') or saved.get('baseFingerprint')!=inputs['scopeFingerprint']:raise HTTPException(422,'请先保存当前最终提示词')
        saved['approval']=approval_hash(inputs,saved['prompt'])
        return save(p,req.version,'studio:video:confirm',dict(storyboardId=sid,trigger='user_button'))

    @app.get('/api/projects/{pid}/videos')
    def videos(pid:str):
        with db() as c:budget=allowance.summary(c,pid)
        return dict(jobs=list_jobs(pid),limit=budget['limitCount'],remaining=budget['remainingCount'],budget=budget,generation=model_info())

    @app.post('/api/projects/{pid}/videos')
    async def create(pid:str,req:VideoRequest):
        async with creation_lock:
            p=versioned(pid,req.version);inputs,image=inputs_for(p,req.storyboardId);saved=media(p,req.storyboardId)
            text=saved.get('prompt','');request_hash=approval_hash(inputs,text)
            if not text or saved.get('baseFingerprint')!=inputs['scopeFingerprint'] or saved.get('approval')!=request_hash:raise HTTPException(422,'请先保存并审核当前最终提示词')
            if req.retryOf:
                previous=owned(pid,req.retryOf)
                if not req.requestId or previous['storyboardId']!=req.storyboardId or not job_current(p,previous,data()) or previous['status']!='failed' or not (previous.get('remoteId') or previous.get('submissionKnownRejected')):raise HTTPException(422,'只可明确重试当前分镜已确定失败的任务；提交状态不明时不能重提')
            identity=dict(projectId=pid,storyboardId=req.storyboardId,request=request_hash)
            if req.retryOf:identity.update(retryOf=req.retryOf,requestId=req.requestId)
            jid=digest(identity)[:24]
            with db() as c:row=c.execute('SELECT body FROM video_jobs WHERE id=?',(jid,)).fetchone()
            if row:return json.loads(row[0])
            backend=generation.active();profile=model_info()
            if not backend or not profile['ready']:raise HTTPException(503,'视频模型尚未接入；本次未提交任务，也未扣额度')
            candidate=dict(prompt=text,referencePlan=inputs['references'],requestConfig=generation.request_config())
            try:provider_hash=digest(backend.build_request(candidate,image))
            except ValueError as exc:raise HTTPException(422,str(exc)) from exc
            if not req.retryOf:
                with db() as c:previous_jobs=[json.loads(r[0]) for r in c.execute('SELECT body FROM video_jobs WHERE project=?',(pid,))]
                for previous in previous_jobs:
                    if previous.get('storyboardId')!=req.storyboardId or previous.get('test'):continue
                    historical_hash=previous.get('providerRequestHash')
                    original=Path(data())/'video-inputs'/(previous['id']+'.png')
                    if not historical_hash and original.is_file():
                        try:historical_hash=digest(payload(previous,original))
                        except (ValueError,KeyError,OSError):pass
                    if historical_hash==provider_hash:return previous
                    if not historical_hash and previous.get('status') in ('submitting','submission_unknown') and previous.get('prompt')==text:raise HTTPException(422,'历史提交状态不明且请求依据不完整，请先核对远端记录；未重新提交')
            try:backend.validate_configuration()
            except ValueError as exc:raise HTTPException(422,str(exc)) from exc
            job=dict(id=jid,projectId=pid,storyboardId=req.storyboardId,clueId=inputs['shot']['clueId'],title=inputs['clue']['name'],
                     status='queued',message='准备提交',time=datetime.now(timezone.utc).isoformat(),prompt=text,
                     sourceVersion=p['version'],requestFingerprint=request_hash,scopeFingerprint=inputs['scopeFingerprint'],
                     providerRequestHash=provider_hash,
                     referencePlan=inputs['references'],imageSha256=inputs['imageSha256'],storyboardSnapshot=inputs['shot'],
                     promptPolicyVersion=PROMPT_POLICY_VERSION,model=profile['model'],duration=profile['duration'],resolution=profile['resolution'],
                     adapter=profile['provider'],budgetReservationCny=5,estimatedCny=profile.get('estimatedCny'),
                     requestConfig=generation.request_config())
            if req.retryOf:job['retryOf']=req.retryOf
            try:
                backend.build_request(job,image)
                price=profile.get('estimatedCny')
                if not isinstance(price,(float,int)) or not math.isfinite(price) or not 0<price<=5:raise ValueError('模型报价尚未核实或超过单条 ¥5 额度，请先配置生成通道')
            except ValueError as exc:raise HTTPException(422,str(exc)) from exc
            folder=Path(data())/'video-inputs';folder.mkdir(exist_ok=True)
            with Image.open(image) as im:ImageOps.exif_transpose(im).convert('RGB').save(folder/(jid+'.png'))
            with db() as c:
                c.execute('BEGIN IMMEDIATE');latest=allowance.lock_project(c,pid)
                if latest['version']!=p['version']:raise HTTPException(409,'分镜输入在提交期间已变化，请重新载入；未提交或扣额度')
                duplicate=c.execute('SELECT body FROM video_jobs WHERE id=?',(jid,)).fetchone()
                if duplicate:return json.loads(duplicate[0])
                allowance.require(c,pid)
                c.execute('INSERT INTO video_jobs VALUES (?,?,?)',(jid,pid,json.dumps(job,ensure_ascii=False)))
            launch(job)
            return job

    @app.post('/api/projects/{pid}/videos/{jid}/refresh')
    async def refresh(pid:str,jid:str):
        job=owned(pid,jid)
        if job.get('remoteId') and job['status']!='succeeded':launch(job)
        return job

    @app.post('/api/projects/{pid}/storyboards/{sid}/experience-video')
    def select_video(pid:str,sid:str,req:Selection):
        p=versioned(pid,req.version);job=owned(pid,req.jobId)
        if job['storyboardId']!=sid or not job_usable(p,job,data()):raise HTTPException(422,'请选择本分镜的可用视频')
        if not (Path(data())/'videos'/(job['id']+'.mp4')).is_file():raise HTTPException(422,'视频文件不存在')
        media(p,sid)['selectedJobId']=job['id']
        return save(p,req.version,'studio:video:select',dict(storyboardId=sid,jobId=job['id']))

    @app.get('/api/projects/{pid}/videos/{jid}/file')
    def file(pid:str,jid:str):
        job=owned(pid,jid);path=Path(data())/'videos'/(job['id']+'.mp4')
        if job['status']!='succeeded' or not path.is_file():raise HTTPException(404,'视频文件不存在')
        return FileResponse(path,media_type='video/mp4',filename=job['id']+'.mp4',content_disposition_type='inline')

    async def recover():
        with db() as c:jobs=[json.loads(r[0]) for r in c.execute('SELECT body FROM video_jobs')]
        for job in jobs:
            if job['status'] in ('queued','submitting') and not job.get('remoteId'):
                job.update(status='submission_unknown',message='服务重启，提交状态待核对；不会自动重提');store(job)
            elif job.get('remoteId') and job['status'] in ('pending','running','downloading'):launch(job)
    async def shutdown():
        for task in workers:task.cancel()
        if workers:await asyncio.gather(*workers,return_exceptions=True)
    app.router.add_event_handler('startup',recover)
    app.router.add_event_handler('shutdown',shutdown)
