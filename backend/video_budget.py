"""Project-local video allowances, reserved atomically before any paid request."""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

DEFAULT_CNY=100
DEFAULT_COUNT=20
SLOT_CNY=5
_attempts={}
_attempt_lock=threading.Lock()


def money(value):
    return float(Decimal(str(value)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))


def schema(c):
    c.execute('CREATE TABLE IF NOT EXISTS video_budget_accounts(id TEXT PRIMARY KEY, project TEXT, body TEXT)')


def lock_project(c,pid):
    # MySQLConnection adds FOR UPDATE in explicit transactions; SQLite uses the
    # same BEGIN IMMEDIATE transaction as the reservation or researcher grant.
    row=c.execute('SELECT body FROM projects WHERE id=?',(pid,)).fetchone()
    if not row:raise HTTPException(404,'项目不存在')
    return json.loads(row[0])


def charge(job,legacy=False):
    if job.get('test') or legacy and job.get('kind')!='video':return 0,0,'free'
    status=job.get('status','')
    rejected=job.get('submissionKnownRejected') or any(code in job.get('message','') for code in ('async_not_enabled','permission_denied','no_available_channel','insufficient_quota'))
    if status=='skipped' or status in ('failed','cancelled') and (rejected or job.get('providerFailed')):return 0,0,'released'
    amount=job.get('budgetReservationCny',job.get('reservedCny') if legacy else SLOT_CNY)
    amount=SLOT_CNY if amount is None else amount
    if status=='succeeded' or (job.get('providerResult') or {}).get('status')=='succeeded' or job.get('remoteVideoUrl'):return money(amount),1,'spent'
    return money(amount),1,'held'


def summary(c,pid):
    schema(c)
    found=c.execute('SELECT body FROM video_budget_accounts WHERE id=?',(pid,)).fetchone()
    account=json.loads(found[0]) if found else dict(limitCny=DEFAULT_CNY,limitCount=DEFAULT_COUNT,grants={})
    spent=held=0;used_count=held_count=0;blocked=False
    for table,legacy in (('video_jobs',False),('media_preview_jobs',True)):
        for body, in c.execute('SELECT body FROM '+table+' WHERE project=?',(pid,)):
            job=json.loads(body);cost,count,state=charge(job,legacy)
            if state=='spent':spent+=cost;used_count+=count
            elif state=='held':held+=cost;held_count+=count
            if count and (job.get('status') in ('submission_unknown','cost_unknown') or job.get('status')=='failed' and not job.get('providerFailed') and not job.get('submissionKnownRejected') and not job.get('remoteId')):blocked=True
    return dict(limitCny=account['limitCny'],limitCount=account['limitCount'],slotCny=SLOT_CNY,
                usedCny=money(spent),reservedCny=money(held),allocatedCny=money(spent+held),
                remainingCny=money(max(0,account['limitCny']-spent-held)),
                usedCount=used_count,reservedCount=held_count,remainingCount=max(0,account['limitCount']-used_count-held_count),
                blocked=blocked,grantCount=len(account.get('grants',{})))


def require(c,pid,count=1,amount=None):
    current=summary(c,pid);amount=SLOT_CNY*count if amount is None else money(amount)
    if current['blocked']:raise HTTPException(409,'本项目有视频提交状态待核实，额度继续预留；请查询原任务')
    if current['remainingCount']<count or current['remainingCny']+.001<amount:raise HTTPException(422,'本项目视频额度不足，请联系实验员增加额度')
    return current


def password_hash(password,salt=None):
    salt=salt or secrets.token_hex(16);rounds=260000
    digest=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),rounds).hex()
    return f'pbkdf2_sha256${rounds}${salt}${digest}'


def verify_password(password):
    encoded=os.getenv('CREATION_RESEARCHER_PASSWORD_HASH','')
    if not encoded:raise HTTPException(503,'实验员密码尚未在服务器配置')
    try:
        algorithm,rounds,salt,expected=encoded.split('$')
        if algorithm!='pbkdf2_sha256' or not 100000<=int(rounds)<=2000000:raise ValueError()
        actual=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),int(rounds)).hex()
        return hmac.compare_digest(actual,expected)
    except (ValueError,TypeError):raise HTTPException(503,'实验员密码配置格式无效')


class Grant(BaseModel):
    password:str=Field(min_length=1,max_length=256,repr=False)
    requestId:str=Field(min_length=1,max_length=100)
    additionalCount:int=Field(ge=1,le=200)


def install(app,get,db):
    @app.get('/api/projects/{pid}/video-budget')
    def get_budget(pid:str):
        get(pid)
        from .video import model_info
        with db() as c:result=summary(c,pid)
        return dict(**result,model=model_info())

    @app.post('/api/projects/{pid}/video-budget/grants')
    def grant(pid:str,req:Grant,request:Request):
        get(pid)
        identity=request.client.host if request.client else 'local'
        now=time.monotonic()
        with _attempt_lock:
            recent=[t for t in _attempts.get(identity,[]) if now-t<300]
            if len(recent)>=5:raise HTTPException(429,'尝试次数过多，请五分钟后再试')
            _attempts[identity]=recent+[now]
        if not verify_password(req.password):raise HTTPException(403,'实验员密码不正确')
        with _attempt_lock:_attempts.pop(identity,None)
        with db() as c:
            c.execute('BEGIN IMMEDIATE');lock_project(c,pid);schema(c)
            found=c.execute('SELECT body FROM video_budget_accounts WHERE id=?',(pid,)).fetchone()
            account=json.loads(found[0]) if found else dict(limitCny=DEFAULT_CNY,limitCount=DEFAULT_COUNT,grants={})
            old=account['grants'].get(req.requestId)
            if old and old['additionalCount']!=req.additionalCount:raise HTTPException(409,'同一请求编号不能用于不同的额度调整')
            if not old:
                account['limitCount']+=req.additionalCount;account['limitCny']+=req.additionalCount*SLOT_CNY
                account['grants'][req.requestId]=dict(additionalCount=req.additionalCount,additionalCny=req.additionalCount*SLOT_CNY,time=time.time())
                if found:c.execute('UPDATE video_budget_accounts SET body=? WHERE id=?',(json.dumps(account),pid))
                else:c.execute('INSERT INTO video_budget_accounts VALUES (?,?,?)',(pid,pid,json.dumps(account)))
            return summary(c,pid)
