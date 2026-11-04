"""Cache official Grounding DINO weights with resumable, validated small HTTP ranges."""
import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import requests
from huggingface_hub import get_hf_file_metadata,hf_hub_download,hf_hub_url
from backend import config,vision


def file_hash(stream):
    digest=hashlib.sha256()
    for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def prepare():
    root=(vision.CACHE/'grounding-dino-tiny').resolve()
    assert root.is_relative_to(config.ROOT.resolve())
    root.mkdir(parents=True,exist_ok=True)
    url=hf_hub_url(vision.MODEL_ID,'model.safetensors')
    meta=get_hf_file_metadata(url,timeout=30)
    expected=meta.etag.strip('"');size=meta.size
    if not size or len(expected)!=64:raise ValueError('官方权重元数据无效，未开始下载')
    target=root/'model.safetensors'
    if target.exists():
        with target.open('rb') as stream:already_valid=file_hash(stream)==expected
        if already_valid:
            print('Official weights already verified',flush=True);return root
    for name in ('config.json','preprocessor_config.json','tokenizer_config.json','tokenizer.json','vocab.txt','special_tokens_map.json','added_tokens.json'):
        import shutil
        source=hf_hub_download(vision.MODEL_ID,name,revision=meta.commit_hash,cache_dir=vision.CACHE)
        shutil.copyfile(source,root/name)
    part=root/'model.safetensors.download';record=root/'download-progress.json'
    block=1024*1024;total=(size+block-1)//block
    state={}
    if record.exists():state=json.loads(record.read_text(encoding='utf-8'))
    done=set(state.get('completed',[])) if part.exists() and state.get('sha256')==expected else set()
    if not done:
        with part.open('wb') as stream:stream.truncate(size)
    sessions=threading.local()
    download_url=meta.location
    def fetch(index):
        if not hasattr(sessions,'http'):sessions.http=requests.Session()
        begin=index*block;end=min(size,begin+block)-1
        for attempt in range(4):
            try:
                with sessions.http.get(download_url,headers={'Range':f'bytes={begin}-{end}'},stream=True,timeout=(20,60)) as response:
                    if response.status_code!=206 or response.headers.get('Content-Range')!=f'bytes {begin}-{end}/{size}':raise ValueError('官方服务器返回的分段范围不匹配')
                    data=b''.join(response.iter_content(65536))
                    if len(data)!=end-begin+1:raise ValueError('权重分段大小不匹配')
                with part.open('r+b') as stream:stream.seek(begin);stream.write(data)
                return index
            except (requests.RequestException,ValueError):
                if attempt==3:raise ValueError('官方权重分段下载失败，进度已保留，可再次运行本脚本')
    print(f'Official model download: {len(done)}/{total} blocks',flush=True)
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures=[pool.submit(fetch,i) for i in range(total) if i not in done]
        for future in as_completed(futures):
            done.add(future.result())
            temp=root/'download-progress.tmp'
            temp.write_text(json.dumps(dict(sha256=expected,completed=sorted(done))),encoding='utf-8');os.replace(temp,record)
            if len(done)%16==0 or len(done)==total:print(f'Official model download: {len(done)}/{total} blocks ({len(done)*100//total}%)',flush=True)
    with part.open('rb') as stream:actual=file_hash(stream)
    if actual!=expected:raise ValueError('模型 SHA256 校验失败，未启用下载文件')
    os.replace(part,target)
    print('Official model SHA256 verified; local cache ready',flush=True)
    return root

if __name__=='__main__':prepare()
