import copy
from backend.project_names import unique_title

def test_duplicate_artwork_names_have_stable_numbered_titles(client):
    a=client.post('/api/projects',json=dict(title='画甲')).json()
    b=client.post('/api/projects',json=dict(title='画甲')).json()
    c=client.post('/api/projects',json=dict(title='画甲')).json()
    assert [p['title'] for p in (a,b,c)]==['画甲','画甲(2)','画甲(3)']
    assert [p['artworkName'] for p in (a,b,c)]==['画甲']*3
    b=client.put('/api/projects/'+b['id'],json=b).json()
    assert b['title']=='画甲(2)'
    assert unique_title('画甲',set(),'画甲(2)')=='画甲(2)'

def test_renaming_only_changes_project_name_and_does_not_overwrite_another_project(client):
    first=client.post('/api/projects',json=dict(title='画甲')).json()
    second=client.post('/api/projects',json=dict(title='画乙')).json()
    original=copy.deepcopy(second['workspace'])
    path='/api/projects/'+second['id']
    renamed=client.patch(path+'/metadata',json=dict(version=second['version'],title='画甲')).json()
    assert renamed['title']=='画甲(2)' and renamed['artworkName']=='画甲'
    assert renamed['workspace']==original
    assert client.get('/api/projects/'+first['id']).json()==first
    same=client.patch(path+'/metadata',json=dict(version=renamed['version'],title='画甲')).json()
    assert same==renamed
    assert client.patch(path+'/metadata',json=dict(version=second['version'],title='画丙')).status_code==409

def test_project_titles_drop_extra_descriptions(client):
    p=client.post('/api/projects',json=dict(title='画甲 · 资料创作示例')).json()
    assert p['title']==p['artworkName']=='画甲'
    p=client.patch('/api/projects/'+p['id']+'/metadata',json=dict(version=p['version'],title='画乙 | 测试')).json()
    assert p['title']==p['artworkName']=='画乙'
