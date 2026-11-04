"""Appreciation derives presentation assets from the session's confirmed snapshot."""
import copy
import io
from PIL import Image, ImageDraw
from backend import main, cutouts, experience
from test_merged_features import ready, session
from test_studio import draft, confirm


def test_portrait_prefers_confirmed_manual_face_then_annotation_then_upper_third(client):
    p,cid=ready(client)
    a=p['workspace']['entities']['material:main']['published']['annotations'][0]
    fallback=experience.available_people(p)[0]['portraitBox']
    assert fallback==dict(x=a['x'],y=a['y'],w=a['w'],h=a['h']/3)
    face=dict(x=.13,y=.12,w=.04,h=.06)
    a['faceRegion']=face
    assert experience.available_people(p)[0]['portraitBox']==face
    r=p['workspace']['entities']['character:'+cid]
    manual=dict(x=.15,y=.13,w=.05,h=.07)
    r['draft']['faceRegion']=manual
    assert experience.available_people(p)[0]['portraitBox']==face
    r['published']['faceRegion']=manual
    assert experience.available_people(p)[0]['portraitBox']==manual
    r['published']['faceRegion']=dict(x=-1,y=0,w=.1,h=.1)
    assert experience.available_people(p)[0]['portraitBox']==face


def test_unbound_figure_can_be_seen_but_cannot_be_sent_a_message(client):
    p,cid=ready(client)
    k=p['workspace']['entities']['knowledge:'+cid]
    k['draft']['clueIds']=[];k['published']['clueIds']=[]
    assert len(experience.painting_people(p))==2
    assert not any(v['canChat'] for v in experience.painting_people(p))
    assert experience.available_people(p)==[]


def test_cutout_cache_is_transparent_local_and_does_not_mutate_creation(client,monkeypatch):
    p,cid=ready(client);v=session(client,p);sid=v['session']['id'];before=main.get(p['id'])
    calls=[]
    def segment(image,box,prompts=None):
        calls.append(box)
        rgba=Image.new('RGBA',(40,80),(0,0,0,0));ImageDraw.Draw(rgba).ellipse((5,0,35,79),fill='#5c6544')
        return rgba
    monkeypatch.setattr(cutouts,'segment',segment)
    base=f"/api/projects/{p['id']}/experience/sessions/{sid}/cutouts"
    response=client.post(base,json={});assert response.status_code==200,response.text
    rows=response.json()['people'];assert len(rows)==2 and len(calls)==2
    assert rows[0]['key']!=rows[1]['key']
    image=client.get(rows[0]['url']);assert image.status_code==200 and image.headers['content-type']=='image/png'
    rgba=Image.open(io.BytesIO(image.content));assert rgba.mode=='RGBA' and rgba.getextrema()[3]==(0,255)
    assert client.post(base,json={}).json()==response.json() and len(calls)==2
    assert main.get(p['id'])==before
    assert client.get(base+'/'+('0'*64)+'.png').status_code==404
    assert client.get(rows[0]['url'].replace(sid,'missing-session')).status_code==404


def test_old_session_keeps_portrait_geometry_and_cutout_identity(client,monkeypatch):
    p,cid=ready(client);v=session(client,p);sid=v['session']['id']
    monkeypatch.setattr(cutouts,'segment',lambda image,box,prompts=None:Image.new('RGBA',(20,30),(0,100,0,120)))
    base=f"/api/projects/{p['id']}/experience/sessions/{sid}"
    rows=client.post(base+'/cutouts',json={}).json()
    material=copy.deepcopy(p['workspace']['entities']['material:main']['draft'])
    material['annotations'][0]['x']+=.03
    p=draft(client,p,'material','main',material);p=confirm(client,p,'material','main').json()
    old=client.get(base).json();new=session(client,p)
    assert old['oldVersion'] and old['figures']==v['figures']
    assert new['figures'][0]['box']!=old['figures'][0]['box']
    assert client.post(base+'/cutouts',json={}).json()==rows
    assert client.get(rows['people'][0]['url']).status_code==200


def test_cutout_failure_is_explicit_and_other_instances_still_work(client,monkeypatch):
    p,_=ready(client);people=experience.painting_people(p)
    def segment(image,box,prompts=None):
        if box['x']<.4:raise ValueError('无法分离人物轮廓')
        return Image.new('RGBA',(20,30),(0,100,0,120))
    monkeypatch.setattr(cutouts,'segment',segment)
    rows=cutouts.prepare(p,people,main.DATA)
    assert rows[0]['error']=='无法分离人物轮廓' and rows[1]['key']
    assert len(experience.available_people(p))==2


def test_box_validation_rejects_nan_bool_and_outside_canvas():
    good=dict(x=.1,y=.2,w=.3,h=.4)
    assert cutouts.valid_box(good)
    for patch in (dict(x=float('nan')),dict(w=True),dict(h=0),dict(x=.9),dict(y=-.1)):
        assert not cutouts.valid_box(dict(good,**patch))


def test_mask_cleanup_keeps_background_transparent_and_fills_clothing_pinholes():
    mask=Image.new('L',(80,120),0);draw=ImageDraw.Draw(mask)
    draw.ellipse((10,8,70,115),fill=255);draw.rectangle((38,48,41,51),fill=0);draw.point((1,1),fill=255)
    clean=cutouts.clean_mask(mask)
    assert clean.getpixel((40,50))==255 and clean.getpixel((0,0))==0 and clean.getpixel((1,1))==0
    assert clean.size==mask.size


def test_nearby_heads_disambiguate_instances_and_are_part_of_cache_identity():
    a=dict(annotationId='a',box=dict(x=.2,y=.1,w=.3,h=.8))
    b=dict(annotationId='b',box=dict(x=.25,y=.15,w=.1,h=.3))
    points,labels=cutouts.point_prompts(a,[a,b])
    assert labels==[1,0] and len(points)==2
    assert cutouts.key_for('hash',a,[a])!=cutouts.key_for('hash',a,[a,b])


def test_shared_group_avatar_does_not_seed_another_instances_edge():
    avatar=dict(x=.1,y=.1,w=.05,h=.1)
    a=dict(annotationId='a',portraitBox=avatar,box=dict(x=.08,y=.08,w=.12,h=.5))
    b=dict(annotationId='b',portraitBox=avatar,box=dict(x=.6,y=.2,w=.2,h=.6))
    points,labels=cutouts.point_prompts(b,[a,b])
    assert labels==[1] and points[0]==(.7,.3)
    assert cutouts.instance_head(a)==avatar
