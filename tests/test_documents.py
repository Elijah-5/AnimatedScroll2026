import asyncio,copy,io,json,threading,time
import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
from fastapi.testclient import TestClient
from backend import documents as docs,main,task_runtime as tr,studio,vision
from backend.domain import blank,reconcile,citation_errors
from test_import import png,wait

def pdf_bytes(text='A painting and its author',encrypted=False,pages=1):
    writer=PdfWriter()
    for _ in range(pages):
        page=writer.add_blank_page(400,500)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        content=DecodedStreamObject();content.set_data(('BT /F1 12 Tf 30 400 Td ('+text+') Tj ET').encode())
        page[NameObject('/Contents')]=writer._add_object(content)
    if encrypted:writer.encrypt('secret')
    output=io.BytesIO();writer.write(output);return output.getvalue()

def literature_project():
    p=blank();p.update(image='/api/images/painting.png',imageVersion=1)
    text='《画甲》画中画家甲与两名侍者相对。文献作者为研究者乙。作者推测丙可能在场。'
    p['documents']=[dict(id='d',title='跨作品研究',filename='d.pdf',format='pdf',parseStatus='ready',parseVersion=docs.PARSE_VERSION,contentHash='file-hash',pageCount=1,pages=[dict(id='d-page-1',page=1,text=text)])]
    p['sources']=[dict(id='s',version=1,text=text,title='PDF第1页',documentId='d',page=1,method='extracted',confirmed=False)]
    return p

def request():return dict(kind='document_analysis',targetArtwork='画甲',documents=[dict(documentId='d',pages=[])])
def output(p):
    ref=lambda q:dict(sourceId='s',quote=q)
    return dict(claims=[dict(kind='background',text='资料描述画中画家与侍者相对。',assertion='description',references=[ref('《画甲》画中画家甲与两名侍者相对。')],indirectSource='')],people=[dict(name='画家甲',scope='depicted',roleType='named',artwork='画甲',contextRoles=['creator','depicted'],summary='本画人物，同时为画家。',identity='画家',biography='',relationships='',references=[ref('《画甲》画中画家甲与两名侍者相对。')],depictionReferences=[ref('《画甲》画中画家甲与两名侍者相对。')],aliases=[],visualHints=[])])

def analysis(p):
    chunks=docs.split_chunks(docs.selected_sources(p,request()));bound=docs.bind_extracted(output(p),chunks[0],'画甲');claims,people=docs.merge_extractions([bound]);summaries=docs.bind_summaries(dict(background=[dict(text='资料描述画中画家与侍者相对。',claimIds=[claims[0]['id']])],relationships=[],narrative=[]),claims)
    return dict(id='analysis',targetArtwork='画甲',request=request(),inputHash=tr.digest(docs.inputs(p,request())),status='pending',claims=claims,people=people,summaries=summaries)

def test_pdfium_native_extraction_and_quality(tmp_path):
    path=tmp_path/'text.pdf';path.write_bytes(pdf_bytes());pages=docs.parse_pdf(path,dict(id='d'))
    assert 'painting' in pages[0]['text'] and pages[0]['engine']=='pdfium'
    assert pages[0]['quality']['state']=='ready'
    assert docs.quality('',2)['state']=='image_page'
    assert docs.quality('')['state']=='blank'
    assert docs.quality('(cid:123)'*30)['state']=='review'

def test_mixed_pdf_keeps_text_image_and_blank_pages_distinct(tmp_path):
    from PIL import Image
    from pypdf import PdfReader
    image=io.BytesIO();Image.new('RGB',(200,200),'gray').save(image,format='PDF')
    writer=PdfWriter()
    writer.add_page(PdfReader(io.BytesIO(pdf_bytes())).pages[0])
    writer.add_page(PdfReader(io.BytesIO(image.getvalue())).pages[0])
    writer.add_blank_page(200,200)
    path=tmp_path/'mixed.pdf'
    with path.open('wb') as output:writer.write(output)
    pages=docs.parse_pdf(path,dict(id='d'))
    assert [p['quality']['state'] for p in pages]==['ready','image_page','blank']
    assert 'painting' in pages[0]['text'] and pages[1]['text']==''

@pytest.mark.parametrize('data',[b'not a pdf',pdf_bytes(encrypted=True)])
def test_bad_or_password_pdf_is_rejected(tmp_path,data):
    path=tmp_path/'bad.pdf';path.write_bytes(data)
    with pytest.raises(ValueError,match='损坏|密码'):docs.parse_pdf(path,dict(id='d'))

def test_page_limit(tmp_path,monkeypatch):
    path=tmp_path/'long.pdf';path.write_bytes(pdf_bytes(pages=2));monkeypatch.setattr(docs,'MAX_PAGES',1)
    with pytest.raises(ValueError,match='300页'):docs.parse_pdf(path,dict(id='d'))

def test_upload_is_async_local_parse_and_never_cloud(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    async def forbidden(*args):raise AssertionError('implicit cloud')
    monkeypatch.setattr(docs,'ask',forbidden)
    with TestClient(main.app) as c:
        p=c.post('/api/projects').json();path='/api/projects/'+p['id']
        response=c.post(path+'/documents?version=1',files={'file':('large.pdf',pdf_bytes()+b'\n%'+b' '* (31*1024*1024),'application/pdf')})
        assert response.status_code==200,response.text
        assert wait(c,p['id'])['status']=='completed'
        p=c.get(path).json();assert p['documents'][0]['parseStatus']=='ready'
        assert p['sources'][0]['confirmed'] is False and 'painting' in p['sources'][0]['text']

def test_upload_limit_preserves_project(client,monkeypatch):
    monkeypatch.setattr(docs,'MAX_BYTES',100)
    p=client.post('/api/projects').json();path='/api/projects/'+p['id']
    response=client.post(path+'/documents?version=1',files={'file':('huge.pdf',pdf_bytes(),'application/pdf')})
    assert response.status_code==413 and client.get(path).json()['version']==1

def test_chunks_cover_every_character_and_bound_exact_spans():
    p=literature_project();text=('段落，关于画作和资料。\n'*1000)+'最后一段。';p['sources'][0]['text']=text
    chunks=docs.split_chunks(docs.selected_sources(p,request()));covered=set()
    for chunk in chunks:
        assert sum(len(f['text']) for f in chunk)<=6000
        for f in chunk:
            assert text[f['start']:f['end']]==f['text'];covered.update(range(f['start'],f['end']))
    assert covered==set(range(len(text)))
    bad=[dict(sourceId='s',quote='不存在的引文')]
    with pytest.raises(ValueError,match='不在'):docs.bind_refs(bad,chunks[0])

def test_pdf_wrapped_quote_is_canonicalized_to_exact_original_span():
    p=literature_project();p['sources'][0]['text']='《画甲》中，画家甲\n与侍者相对。'
    chunk=docs.split_chunks(docs.selected_sources(p,request()))[0]
    ref=docs.bind_refs([dict(sourceId='s',quote='画家甲与侍者相对。')],chunk)[0]
    assert ref['quote']=='画家甲\n与侍者相对。'
    assert p['sources'][0]['text'][ref['start']:ref['end']]==ref['quote']

def test_uncertain_presence_and_other_artwork_do_not_become_depicted():
    p=literature_project();chunk=docs.split_chunks(docs.selected_sources(p,request()))[0];out=output(p)
    uncertain=copy.deepcopy(out['people'][0]);uncertain.update(name='丙',scope='depicted',references=[dict(sourceId='s',quote='作者推测丙可能在场。')],depictionReferences=[dict(sourceId='s',quote='作者推测丙可能在场。')])
    other=copy.deepcopy(out['people'][0]);other.update(artwork='画乙')
    out['people'] += [uncertain,other]
    bound=docs.bind_extracted(out,chunk,'画甲')
    assert [p['scope'] for p in bound['people']]==['depicted','unknown','unknown']
    assert 'creator' in bound['people'][0]['contextRoles']  # A creator can also be depicted.

def test_person_can_reuse_an_explicit_depiction_citation_without_inventing_one():
    p=literature_project();person=output(p)['people'][0];person.pop('references')
    parsed=docs.MentionedPerson.model_validate(person).model_dump()
    assert parsed['references']==parsed['depictionReferences']
    person['depictionReferences']=[]
    with pytest.raises(ValueError):docs.MentionedPerson.model_validate(person)

def test_same_role_titles_in_different_paintings_stay_separate():
    a=dict(name='侍者',scope='depicted',artwork='画甲',references=[],depictionReferences=[],visualHints=[],aliases=[],contextRoles=['depicted'])
    b=dict(a,artwork='画乙',scope='background')
    _,people=docs.merge_extractions([dict(claims=[],people=[a,b])])
    assert len(people)==2

def test_explicit_aliases_and_conflicting_accounts_are_preserved():
    a=dict(name='甲',artwork='画甲',scope='depicted',references=[],depictionReferences=[],visualHints=[],aliases=[],contextRoles=['depicted'],identity='官员',biography='',summary='说法一',relationships='')
    b=copy.deepcopy(a);b.update(scope='unknown',identity='身份未定',summary='说法二')
    _,people=docs.merge_extractions([dict(claims=[],people=[a]),dict(claims=[],people=[b])])
    assert len(people)==1 and len(people[0]['accounts'])==2 and people[0]['scope']=='depicted'
    assert '身份未定' in people[0]['identity']

def test_inference_is_never_existing_historical_narrative():
    p=literature_project();result=analysis(p);claim=result['claims'][0];claim['assertion']='uncertain'
    with pytest.raises(ValueError,match='既有事件'):docs.bind_summaries(dict(background=[],relationships=[],narrative=[dict(text='某人肯定在场',claimIds=[claim['id']])]),[claim])

def test_adoption_only_adds_depicted_and_rebinds_original_page_versions():
    p=literature_project();p['documentAnalysis']=analysis(p);person=p['documentAnalysis']['people'][0]
    p['documentAnalysis']['people'].append(dict(person,id='background',scope='background',name='研究者乙'))
    with pytest.raises(ValueError,match='本画'):docs.adopt(p,dict(analysisId='analysis',summaryKinds=[],characterIds=['background']))
    adopted=docs.adopt(p,dict(analysisId='analysis',summaryKinds=['background'],characterIds=[person['id']]))
    assert [c['name'] for c in adopted['characters']]==['画家甲']
    char=adopted['characters'][0];source=next(s for s in adopted['sources'] if s['id']=='s')
    assert not char['confirmed'] and char['namingOrigin']=='document' and source['confirmed']
    assert char['mentions'][0]['sourceVersion']==source['version']
    assert adopted['materialInputOrigins']['background']['references'][0]['sourceVersion']==source['version']
    derived=next(s for s in adopted['sources'] if s.get('method')=='material_input')
    assert derived['sourceType']=='derived_summary'
    errors=citation_errors(dict(kind='clue',category='supported',text='摘要',references=[dict(sourceId=derived['id'],sourceVersion=derived['version'],quote='资料')]),adopted)
    assert any('PDF原文' in e for e in errors)

def test_adoption_preserves_id_and_requires_explicit_update():
    p=literature_project();p['documentAnalysis']=analysis(p);person=p['documentAnalysis']['people'][0]
    p['characters']=[dict(id='stable',name='画家甲',identity='人工身份',biography='',summary='',relationships='',knowledge='',evidence='',confirmed=True)]
    keep=docs.adopt(p,dict(analysisId='analysis',summaryKinds=[],characterIds=[person['id']]))
    assert keep['characters'][0]['identity']=='人工身份'
    update=docs.adopt(p,dict(analysisId='analysis',summaryKinds=[],characterIds=[person['id']],updateIds=['stable']))
    assert update['characters'][0]['id']=='stable' and update['characters'][0]['identity']=='画家'

def test_changed_document_or_image_prevents_adoption():
    p=literature_project();p['documentAnalysis']=analysis(p);p['sources'][0]['text']+='新内容'
    with pytest.raises(ValueError,match='变化'):docs.adopt(p,dict(analysisId='analysis',summaryKinds=['background'],characterIds=[]))
    p=literature_project();p['documentAnalysis']=analysis(p);p['imageVersion']+=1
    with pytest.raises(ValueError,match='变化'):docs.adopt(p,dict(analysisId='analysis',summaryKinds=[],characterIds=[]))

def test_downstream_receives_cited_spans_not_whole_document():
    p=literature_project();p['documentAnalysis']=analysis(p);person=p['documentAnalysis']['people'][0]
    p=docs.adopt(p,dict(analysisId='analysis',summaryKinds=['background'],characterIds=[person['id']]))
    refs=docs.evidence_refs(p['materialInputOrigins']);context=docs.relevant_sources(p['sources'],refs)
    assert context[0]['id']=='s' and '研究者乙' not in context[0]['text']
    assert not any(s.get('sourceType')=='derived_summary' for s in context)

def test_literal_other_work_reference_cannot_be_labeled_as_target_work():
    p=literature_project();p['sources'][0]['text']='《画乙》画中画家甲与侍者相对。'
    chunk=docs.split_chunks(docs.selected_sources(p,request()))[0];out=output(p)
    out['claims']=[];q=p['sources'][0]['text']
    out['people'][0]['references']=[dict(sourceId='s',quote=q)];out['people'][0]['depictionReferences']=[dict(sourceId='s',quote=q)]
    assert docs.bind_extracted(out,chunk,'画甲')['people'][0]['scope']=='unknown'

def test_role_wording_particles_do_not_erase_a_depicted_person():
    p=literature_project();p['sources'][0]['text']='《画甲》画中可见白衣的官员。'
    chunk=docs.split_chunks(docs.selected_sources(p,request()))[0];out=output(p);q=p['sources'][0]['text']
    out['claims']=[];person=out['people'][0];person.update(name='白衣官员',roleType='role',references=[dict(sourceId='s',quote=q)],depictionReferences=[dict(sourceId='s',quote=q)])
    assert docs.bind_extracted(out,chunk,'画甲')['people'][0]['scope']=='depicted'

def test_rejected_citation_drops_only_its_item_and_never_becomes_evidence():
    p=literature_project();chunk=docs.split_chunks(docs.selected_sources(p,request()))[0];out=output(p)
    out['claims'].append(dict(kind='background',text='不可靠信息',assertion='description',references=[dict(sourceId='s',quote='捏造的文字')]))
    result=docs.bind_extracted(out,chunk,'画甲')
    assert len(result['claims'])==1 and result['validationWarnings']
    assert all(r['quote'] in p['sources'][0]['text'] for c in result['claims'] for r in c['references'])

def test_model_section_mixup_is_conservatively_background():
    claim=docs.Claim.model_validate(dict(kind='interpretation',assertion='interpretation',text='作者观点',references=[dict(sourceId='s',quote='原文')]))
    assert claim.kind=='background' and claim.assertion=='interpretation'

def test_summary_short_identifiers_map_back_to_stable_claims(monkeypatch):
    p=literature_project();cache={}
    async def fake(schema,payload,stats,validator=None):
        if schema is docs.Extracted:value=output(p)
        elif schema is docs.Topics:value=dict(assignments=[dict(claimId='C1',topic='culture')])
        else:
            assert payload['claims'][0]['id']=='C1'
            value=dict(paragraphs=[dict(text='资料描述画中画家与侍者相对。',claimIds=['c01'])])
        return validator(value) if validator else value
    monkeypatch.setattr(docs,'ask',fake)
    result=asyncio.run(docs.organize(p,request(),cache.get,lambda k,v:cache.__setitem__(k,v),lambda *a:None,{}))
    para=result['summaries']['background'][0]
    assert para['claimIds']==[result['claims'][0]['id']] and para['references'][0]['quote'] in p['sources'][0]['text']

def test_visual_request_counter_counts_provider_calls_not_polls(monkeypatch):
    from types import SimpleNamespace as NS
    from PIL import Image
    calls=[];count=[]
    async def create(**kwargs):
        calls.append(1);return NS(model='test',choices=[NS(finish_reason='stop',message=NS(content='{"ok":true}',refusal=None))],usage=None)
    class FakeClient:
        def __init__(self,**kwargs):self.chat=NS(completions=NS(create=create))
        async def close(self):pass
    monkeypatch.setattr(vision,'AsyncOpenAI',FakeClient);monkeypatch.setenv('AIHUBMIX_API_KEY','test-not-a-real-key')
    token=tr.model_request.set(lambda:count.append(1))
    try:assert asyncio.run(vision.ask('test',[Image.new('RGB',(20,20),'white')]))['ok']
    finally:tr.model_request.reset(token)
    assert len(calls)==len(count)==1

def test_document_selection_payload_requires_document_id():
    from backend.pipeline import TaskRequest
    with pytest.raises(ValueError):TaskRequest.model_validate(dict(version=1,kind='document_analysis',targetArtwork='画甲',documents=[{}]))

def test_artwork_history_is_not_reassembled_into_the_depicted_story(monkeypatch):
    p=literature_project();p['sources'][0]['text']+='后世此画被重新装裱。';cache={}
    async def fake(schema,payload,stats,validator=None):
        if schema is docs.Extracted:
            value=output(p);value['claims'][0].update(kind='narrative',assertion='historical_account')
            value['claims'].append(dict(kind='narrative',text='作品后来重裱。',assertion='historical_account',references=[dict(sourceId='s',quote='后世此画被重新装裱。')],indirectSource=''))
        elif schema is docs.Topics:value=dict(assignments=[dict(claimId='C1',topic='story'),dict(claimId='C2',topic='artwork_history')])
        else:
            assert len(payload['claims'])==1
            value=dict(paragraphs=[dict(text='画中人物相对。',claimIds=['C1'])])
        return validator(value) if validator else value
    monkeypatch.setattr(docs,'ask',fake)
    result=asyncio.run(docs.organize(p,request(),cache.get,lambda k,v:cache.__setitem__(k,v),lambda *a:None,{}))
    assert result['claims'][1]['topic']=='artwork_history' and result['claims'][1]['kind']=='background'
    assert '重裱' not in result['summaries']['narrative'][0]['text']

def test_generated_book_volume_must_exist_in_supplied_material():
    sources=[dict(text='论文转引《古籍甲》卷十二。')]
    value,warnings=docs.clean_book_locators('据《古籍甲》卷九十九记载。',sources)
    assert '卷九十九' not in value and '待核对' in value and warnings
    value,warnings=docs.clean_book_locators('据《古籍甲》卷十二记载。',sources)
    assert '卷十二' in value and not warnings

def test_automatic_hints_are_not_unconfirmed_hard_constraints():
    chars=[dict(id='group')];sources=[dict(id='s',version=1,text='画中有一群侍者。')]
    hints={'h':dict(id='h',characterId='group',strength='required',quote='手中持物')}
    raw=dict(characterId='group',confidence='high',supports=[dict(sourceId='s',sourceVersion=1,quote='一群侍者')],constraintChecks=[dict(hintId='h',result='unknown')])
    assert vision.normalize_match(raw,dict(id='a'),chars,sources,hints)['characterId']=='group'
    hints['h']['constraintConfirmed']=True
    assert vision.normalize_match(raw,dict(id='a'),chars,sources,hints)['characterId']==''
    hints['h']['constraintConfirmed']=False;raw['constraintChecks'][0]['result']='conflicts'
    assert vision.normalize_match(raw,dict(id='a'),chars,sources,hints)['characterId']==''

def test_valid_positive_hint_check_is_evidence_even_if_supports_list_is_omitted():
    hint=dict(id='h',characterId='c',sourceId='s',sourceVersion=1,quote='画中侍者着长衣。',strength='suggested')
    raw=dict(characterId='c',confidence='high',constraintChecks=[dict(hintId='h',result='supports')])
    result=vision.normalize_match(raw,dict(id='a'),[dict(id='c')],[],{'h':hint})
    assert result['characterId']=='c' and result['supports'][0]['quote']==hint['quote']

def test_matching_short_tokens_use_stable_ids_and_validated_hint(tmp_path,monkeypatch):
    from PIL import Image
    path=tmp_path/'painting.png';Image.new('RGB',(120,120),'gray').save(path)
    p=literature_project();p['annotations']=[dict(id='stable-box',kind='character',x=.1,y=.1,w=.3,h=.6)]
    quote='《画甲》画中画家甲与两名侍者相对。'
    p['characters']=[dict(id='stable-character',name='画家甲',depictionScope='depicted',mentions=[dict(sourceId='s',sourceVersion=1,quote=quote)],visualHints=[dict(id='hint',sourceId='s',sourceVersion=1,quote=quote)])]
    async def fake(*args):
        return dict(matches=[dict(annotationId='P1',characterId='C1',confidence='high',supports=[dict(hintId='hint')])])
    monkeypatch.setattr(vision,'ask',fake)
    matches=asyncio.run(vision.match_people(path,p))
    assert matches[0]['annotationId']=='stable-box' and matches[0]['characterId']=='stable-character'
    assert matches[0]['supports'][0]['quote']==quote

def test_document_analysis_task_merges_rename_and_never_auto_adopts(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path);started=threading.Event();release=threading.Event()
    async def fake(p,req,*args):
        started.set()
        while not release.is_set():await asyncio.sleep(.005)
        return analysis(p)
    monkeypatch.setattr(docs,'organize',fake)
    with TestClient(main.app) as c:
        p=literature_project();main.save(p,0,'test_setup');path='/api/projects/'+p['id'];p=c.get(path).json()
        result=c.post(path+'/tasks',json=dict(version=p['version'],**request()));assert result.status_code==200,result.text
        assert started.wait(2)
        rename=c.patch(path+'/metadata',json=dict(version=p['version'],title='后台整理时改名'));assert rename.status_code==200
        release.set();assert wait(c,p['id'])['status']=='completed'
        p=c.get(path).json();assert p['title']=='后台整理时改名' and p['documentAnalysis']
        assert not p['characters'] and not p['materialInputs']['background']

def test_document_page_change_stops_next_cloud_batch(monkeypatch):
    p=literature_project();p['sources'][0]['text']*=180;calls=[];stale=[False]
    async def fake(schema,payload,stats,validator=None):
        calls.append(1);stale[0]=True;return dict(claims=[],people=[])
    def check():
        if stale[0]:raise tr.StaleTask('文献已变化')
    monkeypatch.setattr(docs,'ask',fake);token=tr.checkpoint.set(check)
    try:
        with pytest.raises(tr.StaleTask):asyncio.run(docs.organize(p,request(),lambda k:None,lambda *a:None,lambda *a:None,{}))
    finally:tr.checkpoint.reset(token)
    assert len(calls)==1

def test_failed_batch_retry_reuses_only_identical_completed_work(monkeypatch):
    p=literature_project();p['sources'][0]['text']*=250;calls=[];cache={};fail=[True]
    async def provider(schema,payload,stats,validator=None):
        calls.append(payload)
        if schema is docs.Extracted:
            if len(calls)==2 and fail[0]:raise ValueError('provider failed')
            return dict(claims=[],people=[])
        return dict(background=[],relationships=[],narrative=[])
    monkeypatch.setattr(docs,'ask',provider)
    go=lambda:asyncio.run(docs.organize(p,request(),cache.get,lambda k,v:cache.__setitem__(k,v),lambda *a:None,{}))
    with pytest.raises(ValueError,match='provider'):go()
    first=calls[0];fail[0]=False;calls.clear();go()
    assert first not in calls  # First successful batch was cached.
    cache_keys=set(cache);p['sources'][0]['text']+='修改';go();assert set(cache)!=cache_keys
