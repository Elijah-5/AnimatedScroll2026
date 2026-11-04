"""Recover confirmed review receipts. Explicit execution; no model or SQL schema migration."""
import argparse,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--apply',action='store_true');args=ap.parse_args()
 from backend import main as app,review_units as ru,workspace as ws
 with app.db() as c:ids=[r[0] for r in c.execute('SELECT id FROM projects')]
 for pid in ids:
  p=app.get(pid);ws.ensure(p)
  if p['workspace'].get('reviewUnits',{}).get('legacyAuditRecovered'):continue
  with app.db() as c:
   rows=c.execute("SELECT action,`after`,meta FROM events WHERE project=? AND (action LIKE 'studio:confirm:%' OR action='studio:batch_confirm' OR action='confirm_person') ORDER BY rowid",(pid,))
   ru.recover_reviews(p,rows)
  report=dict(projectId=pid,proofMembers=len(ru.meta(p)['members']),apply=args.apply)
  if args.apply:app.save(p,p['version'],'studio:recover_review_units')
  print(json.dumps(report,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
