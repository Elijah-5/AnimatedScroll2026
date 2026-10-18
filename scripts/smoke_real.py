"""Explicit real-provider smoke test. Creates a separate draft project; does not approve AI output."""
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from backend import agent,main
from backend.domain import uid,validate,citation_errors
from backend.zhekan import sample

async def run():
    p=sample('/api/images/example-zhekan.png');p['title']='折槛图 · 真实模型联调草稿';p['sceneCount']=1
    # These input identities and notes were explicitly provided by the creator.
    # Generated narrative and visual observations remain unreviewed.
    for c in p['characters']:c['confirmed']=True
    for s in p['sources']:s['confirmed']=True
    p=main.save(p,0,'real_smoke_input')
    result=await agent.generate('outline',p,instruction='仅生成1场折槛与劝谏场景，不编写观众交互系统。')
    p['scenes']=result['scenes'];p['outlineConfirmed']=True;p=main.save(p,p['version'],'real_smoke_outline')
    for scene in p['scenes']:
        result=await agent.generate('scene',p,scene['id'],instruction='生成约6个简短叙事单元。区分记录、推测与虚构，保留辛庆忌容纳异议的转折。')
        scene['units']=result['units'];p=main.save(p,p['version'],'real_smoke_scene')
    result=await agent.generate('check',p);p['checks']=result['checks'];p=main.save(p,p['version'],'real_smoke_check')
    package=dict(schemaVersion='1.1',state='draft',issues=validate(p),project=p)
    out=Path('examples/zhekan-real-draft.json');out.write_text(json.dumps(package,ensure_ascii=False,indent=2))
    print('PROJECT',p['id'],flush=True)
    for s in p['scenes']:
        print('SCENE',s['title'],flush=True)
        for u in s['units']:print(u['category'],u['text'],'REFERENCE_ERRORS',citation_errors(u,p),flush=True)
    print('CHECKS',p['checks'],flush=True)
    print('Draft saved:',out,flush=True)

asyncio.run(run())
