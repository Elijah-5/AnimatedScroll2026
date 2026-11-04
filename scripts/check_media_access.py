"""Read-only provider diagnostics; never creates a media generation task."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import config,media_previews
import httpx


async def main():
    async with httpx.AsyncClient(timeout=30) as client:
        result=await client.get('https://aihubmix.com/api/v1/models',params={'schema_checked':'true','sort_by':'order'})
        rows=result.json().get('data',[])
        print('catalog',len(rows),'types',sorted({r.get('types','') for r in rows}))
        result=await client.get('https://aihubmix.com/ai/v1/videos',params={'limit':1},headers=media_previews.headers())
        print('account_video_read',result.status_code)
    for kind in ('video','image'):
        try:print(kind,json.dumps(await media_previews.pricing(kind),ensure_ascii=False))
        except Exception as exc:print(kind,type(exc).__name__,str(exc)[:200])

asyncio.run(main())
