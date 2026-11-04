import copy
import pytest
from backend import main,review_units as ru
from test_review_units import merged_client,ready,edit

def setup(c):
 p,cid=ready(c);w=p['workspace'];w['folders'].append(dict(id='sub',name='子分类',parentId='culture',type='culture',root=False))
 clue=next(r for r in w['entities'].values() if r['kind']=='clue' and r['draft']['type']=='culture')
 return main.save(p,p['version'],'studio:fixture'),clue['id'],cid

def test_tree_clue_move_keeps_facts_and_bindings_and_is_idempotent(merged_client):
 c=merged_client;p,rid,cid=setup(c);before=copy.deepcopy(p['workspace']['entities']['clue:'+rid]['draft']);knowledge=copy.deepcopy(p['workspace']['entities']['knowledge:'+cid]);path='/workspace/entities/clue:'+rid+'/draft/parentId'
 response=edit(c,p,path,'sub',rid='move');assert response.status_code==200,response.text
 result=main.get(p['id']);after=result['workspace']['entities']['clue:'+rid]['draft'];assert {k:v for k,v in before.items() if k!='parentId'}=={k:v for k,v in after.items() if k!='parentId'}
 assert result['workspace']['entities']['knowledge:'+cid]['draft']==knowledge['draft']
 assert edit(c,p,path,'sub',rid='move').status_code==200

def test_bad_moves_reject_without_partial_writes_and_conflicts_preserve_remote(merged_client):
 c=merged_client;p,rid,_=setup(c);path='/workspace/entities/clue:'+rid+'/draft/parentId'
 for target in ('relationship','nonexistent'):
  response=edit(c,p,path,target,rid=target);assert response.status_code==422,response.text
 assert main.get(p['id'])['version']==p['version']
 assert edit(c,p,path,'sub',rid='ok').status_code==200
 response=edit(c,p,path,'culture',before='other',rid='conflict');assert response.status_code==409
 assert main.get(p['id'])['workspace']['entities']['clue:'+rid]['draft']['parentId']=='sub'

def test_folder_cycles_and_cross_root_moves_reject_atomically(merged_client):
 c=merged_client;p,_,_=setup(c);folders=copy.deepcopy(p['workspace']['folders']);folders.append(dict(id='deep',name='更深',parentId='sub',type='culture',root=False))
 for target in ('deep','relationship'):
  invalid=copy.deepcopy(folders);next(f for f in invalid if f['id']=='sub')['parentId']=target
  r=c.put(f"/api/projects/{p['id']}/studio/folders",json=dict(version=p['version'],folders=invalid));assert r.status_code==422,r.text
 assert main.get(p['id'])['workspace']['folders']==p['workspace']['folders']

def test_folder_only_changes_do_not_change_actual_clue_dependencies(merged_client):
 c=merged_client;p,rid,cid=setup(c);uid='character:'+cid;before=ru.dependencies(p,uid);row=p['workspace']['entities']['knowledge:'+cid];row['draft']['clueIds']=[rid]
 before=ru.dependencies(p,uid);legacy=copy.deepcopy(before)
 for key,value in legacy.items():
  if key.startswith('clue:'):value['parentId']='culture'
 assert ru.comparable_basis(legacy)==ru.comparable_basis(before)
 p['workspace']['entities']['clue:'+rid]['draft']['parentId']='sub';assert ru.dependencies(p,uid)==before
