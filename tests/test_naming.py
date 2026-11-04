import copy
import pytest
from backend import documents as docs,materials,naming,task_runtime as tr
from test_documents import literature_project,request,output
from backend.domain import reconcile

def extracted(*options,scope='depicted'):
    p=literature_project()
    depiction='《画甲》中可能有一位持卷者。' if scope=='unknown' else '《画甲》画中有一位持卷者。'
    text=depiction+'作者认为此人很可能是礼仪官。另有观点认为可能是使者。'
    p['sources'][0]['text']=text;p['documents'][0]['pages'][0]['text']=text
    o=output(p);person=o['people'][0]
    person.update(name='持卷者',roleType='role',scope=scope,identity='礼仪官（推测）',references=[dict(sourceId='s',quote=depiction)],depictionReferences=[dict(sourceId='s',quote=depiction)],identityOptions=list(options))
    o['claims']=[]
    return p,docs.bind_extracted(o,docs.split_chunks(docs.selected_sources(p,request()))[0],'画甲')

def option(label='礼仪官',assessment='likely',quote='作者认为此人很可能是礼仪官。'):
    return dict(label=label,assessment=assessment,references=[dict(sourceId='s',quote=quote)])

def proposal(p,outputs):
    claims,people=docs.merge_extractions(outputs)
    p['documentAnalysis']=dict(id='analysis',targetArtwork='画甲',request=request(),inputHash=tr.digest(docs.inputs(p,request())),claims=claims,people=people,summaries={k:[] for k in docs.KINDS})
    return people[0]

def test_single_likely_identity_is_adopted_as_creative_name_with_original_evidence():
    p,o=extracted(option());person=proposal(p,[o])
    assert person['name']=='持卷者' and person['creativeNaming']['name']=='礼仪官'
    result=docs.adopt(p,dict(analysisId='analysis',summaryKinds=[],characterIds=[person['id']]))
    c=result['characters'][0]
    assert c['name']==c['identity']=='礼仪官' and c['sourceName']=='持卷者' and not c['confirmed']
    assert c['creativeNaming']['basis']=='literature_interpretation'
    ref=c['creativeNaming']['references'][0];s=next(s for s in result['sources'] if s['id']==ref['sourceId'])
    assert s['text'][ref['start']:ref['end']]==ref['quote'] and '很可能' in ref['quote'] and ref['sourceVersion']==s['version']

def test_competing_explanation_in_another_batch_prevents_creative_rename():
    p,o1=extracted(option());_,o2=extracted(option('使者','possible','另有观点认为可能是使者。'))
    person=proposal(p,[o1,o2])
    assert len(person['identityOptions'])==2 and not person.get('creativeNaming')
    assert '多个' in person['namingNote'] and person['name']=='持卷者'

@pytest.mark.parametrize('scope,role',[('unknown','role'),('background','role'),('depicted','named')])
def test_unknown_presence_background_and_named_people_are_not_renamed(scope,role):
    p,o=extracted(option(),scope=scope);o['people'][0]['roleType']=role
    person=proposal(p,[o]);assert not person.get('creativeNaming')

def test_invalid_identity_quote_is_removed_and_does_not_name_person():
    p,o=extracted(option(quote='原文没有这句话'))
    person=proposal(p,[o]);assert not person.get('creativeNaming') and not person['identityOptions']
    assert o['validationWarnings']

def test_weak_guess_stays_conservative_and_explicitly_rejected_alternative_does_not_compete():
    p,o=extracted(option(assessment='possible'));assert not proposal(p,[o]).get('creativeNaming')
    p,o=extracted(option(),option('使者','rejected','另有观点认为可能是使者。'))
    assert proposal(p,[o])['creativeNaming']['name']=='礼仪官'

def test_adoption_preserves_existing_id_and_clears_old_proposal_when_new_evidence_conflicts():
    p,o=extracted(option());person=proposal(p,[o])
    p['characters']=[dict(id='stable',name='持卷者',identity='旧人工资料',confirmed=True)]
    keep=docs.adopt(p,dict(analysisId='analysis',summaryKinds=[],characterIds=[person['id']]))
    assert keep['characters'][0]['identity']=='旧人工资料'
    adopted=docs.adopt(p,dict(analysisId='analysis',summaryKinds=[],characterIds=[person['id']],updateIds=['stable']))
    assert adopted['characters'][0]['id']=='stable' and adopted['characters'][0]['name']=='礼仪官'
    conflict=copy.deepcopy(o);conflict['people'][0]['identityOptions'].append(option('使者','possible','另有观点认为可能是使者。'))
    conflict=docs.bind_extracted(conflict,docs.split_chunks(docs.selected_sources(p,request()))[0],'画甲')
    person=proposal(p,[conflict]);p['characters']=adopted['characters']
    p['documentAnalysis']['inputHash']=tr.digest(docs.inputs(p,request()))
    result=docs.adopt(p,dict(analysisId='analysis',summaryKinds=[],characterIds=[person['id']],updateIds=['stable']))
    assert result['characters'][0]['id']=='stable' and result['characters'][0]['name']=='持卷者'
    assert not result['characters'][0].get('creativeNaming')

def test_three_input_materials_use_same_naming_and_validate_original_quote():
    p=literature_project();p['materialInputs']['relationships']='画中持卷者很可能是礼仪官。'
    p=reconcile(literature_project(),p)
    person=dict(name='持卷者',identity='礼仪官（推测）',roleType='role',depictionScope='depicted',mentions=[dict(kind='relationships',quote='画中持卷者')],identityOptions=[dict(label='礼仪官',assessment='likely',references=[dict(kind='relationships',quote='持卷者很可能是礼仪官')])])
    parsed=dict(characters=[person],segments=[],eventFramework=[],summary='资料归纳')
    c=materials.bind(p,copy.deepcopy(parsed))['characters'][0]
    assert c['name']=='礼仪官' and c['sourceName']=='持卷者' and c['creativeNaming']['basis']=='literature_interpretation'
    parsed['characters'][0]['identityOptions'][0]['references'][0]['quote']='没有的身份判断'
    with pytest.raises(ValueError,match='身份解释'):materials.bind(p,parsed)
