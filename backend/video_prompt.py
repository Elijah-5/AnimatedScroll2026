"""Deterministic director brief and checks, based on the published Wan guides."""
import re

GUIDE_URL='https://help.aliyun.com/zh/model-studio/text-to-video-prompt'
POLICY='painting-director-v5'


def compile(inputs,duration,style):
    shot=inputs['shot'];refs=inputs['references']
    cast=[]
    for person in inputs['people']:
        ref=next((r for r in refs if r.get('characterId')==person['id']),None)
        if not ref:continue
        instances=person.get('boxes',[])
        count=f"，原画共 {len(instances)} 个身影，保持群体数量与各自位置" if person['profile'].get('roleType')=='group' else ''
        cast.append(f"{ref['label']}的{person['name']}，沿用图1中的对应人物{count}")
    region=shot.get('region') or dict(x=0,y=0,w=1,h=1)
    area=f"原画横向 {region['x']*100:.0f}%–{(region['x']+region['w'])*100:.0f}%、纵向 {region['y']*100:.0f}%–{(region['y']+region['h'])*100:.0f}% 的选定区域"
    mapping='；'.join(r['label']+'＝'+r['name'] for r in refs)
    return (style+f'\n生成单镜头，{duration}秒，一镜到底。每镜只完成一个主要动作，动作自然克制，前后保持同一场景。'
            '\n原画与人物裁切是参考素材，不作为硬性首尾帧。图1用于原画风格与空间关系，各人物参考用于锁定其面貌、衣冠与身份；背景中的原有人物保持自然静止。'
            '\n参考索引：'+mapping+'\n参与动作的人物：'+('；'.join(cast) or '无人出镜，仅表现选定画面区域')+
            '\n构图：聚焦'+area+'，沿用原画人物的相对位置。不得把参考图拼成画面、分屏或新增边框。'
            '\n本镜情节：'+inputs['clue'].get('summary',inputs['clue'].get('name',''))+
            '\n完整分镜要求：'+shot['prompt']+
            '\n动作：'+shot.get('action','')+'\n运镜：'+(shot.get('camera') or '固定镜头')+
            f"\n节奏：0–1秒，{shot.get('startFrame','保持起始构图')}；1–{max(2,duration-1)}秒，完成上述主要动作；末1秒，{shot.get('endFrame','自然停稳')}。"+
            '\n绘画与质感：'+shot.get('style','')+
            '\n声音：无台词、无旁白、无背景音乐。无字幕、无新增人物、无现代物件，不改变人物的身份和原画风格。')


def audit(inputs,text,duration):
    shot=inputs['shot'];warnings=[];errors=[]
    if len(text)>19500:errors.append('完整提示词超过19500字符，请缩短后再提交')
    missing=[label for field,label in (('action','具体动作'),('camera','运镜'),('startFrame','起始画面'),('endFrame','结束画面')) if not shot.get(field,'').strip()]
    if missing:warnings.append('分镜尚缺少'+ '、'.join(missing)+'；建议补充后再生成')
    if not all(r['label'] in text for r in inputs['references']):warnings.append('最终文本未完整对应参考图编号，人物可能被模型重新设计')
    if inputs['people'] and any(not p.get('boxes') for p in inputs['people']):errors.append('出场人物缺少已确认的画中对应')
    region=shot.get('region')
    if region:
        def overlaps(box):
            width=max(0,min(box['x']+box['w'],region['x']+region['w'])-max(box['x'],region['x']))
            height=max(0,min(box['y']+box['h'],region['y']+region['h'])-max(box['y'],region['y']))
            return width*height>.05*box['w']*box['h']
        outside=[p['name'] for p in inputs['people'] if p.get('boxes') and not any(overlaps(box) for box in p['boxes'])]
        if outside:warnings.append('出场名单中的'+ '、'.join(outside)+'位于当前取景框外，请核对人物选择或画面区域')
    if re.search(r'固定.{0,6}或|或.{0,6}(?:推近|平移)',shot.get('camera','')):warnings.append('运镜仍有备选方案，请在固定镜头和移动镜头之间明确一种')
    if re.search(r'固定机位',shot.get('camera','')) and re.search(r'平移|移动机位',shot.get('camera','')):warnings.append('运镜同时写了固定机位和平移，请统一镜头运动')
    if re.search(r'不换位|保持原画姿态|仅有.{0,8}衣纹',shot.get('prompt','')+shot.get('action','')) and re.search(r'前行|迈步|走向|起身|站起',shot.get('endFrame','')):warnings.append('主体要求保持姿态，结束画面却出现位移或起身，请统一起止动作')
    if re.search(r'仅有.{0,8}衣纹|仅作.{0,8}衣纹',shot.get('action','')):warnings.append('当前主要是衣纹微动，历史情节依靠外部讲解；若希望演出剧情，请明确一个可见的主要动作')
    durations={int(v) for v in re.findall(r'(?<![\d–—\-])(?<![\d])(?:独立|时长|共|总计|持续)?\s*(\d+)\s*秒(?:分镜|视频|短片|钟)?',shot.get('prompt',''))}
    if durations and any(v!=duration for v in durations):warnings.append(f'原分镜包含不同的时长，请与本次{duration}秒设置统一')
    if not re.search(r'单镜头|一镜到底|single shot',text,re.I):warnings.append('未明确单镜头，可能出现额外切镜')
    if not re.search(r'无台词|无对白|No dialogue',text,re.I):warnings.append('未明确禁止台词，模型可能自行配音')
    if not re.search(r'笔触|绘画|画风|水墨|设色',text):warnings.append('缺少原画风格与材质约束')
    positive=re.sub(r'(?:不|禁止|避免|不要|无)[^，。；\n]{0,25}','',text)
    if re.search(r'真人实拍|照片级真实|3D渲染|现代卡通',positive,re.I):warnings.append('提示词可能要求改变原画风格，请检查真人化或3D描述')
    if re.search(r'不[动移]|静止不动',shot.get('prompt','')) and re.search(r'抬手|起身|走向|行走|转身',shot.get('action','')):warnings.append('完整提示词与动作字段可能存在运动冲突')
    return dict(policyVersion=POLICY,guideUrl=GUIDE_URL,errors=errors,warnings=warnings,
                checks=[dict(label='参考图编号齐全',passed=all(r['label'] in text for r in inputs['references'])),
                        dict(label='动作、运镜与起止字段齐全',passed=not missing),
                        dict(label='已声明原画风格',passed=bool(re.search(r'笔触|绘画|画风|水墨|设色',text))),
                        dict(label='已声明单镜头与声音边界',passed=bool(re.search(r'单镜头|一镜到底',text) and re.search(r'无台词|无对白',text)))],
                note='规则检查用于发现输入缺失与冲突；人物一致性和动作效果仍需生成后人工检查。')
