"""Validate classification edits without changing clue facts or knowledge permissions."""
from .workspace import ROOTS

def validate_folders(items,entities,previous=None):
    by={f['id']:f for f in items}
    if len(by)!=len(items):raise ValueError('分类ID重复')
    for root in ROOTS:
        if root not in by or not by[root].get('root') or by[root].get('parentId') or by[root].get('type')!=root or by[root].get('name')!=ROOTS[root]:raise ValueError('不能删除或移动根分类')
    for f in items:
        seen=set();node=f
        while node.get('parentId'):
            if node['id'] in seen:raise ValueError('分类不能循环')
            seen.add(node['id']);node=by[node['parentId']]
            if node['type']!=f['type']:raise ValueError('分类不能跨根嵌套')
        if not node.get('root'):raise ValueError('子分类必须归属于根分类')
    for r in entities.values():
        if r['kind']=='clue' and r['state']!='deleted' and r['draft']['parentId'] not in by:
            if previous is None or any(f['id']==r['draft']['parentId'] for f in previous):raise ValueError('分类仍有线索，先移动线索')

def validate_moves(old,p):
    before=old['workspace'];after=p['workspace'];folders=after['folders']
    if folders!=before['folders']:validate_folders(folders,after['entities'],before['folders'])
    by={f['id']:f for f in folders}
    for key,r in after['entities'].items():
        prior=before['entities'].get(key)
        if r['kind']!='clue' or r['state']=='deleted' or not prior:continue
        d=r['draft'];a=prior['draft']
        if d.get('parentId')==a.get('parentId'):continue
        target=by.get(d.get('parentId'))
        if not target:raise ValueError('目标分类不存在，请重新选择')
        if target['type']!=d['type'] or d['type']!=a['type']:raise ValueError('只能移动到同类分类，不能通过移动改变线索类型')
