"""Preview / apply recoverable notice metadata; never changes published wording."""
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend import main,revisions


def run(apply=False):
    with main.db() as c:originals=[json.loads(r[0]) for r in c.execute('SELECT body FROM projects')]
    reports=[]
    for old in originals:
        if old.get('workspace',{}).get('revisionPolicy')==1:continue
        p=main.get(old['id']);restored=[];blocked=[]
        before={k:r.get('published') for k,r in old.get('workspace',{}).get('entities',{}).items()}
        after={k:r.get('published') for k,r in p.get('workspace',{}).get('entities',{}).items()}
        assert before==after,'迁移不能改写确认内容'
        for key,r in p.get('workspace',{}).get('entities',{}).items():
            if r.get('published') is None or r['state']=='deleted':continue
            try:revisions.resolve(p['workspace'],key)
            except ValueError as exc:blocked.append(dict(key=key,reason=str(exc)))
            if old['workspace']['entities'][key]['state'] in ('stale','review') and r['state']=='confirmed':restored.append(key)
        report=dict(projectId=p['id'],title=p['title'],restored=restored,blocked=blocked,publishedContentUnchanged=True,applied=apply)
        if apply:main.save(p,p['version'],'studio:migrate_revision_notices',report)
        reports.append(report)
    return reports


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    print(json.dumps(run(args.apply),ensure_ascii=False,indent=2))
