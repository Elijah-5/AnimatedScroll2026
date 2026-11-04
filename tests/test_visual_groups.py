import copy
from backend import main,review_units as ru
from test_review_units import merged_client,ready,units,confirm,edit

def grouped(c):
 p,cid=ready(c);r=p['workspace']['entities']['character:'+cid];r['draft']['roleType']='group';r['published']['roleType']='group'
 # Deliberately different observations must never be merged into one invented observation.
 mat=p['workspace']['entities']['material:main'];mat['draft']['annotations'][0]['description']='第一位穿绿衣';mat['draft']['annotations'][1]['description']='第二位穿红衣'
 mat['published']=copy.deepcopy(mat['draft']);p['annotations']=copy.deepcopy(mat['draft']['annotations'])
 p=main.save(p,p['version'],'studio:fixture');return p,cid

def test_group_is_one_unit_and_one_confirmation_reviews_every_figure(merged_client):
 c=merged_client;p,cid=grouped(c);uid='visual-group:'+cid;report=units(c,p)
 assert uid in report['units'] and not any(k.startswith('visual:') for k in report['units'])
 assert uid in next(row for row in report['pages'] if row['id']=='library')['unitIds']
 original=copy.deepcopy(p['annotations']);v=p['version'];response=confirm(c,p,uid);assert response.status_code==200,response.text
 p=response.json();assert p['version']==v+1 and units(c,p)['units'][uid]['status']=='human'
 assert main.get(p['id'])['annotations']==original
 for a in original:assert p['workspace']['reviewUnits']['members']['visual:'+a['id']]['reviewedHash']==ru.fingerprint(a)
 assert confirm(c,p,uid).json()['version']==p['version']
 assert units(c,p)['units']['character:'+cid]['status']!='human'

def test_shared_note_and_individual_boxes_are_independent(merged_client):
 c=merged_client;p,cid=grouped(c);a,b=copy.deepcopy(p['annotations']);path='/workspace/entities/material:main/draft/visualGroups/'+cid
 response=edit(c,p,path,dict(description='共用创作备注',kind='creator_note'));assert response.status_code==200,response.text
 p=response.json();response=edit(c,p,'/annotations/@'+a['id']+'/x',.15,rid='position');assert response.status_code==200,response.text
 p=response.json();assert p['annotations'][0]['x']==.15 and p['annotations'][1]==b
 assert [v['description'] for v in p['annotations']]==['第一位穿绿衣','第二位穿红衣']
 assert p['workspace']['entities']['material:main']['published']['visualGroups'][cid]['description']=='共用创作备注'
 p=confirm(c,p,'visual-group:'+cid).json();assert units(c,p)['units']['visual-group:'+cid]['status']=='human'

def test_new_ai_figure_only_reopens_the_shared_group_review(merged_client):
 c=merged_client;p,cid=grouped(c);p=confirm(c,p,'visual-group:'+cid).json();p=main.get(p['id'])
 a=copy.deepcopy(p['annotations'][0]);a.update(id='new-ai-figure',x=.7,description='新识别出的身影')
 p['annotations'].append(a);mat=p['workspace']['entities']['material:main'];mat['draft']['annotations'].append(copy.deepcopy(a));ru.make_available(p);p=main.save(p,p['version'],'studio:generation:painting')
 u=units(c,p)['units']['visual-group:'+cid];assert u['status']=='AI' and 'visual:new-ai-figure' in u['members']
 for old in ('instance-1','instance-2'):assert p['workspace']['reviewUnits']['members']['visual:'+old].get('reviewedHash')

def test_group_membership_change_rejects_a_stale_confirmation_atomically(merged_client):
 c=merged_client;p,cid=grouped(c);uid='visual-group:'+cid;u=units(c,p)['units'][uid]
 response=edit(c,p,'/annotations/@instance-2/characterId','',rid='unlink');assert response.status_code==200,response.text
 response=c.post(f"/api/projects/{p['id']}/studio/units/{uid}/confirm",json=dict(contentHash=u['contentHash'],dependencyHash=u['dependencyHash'],requestId='old-group'))
 assert response.status_code==409 and 'old-group' not in main.get(p['id'])['workspace']['reviewUnits']['receipts']

def test_grouping_existing_ai_figures_does_not_turn_them_into_human(merged_client):
 c=merged_client;p,cid=grouped(c)
 for key,value in ru.members(p,'visual-group:'+cid).items():ru.meta(p)['members'][key]=dict(origin='AI',hash=ru.fingerprint(value))
 other=copy.deepcopy(p);other['workspace']['entities']['character:'+cid]['draft']['roleType']='named'
 ru.changed_members(p,other,'manual')
 assert all(v['origin']=='AI' for key,v in ru.meta(other)['members'].items() if key.startswith('visual:'))
