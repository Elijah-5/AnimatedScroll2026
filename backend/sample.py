from .domain import blank, uid

def sample():
    p = blank()
    p['title'] = '听乐片段 · 人工编写演示草稿'
    # Editorial paraphrase, not a primary-source transcription or AI-generated evidence.
    source = dict(id=uid(),version=1,title='故宫藏品说明 · 人工整理的阅读笔记（非原文）',citation='故宫博物院《顾闳中韩熙载夜宴图卷》 https://www.dpm.org.cn/collection/paint/228200.html',location='全图五段及首段听乐的介绍；请对照馆方网页复核',text='馆方介绍将画卷分成听乐、观舞、暂歇、清吹、散宴五段。听乐段中，韩熙载与郎粲同坐床榻，聆听李家明之妹演奏琵琶；李家明在妹妹旁边。此笔记仅概括馆方描述，不包含现场对白或人物动机的历史记录。')
    p['sources'] = [source]
    for name, identity in [('韩熙载','宴会主人'),('郎粲','听乐宾客'),('琵琶演奏者','馆方说明中的李家明之妹'),('李家明','演奏者之兄')]:
        p['characters'].append(dict(id=uid(),name=name,identity=identity,relationships='参考所附阅读笔记，需人工复核',knowledge='仅知道本片段现场可见的宴乐；不预设他人内心',evidence=source['id']+'，馆方藏品说明阅读笔记',confirmed=False))
    p['intent'].update(theme='同一场音乐中的不同注意',goal='通过宴乐片段探索人物关系，明确区分画面描述和创作对白',fixed='不改变人工确认的画面人物与活动',forbidden='不得把现场对白、心理和动机描述为确证历史')
    for title,goal,text in [('落座','引入听乐情境','韩熙载与郎粲同坐床榻，聆听琵琶演奏。'),('弦间','以虚构对白衔接人物注意','郎粲轻声说道：“且听这一段。”'),('余音','结束本片段并留下可探索线索','演奏者暂缓手势，席间的谈话也随之放轻。')]:
        category = 'supported' if title=='落座' else 'fiction'
        u = dict(id=uid(),text=text,kind='dialogue' if title=='弦间' else 'action',category=category,speakerId=p['characters'][1]['id'] if title=='弦间' else '',rationale='人工编写演示内容，非模型生成；对白与过渡动作为虚构。',references=[dict(sourceId=source['id'],sourceVersion=1,quote='听乐段中，韩熙载与郎粲同坐床榻，聆听李家明之妹演奏琵琶；李家明在妹妹旁边。')] if category=='supported' else [],status='pending',locked=False)
        p['scenes'].append(dict(id=uid(),title=title,goal=goal,connection='同一听乐片段中的连续叙事节拍，并非画卷原有三个段落',characterIds=[c['id'] for c in p['characters']],units=[u]))
    return p
