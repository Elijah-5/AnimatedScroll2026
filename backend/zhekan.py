from .domain import blank, uid

def sample(image):
    p=blank();p.update(title='折槛图 · 图片与资料创作示例',image=image,imageVersion=1)
    p['painting']=dict(name='宋人《折槛图》轴',artist='佚名，无作者款印',paintingPeriod='宋代',storyPeriod='西汉成帝时期，事件段未明确记年',material='绢本设色',dimensions='173.9 × 101.8 厘米',collection='台北故宫博物院',catalog='https://digitalarchive.npm.gov.tw/Collection/Detail/38?dep=P',imageNote='用户提供的画作局部截图，含浏览器控件，不代表完整立轴。人物框与身份均需实测及校准。')
    entries=[('画作档案与解释边界','用户提供资料；馆藏资料 https://digitalarchive.npm.gov.tw/Collection/Detail/38?dep=P','馆藏名称为宋人《折槛图》轴，佚名，无作者款印。绢本设色，173.9 × 101.8厘米，收藏于台北故宫博物院。故事发生在汉代，画作属于宋代绘画。用户提供的截图为局部图像，不是完整画作。馆方页面的部分概要将旧栏处理概括为保留原状；解读应对照《朱云传》的勿易、因而辑之，不把概述差异抹平。'),('朱云传 · 用户整理的事件笔记','《汉书》卷六十七《朱云传》 https://zh.wikisource.org/zh-hans/漢書/卷067','朱云在公卿面前指责大臣不能匡正君主、造福百姓，只是尸位素餐。他请求赐尚方斩马剑，处死佞臣，皇帝追问时点名安昌侯张禹。成帝以当众侮辱帝师为由震怒，命御史将朱云带走。朱云被带离时攀住殿前栏杆，栏杆折断，并非主动砸毁宫殿或折断门槛。传文记：“云攀殿槛，槛折。”朱云以关龙逢、比干自比。左将军辛庆忌免冠解印绶，叩头流血，请求容纳逆耳之言：“使其言是，不可诛；其言非，固当容之。”成帝息怒，朱云得以保全。后来修栏时皇帝要求不要换掉，而应修补旧栏，用来表彰直臣。此事件段未明确具体年份。以上是用户整理笔记，标出的短引文需对照原文版本。'),('主要人物 · 用户整理笔记','《汉书》卷六十七及卷八十一 https://zh.wikisource.org/zh-hans/漢書/卷081','朱云字游，鲁人，后迁平陵；青年时交游侠客、以勇力闻名，四十岁开始学习《易》《论语》，曾任博士、杜陵令、槐里令，兼有勇悍与经学修养。汉成帝是张禹的学生，长期信任张禹；事件中先震怒，后接受劝说。张禹为经学家、帝师、前丞相、安昌侯，退休后仍获礼遇并参与政事，不能只用奸臣标签代替背景。辛庆忌当时为左将军，免冠解印绶、以死争辩，是推动结局改变的关键人物。'),('张禹传 · 背景与时间边界','用户整理《汉书》卷八十一《张禹传》 https://zh.wikisource.org/zh-hans/漢書/卷081','张禹有经学专长，曾向太子教授《论语》；显贵后积累田产、生活奢华。皇帝在重要政事上征询其意见。面对灾异和王氏专权疑虑，他顾虑自身及子孙，作出有利于消解皇帝疑虑的答复。这些是不同时间的背景材料，不等于折槛当天朱云提交的罪证清单，不得将其直接改写为当天已发生的证据收集。'),('互动创作意图 · 非史料','用户创作设想','可让观众以劝谏者身份，根据先前对话尝试劝服成帝。成功分支为释放朱云；未成功劝服分支提供反馈，只表示此次互动未达目标，不声称历史上朱云被处死。收集张禹背景线索触发进谏属于画作之外的虚构组织方式，不能表述为史料已载的当天流程。')]
    for title,citation,text in entries:
        p['sources'].append(dict(id=uid(),version=1,title=title,citation=citation,location='用户提供的整理材料，非完整原文转录',text=text,confirmed=False,method='user_notes',sourceType='creative_intent' if '互动创作意图' in title else 'historical_material'))
    p['materialInputs']=dict(background=p['sources'][0]['text']+'\n\n'+p['sources'][3]['text'],relationships=p['sources'][2]['text'],narrative=p['sources'][1]['text'],version=1)
    p['materialInputs']['background']+='\n\n出处：https://digitalarchive.npm.gov.tw/Collection/Detail/38?dep=P\n张禹传：https://zh.wikisource.org/zh-hans/漢書/卷081'
    p['materialInputs']['relationships']+='\n\n出处：《汉书》卷六十七《朱云传》及卷八十一《张禹传》。'
    p['materialInputs']['narrative']+='\n\n出处：https://zh.wikisource.org/zh-hans/漢書/卷067'
    identities=[('朱云','直谏者，曾任槐里令','与成帝公开争论，指责张禹'),('汉成帝','西汉皇帝，张禹的学生','信任帝师，后接受辛庆忌劝谏'),('张禹','经学家、帝师、前丞相、安昌侯','成帝之师，朱云进谏所针对的人物'),('辛庆忌','左将军','为朱云冒死辩护，劝成帝容纳异议')]
    for name,identity,relationships in identities:p['characters'].append(dict(id=uid(),name=name,identity=identity,relationships=relationships,knowledge='仅限经审核的当时身份、已发生事件与可见行动，不知道未来结局或他人内心',evidence='用户提供人物笔记，需对照《朱云传》《张禹传》',confirmed=False))
    p['intent'].update(theme='直谏与容纳异议',goal='围绕折槛与辛庆忌劝谏构建可追溯叙事；为后续观众劝谏互动保留线索',fixed='汉代事件与宋代绘画分开；朱云攀栏导致折断；辛庆忌劝谏后朱云获救；旧栏修补而非替换',allowed='过渡动作、未直接记载的对白与互动反馈均标为虚构；背景线索不得混入当天确证事件',forbidden='不得把门槛或砸殿当作折槛；不得拼接张禹不同时间事迹为当日罪证；不得把互动失败写成真实历史结局')
    return p
