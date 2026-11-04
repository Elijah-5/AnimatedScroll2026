"""Explicit local playback fixtures, outside video jobs and production selection."""
import json
import os
from pathlib import Path
from . import consumption


def fixture(p,data,sid):
    if os.getenv('CREATION_ACCEPTANCE')!='1':return None
    folder=Path(data)/'acceptance-media';manifest=folder/'manifest.json'
    if not manifest.is_file():return None
    rows=json.loads(manifest.read_text())
    item=rows.get(p['id'],{}).get(sid)
    if not item or item.get('fingerprint')!=consumption.snapshot(p):return None
    name=item.get('filename','')
    if not name or Path(name).name!=name or not (folder/name).is_file():return None
    return dict(kind='placeholder',origin='local_fixture',label='本地测试占位视频 · 非模型生成',filename=name,path=folder/name,videoUrl='/api/acceptance-media/'+name)


def install(app,data):
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    @app.get('/api/acceptance-media/{name}')
    def serve(name:str):
        if os.getenv('CREATION_ACCEPTANCE')!='1' or Path(name).name!=name:raise HTTPException(404)
        folder=Path(data())/'acceptance-media';path=folder/name
        if not name.endswith('.mp4') or not path.is_file():raise HTTPException(404)
        return FileResponse(path,media_type='video/mp4')
