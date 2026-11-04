"""Preview or stage unified material drafts. Never publishes or calls models."""
import argparse
import copy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import main,structured

def run(apply=False,project_id=None):
    with main.db() as conn:ids=[r[0] for r in conn.execute('SELECT id FROM projects')]
    reports=[]
    for pid in ids:
        if project_id and pid!=project_id:continue
        p=main.get(pid);r=p['workspace']['entities']['material:main']
        if r['draft'].get('structured'):continue
        value=structured.preview(p,main.db);structured.validate(value)
        report=dict(projectId=pid,title=p['title'],version=p['version'],counts={k:len(value[k]) for k in ('people','events','relations','statements','research','evidence','missing','conflicts')},applied=apply,publishedContentUnchanged=True)
        if apply:
            before={k:copy.deepcopy(v.get('published')) for k,v in p['workspace']['entities'].items()}
            structured.install_draft(p,value)
            assert before=={k:v.get('published') for k,v in p['workspace']['entities'].items()}
            main.save(p,p['version'],'studio:migrate_unified_draft',report)
        reports.append(report)
    return reports

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');parser.add_argument('--project-id');args=parser.parse_args()
    print(json.dumps(run(args.apply,args.project_id),ensure_ascii=False,indent=2))
