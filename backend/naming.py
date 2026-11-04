"""Evidence-backed creative role names, separate from historical certainty."""
import copy
from typing import Literal
from pydantic import BaseModel, Field

POLICY_VERSION='single-preferred-identity-1'
INSTRUCTION='''人物name保留原文姓名或可直接定位的画面称谓。另用identityOptions完整列出文献对同一画中人物的身份解释：label为简短身份称谓；assessment为certain（明确身份）、likely（作者较明确的单一主张，即使写“可能/应当/很可能”）、possible（弱猜想或并列竞争解释）、rejected（原文明示否定）。每项必须引用实际讨论此身份的原文，不可仅引服饰描述。不得遗漏并列解释以便强行命名。仅对已经明确在画中的角色，在合并全文后只剩一种较明确解释时，系统可采用该身份作创作称谓。对是否出现在画中尚不确定的背景姓名，不因单一猜测变为画中人物。创作称谓不改变史料的解释/推测性质，也不增补具体姓名或经历。'''

class IdentityOption(BaseModel):
    label:str=Field(min_length=1,max_length=100)
    assessment:Literal['certain','likely','possible','rejected']
    references:list[dict]=Field(min_length=1,max_length=6)

def propose(person,scope_field='scope'):
    """Called only after original-reference binding and cross-batch merging."""
    person.pop('creativeNaming',None)
    person.pop('namingNote',None)
    options=[v for v in person.get('identityOptions',[]) if v.get('references') and v.get('assessment')!='rejected']
    labels={v['label'].strip() for v in options if v['label'].strip()}
    if person.get(scope_field)!='depicted' or person.get('roleType') not in ('role','group'):
        return person
    if len(labels)>1:
        person['namingNote']='文献存在多个身份解释，保留画面称谓。'
        return person
    if len(labels)!=1 or not any(v['assessment'] in ('certain','likely') for v in options):
        person['namingNote']='未提供较明确的单一身份解释，保留画面称谓。'
        return person
    refs=[]
    for option in options:
        for ref in option['references']:
            if ref not in refs:refs.append(copy.deepcopy(ref))
    person['creativeNaming']=dict(name=next(iter(labels)),sourceName=person.get('sourceName') or person['name'],sourceIdentity=person.get('identity',''),basis='document_identity' if all(v['assessment']=='certain' for v in options) else 'literature_interpretation',references=refs,policyVersion=POLICY_VERSION)
    person['namingNote']='采用单一身份解释作为创作称谓；原文及其推测性质保留在依据中。'
    return person

def display_name(person):return (person.get('creativeNaming') or {}).get('name') or person['name']

def same_person(existing,candidate):
    # This is an adoption lookup, not evidence of an historical alias.
    names={candidate['name'],display_name(candidate),candidate.get('sourceName','')}
    names|={a['name'] for a in candidate.get('aliases',[])}
    names.discard('')
    return existing['name'] in names or bool(existing.get('sourceName') and existing['sourceName'] in names)
